# Step 26: First-run setup

**Goal:** someone who has just installed the system gets from an empty database to a working dashboard without the command line. Step 4 of the [sharing plan](../design/sharing.md).

## What was added

| Piece | Why |
| --- | --- |
| `agents/setup.py` | The setup's work as plain functions: whether it is needed, the company list, example stocks, the history start date, loading prices |
| **Setup** screens | Four screens, shown instead of the normal sidebar until the setup is finished or skipped |
| `settings_store` flags | `setup_started` and `setup_done`, kept in the `settings` table |
| Settings | "Run the setup again" |
| `add_stock_form(offer_history=False)` | The Manage stocks form, reused without its own "Load history now" button |
| Guide | "Getting started" mentions the setup |

## The screens

1. **Welcome:** what the system does, what it needs (the computer on in the morning, optionally an API key), and that it isn't advice. Start, or skip the setup.
2. **AI features:** what the key turns on and what works without one, and where to get a key. The key is checked before it is saved. The monthly budget is offered at $5 for a new copy; an existing budget is kept.
3. **Your stocks:**
   - a new copy has no list of listed companies, so the screen first downloads it (about a minute)
   - then the usual add-a-stock form, or one button to start with five large companies (Reliance, HDFC Bank, Infosys, L&T, ITC)
   - Next waits for at least one stock
4. **History:**
   - how far back: 1 year, 2 years or since October 2023, with an estimate of the time
   - loading fetches daily prices for every listed stock (about two requests a trading day; a new copy has none), then each stock's filings, news and corporate actions
   - problems are listed, and running it again fills the gaps
   - it ends by saying to start the scheduler, then goes to Today

## When it shows

- **A new copy** (no stocks yet) opens on it.
- **A copy with stocks** never sees it, so the author's dashboard is unchanged.
- **Once started,** it stays on until it is finished or skipped, even after the first stock is added or the browser is reloaded. The first version ended the setup as soon as the first stock was added, because "no stocks" was the only test.
- **Settings** can start it again; nothing is removed.

## Checked in a browser, on an empty database

Walked through every screen on a new, empty database:
- **Welcome and AI features:** both work, and "Continue without AI" moves on.
- **Downloading the company list:** with no internet in the sandbox, it fails with a clear message and the Back button stays. The first version hid the message inside the collapsed status box.
- **Your stocks:** the database was then seeded with companies; adding stocks and Next work.
- **History:** a price download that fails is now listed as a problem and the setup carries on with the stocks. The first version crashed with a traceback.
- **When something failed:** the end screen says what to do rather than "Done".
- **Go to Today:** finishes the setup and opens the normal dashboard.

## Tests

`tests/test_setup.py`:
- a new copy needs the setup until it is finished
- a copy with stocks never does
- a started setup stays on after stocks are added
- the example stocks and the company-list check
- the history start, never before October 2023
- price-loading progress lines

`tests/test_ui.py`:
- each of the four screens renders
- `main()` shows only Setup and Guide for a new copy

## On the Mac

```
git checkout main
git pull
make ui
```

Your dashboard won't show the setup, since it has stocks. To see it, use **Run the setup again** on Settings and step through. It removes nothing, and Skip ends it.
