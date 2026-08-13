# Team Lunch

Team Lunch is a terminal-only coordinator for DoorDash group orders. It creates a
shareable group cart, pauses while teammates add their food, previews the real
scheduled-delivery price, and requires an organizer to approve the tip and named
payment source before it submits anything.

## What the MVP does

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

## Recipient setup

The `team-lunch` executable contains the Python application, so recipients do not
need Python. DoorDash CLI remains a separate prerequisite because it owns login,
account access, cart operations, and checkout.

On each recipient's computer:

1. Install `dd-cli` and make sure it is available as `dd-cli` in the terminal.
2. Run `dd-cli login` and sign in with that person's own DoorDash account.
3. Put `team-lunch` and a copy of `config.example.json` in one folder.
4. Rename the copied configuration to `config.json` and adjust the team name,
   timezone, and spending limit.
5. Run `team-lunch doctor`, then `team-lunch start`.

Never transfer DoorDash access tokens, keychain entries, or payment details. Each
recipient signs in independently. A one-file executable is specific to the OS and
CPU it was built on; build separately for macOS, Windows, and Linux.

If `dd-cli` is not on `PATH`, run:

```text
team-lunch --dd-cli /full/path/to/dd-cli doctor
```

or set the `DD_CLI_PATH` environment variable.

## Commands

```text
team-lunch doctor
team-lunch start
team-lunch resume
team-lunch --config /path/to/config.json start
```

Choose `LATER` after creating the group cart to exit safely. The organizer can run
`team-lunch resume` after teammates finish ordering. The saved session contains a
cart identifier and group URL, not account credentials.

## Run from source

Python 3.9 or newer is required:

```text
python3 main.py doctor
python3 main.py start
python3 main.py resume
```

The application itself uses only Python's standard library.

## Build a standalone executable

Build on the same operating system and CPU family as the recipient:

```text
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-build.txt
.venv/bin/python build.py
```

On Windows, use `.venv\\Scripts\\python.exe` in the last two commands. The result
is `dist/team-lunch` on macOS/Linux or `dist/team-lunch.exe` on Windows. Transfer
that file together with a renamed `config.json`.

## Test

```text
python3 -m unittest discover -v
```

Tests use simulated DoorDash responses and never create a cart or place an order.

## Configuration

`config.example.json` documents every MVP setting. Relative receipt and session
paths are resolved beside the selected configuration file. Receipt files can
include the charged card's last four digits and are created with owner-only file
permissions where the operating system supports them.

Scheduled times are entered as `YYYY-MM-DD HH:MM` in the configured timezone. The
app converts them to an unambiguous UTC value and passes the exact same value to
both preview and submission.

## Important limitations

- Only the organizer/host needs this executable and `dd-cli`; teammates use the
  printed DoorDash group-cart link.
- DoorDash uses the signed-in account's current default address. The CLI does not
  provide a per-cart address override.
- The MVP prompts for required first-level item customizations. Deeply nested combo
  choices may need a simpler organizer item or completion in DoorDash.
- If the CLI cannot identify the default card, Team Lunch recommends browser
  checkout first because the account default might be a wallet.
- Final submission is intentionally attended. Scheduling prepares a delivery slot;
  it does not authorize an unattended future charge.
