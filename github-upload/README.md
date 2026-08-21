# Team Lunch

Team Lunch is a terminal-only coordinator for DoorDash group orders. It creates a
shareable group cart, pauses while teammates add their food, previews the real
scheduled-delivery price, and requires an organizer to approve the tip and named
payment source before it submits anything.

Team Lunch v0.3.0 requires DoorDash CLI v0.2.3 or newer.

## Quickstart

Only the lunch organizer installs Team Lunch. Teammates join through the group-cart
link it creates.

After extracting the distribution ZIP, open a terminal in that folder and run:

```bash
dd-cli --version
dd-cli login
cp config.example.json config.json
chmod +x team-lunch
./team-lunch doctor
./team-lunch start
```

Edit `config.json` before starting if you want to change the team name, timezone,
or per-person spending limit. At startup, choose one of the organizer's saved
DoorDash delivery addresses. Changing it also changes that account's default
address across DoorDash, so Team Lunch asks for confirmation first. After a
restaurant search, enter a result number or `R` to let restaurant roulette pick.
When the group-cart link appears, share it with the team. Type `LATER` if you want
to close the program while teammates add their items, then continue with:

```bash
./team-lunch resume
```

Review the final DoorDash preview carefully. The order is charged and submitted
only when the organizer enters `PLACE ORDER` at the final confirmation prompt.
Entering anything else leaves the cart unsubmitted.

On Windows, use `copy config.example.json config.json` and run
`team-lunch.exe` instead; `chmod` is not needed. The executable must match the
recipient's operating system and processor.

## What the MVP does

1. Lists saved delivery addresses and lets the organizer choose one.
2. Searches restaurants and offers manual selection or no-repeat roulette.
3. Creates a host-pays group cart with an optional per-person spending limit.
4. Prints the group-cart link and saves a resumable local session.
5. Lets the organizer apply an eligible promotion.
6. Previews ASAP or scheduled delivery and offers eligible company meal budgets.
7. Shows DoorDash's canonical itemized preview.
8. Collects an explicit Dasher tip and identifies the card or company budget.
9. Requires the organizer to type `PLACE ORDER` before charging anything.
10. Polls the v0.2.3 order lifecycle until the order is created or needs attention,
    then saves a private text receipt for successfully created orders.

The app never retries order submission. A retry could create a duplicate order.

## Recipient setup

The `team-lunch` executable contains the Python application, so recipients do not
need Python. DoorDash CLI remains a separate prerequisite because it owns login,
account access, cart operations, and checkout.

On each recipient's computer:

1. Install [DoorDash CLI v0.2.3 or newer](https://github.com/doordash-oss/doordash-cli/releases)
   and make sure it is available as `dd-cli` in the terminal.
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

## Restaurant roulette

Restaurant results are always shown before selection. At the restaurant prompt:

- Enter a result number to choose manually.
- Enter `R` to spin restaurant roulette.
- Accept the winner, reroll, return to manual selection, or quit.
- Rerolls do not repeat restaurants. After every result has appeared, Team Lunch
  returns to manual selection.

Roulette is deliberately fair and simple: every displayed search result has an
equal chance. It does not inspect order history, ratings, fees, or delivery times.

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

## Future ideas

- Smart roulette that avoids recent restaurants using group-order history.
- New-address onboarding using DoorDash CLI's address search and save commands.
- A live delivery tracker showing ETA, delays, Dasher progress, and cancellation.
- A team reorder board for recreating favorite hosted or joined group orders.
- Recurring lunch templates that retain attended final checkout.
- Lunch analytics for restaurant rotation, spending, promotions, and reliability.

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
- DoorDash does not provide a per-cart address override. Choosing a different
  saved address changes the signed-in account's default across the CLI, app, and
  website until it is changed again.
- Team Lunch currently selects existing saved addresses. DoorDash CLI v0.2.3 can
  add new addresses, but that flow is intentionally deferred to a future release.
- The MVP prompts for required first-level item customizations. Deeply nested combo
  choices may need a simpler organizer item or completion in DoorDash.
- If the CLI cannot identify the default card, Team Lunch recommends browser
  checkout first because the account default might be a wallet.
- Final submission is intentionally attended. Scheduling prepares a delivery slot;
  it does not authorize an unattended future charge.
