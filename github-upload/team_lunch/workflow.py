from __future__ import annotations

import json
import secrets
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .ddcli import DDCLI, DDCLIError, find_mapping_with_key, response_list, response_value
from .utils import (
    clean_item_id,
    display_price,
    dollars_to_cents,
    flatten_menu_items,
    money_display,
    parse_local_schedule,
    resolve_data_path,
    save_json,
    save_private_text,
    select_number,
    yes_no,
)


class Cancelled(RuntimeError):
    pass


ORDER_CREATED_STATUSES = frozenset(
    {
        "placed",
        "scheduled",
        "store_confirmed",
        "ready_for_pickup",
        "dasher_assigned",
        "dasher_at_store",
        "picked_up",
        "dasher_nearby",
        "completed",
    }
)


class LunchWorkflow:
    def __init__(self, dd: DDCLI, config: Dict[str, Any], config_path: Path) -> None:
        self.dd = dd
        self.config = config
        self.config_path = config_path
        self.session_path = resolve_data_path(config_path, str(config["session_file"]))

    def start(self) -> None:
        self.dd.require_minimum_version()
        print(f"\nTeam Lunch — {self.config['team_name']}")
        print("This creates a real DoorDash group cart. Nothing is charged until final approval.\n")
        delivery_address = self._choose_delivery_address()
        store = self._choose_store(delivery_address)
        self._handle_existing_cart(store)
        menu_response = self.dd.run_json(["menu", "--store-id", str(store["store_id"])])
        menu_id = str(response_value(menu_response, "menu_id", ""))
        items = flatten_menu_items(menu_response)
        if not menu_id or not items:
            raise DDCLIError("No usable restaurant menu was returned. Try another restaurant.")
        item, quantity, nested_options = self._choose_host_item(store, menu_id, items)
        cart = self._create_group_cart(store, menu_id, item, quantity, nested_options)
        cart_uuid = str(response_value(cart, "cart_uuid", ""))
        if not cart_uuid:
            raise DDCLIError("The group cart response did not include a cart ID.")
        group_url = self._group_url(cart)
        session = {
            "cart_uuid": cart_uuid,
            "store_id": str(store["store_id"]),
            "store_name": self._store_name(store),
            "group_cart_url": group_url,
            "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        }
        save_json(self.session_path, session)
        print("\nGroup cart created.")
        print(f"Cart ID: {cart_uuid}")
        if group_url:
            print(f"Share this link with teammates:\n{group_url}")
        else:
            print("The CLI did not return a share link. The cart ID was saved so you can resume.")
        print(f"\nSession saved at {self.session_path}")
        value = input("Press Enter after teammates finish adding items, or type LATER to exit: ").strip()
        if value.lower() == "later":
            print("Run 'team-lunch resume' when the cart is ready.")
            return
        self.finish(session)

    def resume(self) -> None:
        self.dd.require_minimum_version()
        if not self.session_path.exists():
            raise DDCLIError(f"No saved lunch session was found at {self.session_path}.")
        try:
            session = json.loads(self.session_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise DDCLIError(f"The saved session could not be read: {exc}") from exc
        if not isinstance(session, dict) or not session.get("cart_uuid"):
            raise DDCLIError("The saved lunch session is invalid.")
        self.finish(session)

    def finish(self, session: Dict[str, Any]) -> None:
        cart_uuid = str(session["cart_uuid"])
        store_id = str(session.get("store_id", ""))
        print("\nCurrent group cart")
        print(self.dd.run_text(["cart", "show", "--cart-uuid", cart_uuid]))
        self._offer_promotion(store_id, cart_uuid)
        scheduled_time = self._ask_schedule()
        preview_args = ["order", "preview", "--cart-uuid", cart_uuid]
        if scheduled_time:
            preview_args.extend(["--scheduled-time", scheduled_time])
        preview_args.append("--include-work-benefits")
        preview_json = self.dd.run_json(preview_args)
        self._require_success(preview_json, "Order preview failed")
        selected_budget = self._choose_budget(preview_json)
        if selected_budget:
            preview_args = [arg for arg in preview_args if arg != "--include-work-benefits"]
            preview_args.extend(["--selected-budget-id", str(selected_budget["id"])])
            preview_json = self.dd.run_json(preview_args)
            self._require_success(preview_json, "Budget preview failed")
        print("\nFinal DoorDash preview")
        print("=" * 72)
        print(self.dd.run_text([*preview_args, "--beautify"]))
        print("=" * 72)
        self._confirm_pin_if_needed(preview_json)
        tip_cents = self._ask_tip(preview_json)
        submit_args = [
            "order",
            "submit",
            "--cart-uuid",
            cart_uuid,
            "--tip-cents",
            str(tip_cents),
        ]
        if scheduled_time:
            submit_args.extend(["--scheduled-time", scheduled_time])
        payment_description = self._prepare_payment(preview_json, selected_budget, submit_args, cart_uuid)
        confirmation = input(
            f"\nType PLACE ORDER to charge {payment_description} and submit this order: "
        ).strip()
        if confirmation != "PLACE ORDER":
            print("Order not submitted. Your group cart and saved session were left intact.")
            return
        submit_args.append("--yes")
        try:
            result = self.dd.run_json(submit_args, timeout=40)
        except DDCLIError as exc:
            text = f"{exc} {exc.stdout} {exc.stderr}".lower()
            if "restricted" in text or "age-restricted" in text:
                print("This cart contains a restricted item and must be completed in DoorDash.")
                self._print_checkout_url(cart_uuid)
                return
            raise
        order_uuid = str(response_value(result, "order_uuid", ""))
        if not order_uuid:
            raise DDCLIError(
                "DoorDash accepted the submit request but did not return an order ID. "
                "Check order history before trying again; re-submitting can create a duplicate."
            )
        status = self._poll_status(order_uuid)
        self._show_order_status(order_uuid, status)
        if status in ORDER_CREATED_STATUSES:
            print("\nOrder created successfully.")
            try:
                self._save_receipt(order_uuid)
            except DDCLIError as exc:
                print(f"The receipt is not available yet: {exc}")
            try:
                self.session_path.unlink()
            except OSError:
                pass
        elif status == "action_required":
            print("\nDoorDash needs a verification step. Finish it in the DoorDash app or website.")
            self._offer_checkout_fallback(cart_uuid)
        elif status == "order_declined":
            print("\nThe order did not go through. Review it in DoorDash; do not re-submit this cart blindly.")
            self._offer_checkout_fallback(cart_uuid)
        elif status == "cancelled":
            print("\nDoorDash reports that this order was cancelled. Review the order in DoorDash.")
        elif status == "not_found":
            print("\nDoorDash could not find the submitted order. Check order history before trying anything else.")
        elif status in {"unavailable", "unknown"}:
            print(
                "\nThe final order state could not be determined. Check DoorDash or order history; "
                "do not re-submit this cart."
            )
        else:
            print("\nThe order is still pending. Check DoorDash or run the status command later; do not re-submit.")

    def doctor(self) -> None:
        print(f"dd-cli found: {self.dd.resolve()}")
        print(f"dd-cli version: {self.dd.require_minimum_version()}")
        try:
            response = self.dd.run_json(["address", "list"])
        except DDCLIError as exc:
            print(f"Sign-in check failed: {exc}")
            print("Run 'dd-cli login', then try again.")
            return
        addresses = response_list(response, "addresses")
        print(f"DoorDash sign-in check: OK ({len(addresses)} saved address record(s))")
        print(f"Configuration: {self.config_path}")
        print(f"Session storage: {self.session_path}")

    def _choose_delivery_address(self) -> Dict[str, Any]:
        response = self.dd.run_json(["address", "list"])
        addresses = response_list(response, "addresses")
        if not addresses:
            raise DDCLIError("No saved delivery addresses were found in DoorDash.")

        # Match DoorDash's human-facing grouping: current default, labeled, other.
        default = next((entry for entry in addresses if entry.get("is_default") is True), None)
        ordered: List[Dict[str, Any]] = []
        seen = set()
        groups = [
            [default] if default else [],
            [entry for entry in addresses if entry is not default and entry.get("label")],
            [entry for entry in addresses if entry is not default and not entry.get("label")],
        ]
        for group in groups:
            for entry in group:
                address_id = str(entry.get("address_id") or "")
                identity = address_id or str(entry.get("printable_address") or id(entry))
                if identity not in seen:
                    ordered.append(entry)
                    seen.add(identity)

        print("Delivery addresses")
        for index, address in enumerate(ordered, 1):
            label = address.get("label") or "Saved address"
            printable = address.get("printable_address") or "Address details unavailable"
            marker = " (current default)" if address is default else ""
            print(f"{index:>2}. {label} — {printable}{marker}")

        default_index = ordered.index(default) + 1 if default in ordered else None
        while True:
            suffix = f" [{default_index}]" if default_index else ""
            raw = input(f"Choose the delivery address{suffix}: ").strip()
            if not raw and default_index:
                choice = default_index
                break
            try:
                choice = int(raw)
            except ValueError:
                print(f"Enter a number from 1 to {len(ordered)}.")
                continue
            if 1 <= choice <= len(ordered):
                break
            print(f"Enter a number from 1 to {len(ordered)}.")

        selected = ordered[choice - 1]
        if selected is default:
            print("Using the current DoorDash default address.\n")
            return selected

        selected_label = selected.get("label") or "the selected saved address"
        selected_printable = selected.get("printable_address") or "address details unavailable"
        print(
            "\nDoorDash can only change the account-wide default address. "
            "This selection will persist in the DoorDash app, website, and future orders."
        )
        if not yes_no(
            f"Set {selected_label} — {selected_printable} as the account-wide default?",
            default=False,
        ):
            raise Cancelled("Delivery address was not changed; no cart was created.")
        address_id = str(selected.get("address_id") or "")
        if not address_id:
            raise DDCLIError("The selected address did not include an address ID.")
        changed = self.dd.run_json(
            ["address", "set", "--address-id", address_id, "--yes"]
        )
        self._require_success(changed, "Could not change the delivery address")
        print(f"Delivery address changed to {selected_label} — {selected_printable}.\n")
        return selected

    def _choose_store(self, default_address: Dict[str, Any]) -> Dict[str, Any]:
        query = input("What kind of restaurant should we search for? ").strip()
        if not query:
            raise Cancelled("No restaurant search was entered.")
        limit = int(self.config.get("restaurant_result_limit", 8))
        args = ["search", "--query", query, "--limit", str(limit)]
        lat = default_address.get("lat")
        lng = default_address.get("lng")
        if lat is not None and lng is not None:
            args.extend(["--lat", str(lat), "--lng", str(lng)])
        response = self.dd.run_json(args)
        stores = response_list(response, "stores")
        if not stores:
            raise DDCLIError("No restaurants matched that search. Try a different description.")
        print("\nRestaurants")
        for index, store in enumerate(stores, 1):
            print(f"{index:>2}. {self._store_display(store)}")
        return self._select_store(stores)

    def _select_store(self, stores: List[Dict[str, Any]]) -> Dict[str, Any]:
        while True:
            raw = input("Choose a restaurant number, R for roulette, or Q to cancel: ").strip().lower()
            if raw in {"r", "roulette"}:
                return self._roulette_store(stores)
            if raw in {"q", "quit", "cancel"}:
                raise Cancelled("Restaurant selection cancelled; no cart was created.")
            try:
                selected = int(raw)
            except ValueError:
                print(f"Enter a number from 1 to {len(stores)}, R, or Q.")
                continue
            if 1 <= selected <= len(stores):
                return stores[selected - 1]
            print(f"Enter a number from 1 to {len(stores)}, R, or Q.")

    def _roulette_store(self, stores: List[Dict[str, Any]]) -> Dict[str, Any]:
        remaining = list(stores)
        while remaining:
            winner = secrets.choice(remaining)
            remaining.remove(winner)
            print(f"\nRoulette picked: {self._store_display(winner)}")
            while True:
                action = input("[A]ccept, [R]eroll, [M]anual selection, or [Q]uit: ").strip().lower()
                if action in {"", "a", "accept"}:
                    return winner
                if action in {"r", "reroll"}:
                    if remaining:
                        break
                    print("Every restaurant has appeared. Returning to manual selection.")
                    return self._select_store_manual(stores)
                if action in {"m", "manual"}:
                    return self._select_store_manual(stores)
                if action in {"q", "quit", "cancel"}:
                    raise Cancelled("Restaurant roulette cancelled; no cart was created.")
                print("Enter A, R, M, or Q.")
        return self._select_store_manual(stores)

    @staticmethod
    def _select_store_manual(stores: List[Dict[str, Any]]) -> Dict[str, Any]:
        return stores[select_number("Choose a restaurant: ", len(stores)) - 1]

    def _handle_existing_cart(self, store: Dict[str, Any]) -> None:
        store_id = str(store["store_id"])
        response = self.dd.run_json(["cart", "list", "--store-id", store_id])
        carts = response_list(response, "carts")
        if not carts:
            return
        print(f"\nThere is already an open cart at {self._store_name(store)}.")
        print("Creating another cart could unexpectedly append to it.")
        if yes_no("Delete that existing cart and create a fresh group cart?", default=False):
            confirmation = input("Type DELETE CART to confirm: ").strip()
            if confirmation != "DELETE CART":
                raise Cancelled("Existing cart was not deleted.")
            cart_uuid = str(carts[0].get("cart_uuid", ""))
            if not cart_uuid:
                raise DDCLIError("The existing cart did not include a cart ID.")
            self.dd.run_json(["cart", "delete", "--cart-uuid", cart_uuid])
            return
        raise Cancelled("Choose a different restaurant or resolve the existing cart in DoorDash.")

    def _choose_host_item(
        self, store: Dict[str, Any], menu_id: str, items: List[Dict[str, Any]]
    ) -> Tuple[Dict[str, Any], int, List[Dict[str, Any]]]:
        shown = items[: int(self.config.get("menu_display_limit", 40))]
        print("\nChoose one organizer item to initialize the group cart")
        for index, item in enumerate(shown, 1):
            price = display_price(item)
            print(f"{index:>2}. {item.get('name') or item.get('item_name')} {price}".rstrip())
        item = shown[select_number("Item: ", len(shown)) - 1]
        quantity = select_number("Quantity (1-20): ", 20)
        details = self.dd.run_json(
            [
                "restaurant-item-details",
                "--store-id",
                str(store["store_id"]),
                "--menu-id",
                menu_id,
                "--item-id",
                clean_item_id(item["item_id"]),
            ]
        )
        nested_options = self._choose_required_options(details)
        return item, quantity, nested_options

    def _choose_required_options(self, details: Dict[str, Any]) -> List[Dict[str, Any]]:
        extras = response_list(details, "extras")
        chosen: List[Dict[str, Any]] = []
        for extra in extras:
            minimum = int(extra.get("min_num_options") or extra.get("min") or 0)
            if minimum <= 0:
                continue
            options = [option for option in extra.get("options", []) if isinstance(option, dict)]
            if not options:
                continue
            name = str(extra.get("name") or "Required choice")
            print(f"\n{name} (choose {minimum})")
            for index, option in enumerate(options, 1):
                print(f"{index:>2}. {option.get('name', 'Option')} {display_price(option)}".rstrip())
            available = list(options)
            for _ in range(minimum):
                picked_index = select_number("Choice: ", len(available)) - 1
                picked = available.pop(picked_index)
                chosen.append(
                    {"id": str(picked.get("option_id") or picked.get("id")), "name": picked.get("name"), "quantity": 1}
                )
        return chosen

    def _create_group_cart(
        self,
        store: Dict[str, Any],
        menu_id: str,
        item: Dict[str, Any],
        quantity: int,
        nested_options: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "item_id": clean_item_id(item["item_id"]),
            "item_name": item.get("name") or item.get("item_name"),
            "quantity": quantity,
        }
        if nested_options:
            payload["nested_options"] = nested_options
        args = [
            "cart",
            "add-items",
            "--store-id",
            str(store["store_id"]),
            "--menu-id",
            menu_id,
            "--items-json",
            json.dumps([payload], separators=(",", ":")),
            "--group-cart",
        ]
        limit = self.config.get("spend_limit_dollars")
        if limit not in (None, "", 0, 0.0):
            args.extend(["--spend-limit-cents", str(dollars_to_cents(str(limit)))])
        response = self.dd.run_json(args)
        self._require_success(response, "Could not create the group cart")
        return response

    def _group_url(self, response: Dict[str, Any]) -> str:
        value = response_value(response, "group_cart_url", "")
        return str(value or "")

    def _offer_promotion(self, store_id: str, cart_uuid: str) -> None:
        if not store_id:
            return
        response = self.dd.run_json(["promo", "list", "--store-id", store_id])
        promotions = response_list(response, "promotions")
        if not promotions:
            return
        print("\nEligible promotions")
        for index, promo in enumerate(promotions, 1):
            title = promo.get("title") or promo.get("code") or "Promotion"
            description = promo.get("description") or ""
            print(f"{index:>2}. {title} {description}".rstrip())
        print(" 0. Skip promotions")
        choice = select_number("Apply which promotion? ", len(promotions), allow_zero=True)
        if choice == 0:
            return
        promo = promotions[choice - 1]
        args = ["promo", "apply", "--cart-uuid", cart_uuid, "--promo-code", str(promo.get("code", ""))]
        for field, flag in (
            ("campaign_id", "--campaign-id"),
            ("ad_group_id", "--ad-group-id"),
            ("ad_id", "--ad-id"),
        ):
            if promo.get(field):
                args.extend([flag, str(promo[field])])
        applied = self.dd.run_json(args)
        if response_value(applied, "success", False):
            discount = int(response_value(applied, "discount_cents", 0) or 0)
            print(f"Promotion applied ({money_display(discount)} discount).")
        else:
            print(f"Promotion was not applied: {response_value(applied, 'message', 'unknown reason')}")

    def _ask_schedule(self) -> Optional[str]:
        zone = str(self.config.get("timezone", "America/Los_Angeles"))
        while True:
            raw = input(
                f"\nScheduled delivery in {zone} (YYYY-MM-DD HH:MM), or Enter for ASAP: "
            ).strip()
            if not raw:
                return None
            try:
                return parse_local_schedule(raw, zone)
            except ValueError as exc:
                print(exc)

    def _choose_budget(self, preview: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        budgets = response_list(preview, "all_eligible_expense_order_budgets")
        eligible = []
        for budget in budgets:
            remaining = budget.get("remaining_amount")
            if isinstance(remaining, dict) and int(remaining.get("unit_amount") or 0) > 0:
                eligible.append(budget)
        if not eligible:
            return None
        print("\nAvailable company budgets")
        for index, budget in enumerate(eligible, 1):
            remaining = budget.get("remaining_amount", {})
            print(f"{index:>2}. {budget.get('name', 'Company budget')} — {remaining.get('display_string', '')}")
        print(" 0. Do not use a company budget")
        choice = select_number("Choose a budget: ", len(eligible), allow_zero=True)
        return None if choice == 0 else eligible[choice - 1]

    def _confirm_pin_if_needed(self, preview: Dict[str, Any]) -> None:
        quote = find_mapping_with_key(preview, "dropoff_options") or {}
        options = quote.get("dropoff_options", [])
        needs_pin = any(
            isinstance(option, dict) and option.get("proof_of_delivery_type") == "PIN_CODE"
            for option in options
        )
        if needs_pin and not yes_no(
            "This order requires a PIN at handoff. Do you accept the PIN handoff?", default=False
        ):
            raise Cancelled("PIN handoff was not accepted; order was not submitted.")

    def _ask_tip(self, preview: Dict[str, Any]) -> int:
        suggestions = response_list(preview, "tips_suggestion_details")
        suggested_cents = 0
        for suggestion in suggestions:
            for key in ("tip_amount", "amount", "tip_amount_monetary_fields"):
                value = suggestion.get(key)
                if isinstance(value, dict) and value.get("unit_amount") is not None:
                    suggested_cents = int(value["unit_amount"])
                    break
                if isinstance(value, int):
                    suggested_cents = value
                    break
            if suggested_cents:
                break
        if suggested_cents:
            prompt = f"Dasher tip in dollars (suggested {money_display(suggested_cents)}, 0 to skip): "
        else:
            prompt = "Dasher tip in dollars (0 to skip): "
        while True:
            raw = input(prompt).strip()
            try:
                return dollars_to_cents(raw)
            except ValueError as exc:
                print(exc)

    def _prepare_payment(
        self,
        preview: Dict[str, Any],
        budget: Optional[Dict[str, Any]],
        submit_args: List[str],
        cart_uuid: str,
    ) -> str:
        if budget:
            quote = find_mapping_with_key(preview, "company_payment_info") or {}
            company = quote.get("company_payment_info", {})
            team_info = company.get("team_order_info", {}) if isinstance(company, dict) else {}
            team_id = team_info.get("team_id") if isinstance(team_info, dict) else None
            if not team_id:
                raise DDCLIError("The selected company budget did not return a team identifier.")
            submit_args.extend(["--team-id", str(team_id), "--budget-id", str(budget["id"])])
            if budget.get("team_account_id"):
                submit_args.extend(["--team-account-id", str(budget["team_account_id"])])
            if str(budget.get("expense_code_mode", "NONE")) != "NONE":
                code = input("Expense code: ").strip()
                if not code:
                    raise Cancelled("An expense code is required to use this budget.")
                submit_args.extend(["--expense-code", code])
            if budget.get("is_expense_note_required"):
                notes = input("Expense note: ").strip()
                if not notes:
                    raise Cancelled("An expense note is required to use this budget.")
                submit_args.extend(["--expense-notes", notes])
            remaining = budget.get("remaining_amount", {})
            return f"the {budget.get('name', 'company')} budget ({remaining.get('display_string', 'available')})"
        try:
            methods = self.dd.run_json(["payment-method", "list"])
            cards = response_list(methods, "cards")
            default_id = response_value(methods, "default_payment_method_id", None)
            card = next(
                (
                    item
                    for item in cards
                    if str(item.get("payment_method_id")) == str(default_id)
                ),
                None,
            )
        except DDCLIError:
            card = None
        if card:
            return f"your {card.get('brand', 'card')} ending {card.get('last4', '????')}"
        print(
            "\nThe CLI cannot identify the account default; it may be a card or wallet. "
            "The safest option is browser checkout so you can verify it."
        )
        if yes_no("Open browser checkout instead of submitting from this app?", default=True):
            self._print_checkout_url(cart_uuid)
            raise Cancelled("Continue checkout in the browser; the CLI order was not submitted.")
        return "whatever default payment method DoorDash has on file (card or wallet)"

    def _print_checkout_url(self, cart_uuid: str) -> None:
        response = self.dd.run_json(["order", "checkout-url", "--cart-uuid", cart_uuid])
        url = response_value(response, "checkout_url", "") or response_value(response, "url", "")
        if url:
            print(f"Checkout URL:\n{url}")
        else:
            print("Open this cart in the DoorDash app or website to finish checkout.")

    def _offer_checkout_fallback(self, cart_uuid: str) -> None:
        try:
            self._print_checkout_url(cart_uuid)
        except DDCLIError:
            print("Open DoorDash in the app or on the website to review the order.")

    def _poll_status(self, order_uuid: str) -> str:
        attempts = max(1, int(self.config.get("status_poll_attempts", 6)))
        delay = max(1, int(self.config.get("status_poll_seconds", 5)))
        for attempt in range(attempts):
            response = self.dd.run_json(["order", "status", "--order-uuid", order_uuid])
            status = self._classify_order_status(response)
            print(f"Order status: {status}")
            if status != "pending":
                return status
            if attempt + 1 < attempts:
                time.sleep(delay)
        return "pending"

    @staticmethod
    def _classify_order_status(response: Dict[str, Any]) -> str:
        payload = find_mapping_with_key(response, "result")
        if payload is None:
            return "unavailable"
        success = payload.get("success")
        result = payload.get("result")
        if success is False:
            return "unavailable"
        if result is None:
            return "not_found" if success is True else "unavailable"
        if success is not True or not isinstance(result, dict):
            return "unavailable"
        status = result.get("status")
        if not isinstance(status, str) or not status.strip():
            return "unknown"
        normalized = status.strip().lower()
        known = ORDER_CREATED_STATUSES | {
            "pending",
            "action_required",
            "order_declined",
            "cancelled",
        }
        return normalized if normalized in known else "unknown"

    def _show_order_status(self, order_uuid: str, fallback_status: str) -> None:
        print("\nFinal DoorDash status")
        print("=" * 72)
        try:
            print(
                self.dd.run_text(
                    ["order", "status", "--order-uuid", order_uuid, "--beautify"]
                )
            )
        except DDCLIError:
            print(f"Order status: {fallback_status}")
        print("=" * 72)

    def _save_receipt(self, order_uuid: str) -> None:
        receipt = self.dd.run_text(["order", "receipt", "--order-uuid", order_uuid, "--beautify"])
        directory = resolve_data_path(self.config_path, str(self.config["receipts_directory"]))
        path = directory / f"receipt-{order_uuid}.txt"
        save_private_text(path, receipt + "\n")
        print(f"Receipt saved privately at {path}")

    @staticmethod
    def _require_success(response: Dict[str, Any], prefix: str) -> None:
        success = response_value(response, "success", True)
        if success is False:
            message = response_value(response, "message", "DoorDash did not accept the request.")
            errors = response_list(response, "item_errors")
            if errors:
                detail = "; ".join(str(error.get("error_message") or error) for error in errors)
                message = f"{message} {detail}"
            raise DDCLIError(f"{prefix}: {message}")

    @staticmethod
    def _store_name(store: Dict[str, Any]) -> str:
        return str(store.get("name") or store.get("store_name") or "Restaurant")

    @classmethod
    def _store_display(cls, store: Dict[str, Any]) -> str:
        details = []
        for key in ("delivery_time", "delivery_fee", "distance"):
            if store.get(key):
                details.append(str(store[key]))
        suffix = f" — {' · '.join(details)}" if details else ""
        return f"{cls._store_name(store)}{suffix}"
