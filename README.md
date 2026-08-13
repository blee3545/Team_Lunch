# Team Lunch

Team Lunch is a terminal-only coordinator for DoorDash group orders. It creates a
shareable group cart, pauses while teammates add their food, previews the real
scheduled-delivery price, and requires an organizer to approve the tip and named
payment source before it submits anything.

## Quickstart

Only the lunch organizer installs Team Lunch. Teammates join through the group-cart
link it creates.

After extracting the distribution ZIP, open a terminal in that folder and run:

```bash
dd-cli login
cp config.example.json config.json
chmod +x team-lunch
./team-lunch doctor
./team-lunch start
```

Edit `config.json` before starting if you want to change the team name, timezone,
or per-person spending limit. When the group-cart link appears, share it with the
team. Type `LATER` if you want to close the program while teammates add their
items, then continue with:

```bash
./team-lunch resume
```

Review the final DoorDash preview carefully. The order is charged and submitted
only when the organizer enters `PLACE ORDER` at the final confirmation prompt.
Entering anything else leaves the cart unsubmitted.

On Windows, use `copy config.example.json config.json` and run
`team-lunch.exe` instead; `chmod` is not needed. The executable must match the
recipient's operating system and processor.

## What this does

1. Confirms the signed-in account's default delivery address.
2. Searches restaurants and checks for an existing cart collision.
3. Creates a host-pays group cart with an optional per-person spending limit.
4. Prints the group-cart link and saves a resumable local session.
5. Lets the organizer apply an eligible promotion.
6. Previews ASAP or scheduled delivery and offers eligible company meal budgets.
7. Shows DoorDash's canonical itemized preview.
8. Collects an explicit Dasher tip and identifies the card or company budget.
9. Requires the organizer to type `PLACE ORDER` before charging anything.
10. Polls the submitted order until it succeeds or needs attention, then saves a
    private text receipt.

The app never retries order submission. A retry could create a duplicate order.

