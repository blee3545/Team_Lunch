from __future__ import annotations

import json
import os
import re
import stat
import sys
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


def application_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def default_config_path() -> Path:
    beside_app = application_dir() / "config.json"
    if beside_app.exists():
        return beside_app
    return Path.cwd() / "config.json"


def load_config(path: Path) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {
        "team_name": "My Team",
        "timezone": "America/Los_Angeles",
        "restaurant_result_limit": 8,
        "menu_display_limit": 40,
        "spend_limit_dollars": 25,
        "status_poll_attempts": 6,
        "status_poll_seconds": 5,
        "receipts_directory": "receipts",
        "session_file": ".team-lunch-session.json",
    }
    if not path.exists():
        return defaults
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Could not read configuration at {path}: {exc}") from exc
    if not isinstance(loaded, dict):
        raise ValueError("Configuration must be a JSON object.")
    defaults.update(loaded)
    return defaults


def resolve_data_path(config_path: Path, configured: str) -> Path:
    path = Path(configured).expanduser()
    return path if path.is_absolute() else config_path.resolve().parent / path


def save_private_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    try:
        path.chmod(stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass


def save_json(path: Path, value: Dict[str, Any]) -> None:
    save_private_text(path, json.dumps(value, indent=2) + "\n")


def parse_local_schedule(raw: str, timezone_name: str, now: Optional[datetime] = None) -> str:
    try:
        zone = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError as exc:
        raise ValueError(f"Unknown timezone '{timezone_name}'.") from exc
    try:
        local = datetime.strptime(raw.strip(), "%Y-%m-%d %H:%M").replace(tzinfo=zone)
    except ValueError as exc:
        raise ValueError("Use YYYY-MM-DD HH:MM, for example 2026-08-13 12:00.") from exc
    current = now or datetime.now(timezone.utc)
    if local.astimezone(timezone.utc) <= current.astimezone(timezone.utc):
        raise ValueError("Scheduled delivery must be in the future.")
    return local.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def dollars_to_cents(raw: str) -> int:
    cleaned = raw.strip().replace("$", "")
    try:
        amount = Decimal(cleaned)
    except InvalidOperation as exc:
        raise ValueError("Enter a dollar amount such as 8 or 8.50.") from exc
    if amount < 0:
        raise ValueError("Amount cannot be negative.")
    cents = int((amount * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    if cents > 2_147_483_647:
        raise ValueError("Amount is too large.")
    return cents


def money_display(cents: int) -> str:
    return f"${cents / 100:.2f}"


def clean_item_id(value: Any) -> str:
    return re.sub(r"^i_", "", str(value or ""))


def flatten_menu_items(value: Any) -> List[Dict[str, Any]]:
    """Collect menu item records without duplicating IDs from nested sections."""
    found: List[Dict[str, Any]] = []
    seen = set()

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            item_id = node.get("item_id")
            name = node.get("name") or node.get("item_name")
            if item_id is not None and name and clean_item_id(item_id) not in seen:
                record = dict(node)
                record["item_id"] = clean_item_id(item_id)
                found.append(record)
                seen.add(record["item_id"])
            for child in node.values():
                walk(child)
        elif isinstance(node, list):
            for child in node:
                walk(child)

    walk(value)
    return found


def display_price(item: Dict[str, Any]) -> str:
    for key in ("price", "display_price", "price_display_string"):
        value = item.get(key)
        if isinstance(value, str) and value:
            return value
        if isinstance(value, (int, float)):
            return money_display(int(value))
    monetary = item.get("price_monetary_fields")
    if isinstance(monetary, dict):
        display = monetary.get("display_string")
        if display:
            return str(display)
    return ""


def select_number(prompt: str, count: int, *, allow_zero: bool = False) -> int:
    low = 0 if allow_zero else 1
    while True:
        raw = input(prompt).strip()
        try:
            selected = int(raw)
        except ValueError:
            print(f"Enter a number from {low} to {count}.")
            continue
        if low <= selected <= count:
            return selected
        print(f"Enter a number from {low} to {count}.")


def yes_no(prompt: str, *, default: Optional[bool] = None) -> bool:
    suffix = " [Y/n] " if default is True else " [y/N] " if default is False else " [y/n] "
    while True:
        value = input(prompt + suffix).strip().lower()
        if not value and default is not None:
            return default
        if value in {"y", "yes"}:
            return True
        if value in {"n", "no"}:
            return False
        print("Please answer y or n.")
