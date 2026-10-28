# Step 24: Settings page

**Goal:** change the things people change most from the dashboard, not by editing `.env` and restarting. Step 2 of the [sharing plan](../design/sharing.md).

## What was added

| Piece | Why |
| --- | --- |
| `settings` table (migration 0025) | Values saved on the page, as text, one row per setting |
| `config.get_settings()` | `.env` and the environment as before, with saved values on top; read again every 30 seconds, so the scheduler and dashboard pick up a change without a restart |
| `settings_store.py` | Save and remove a value, and say where a setting comes from (Settings page, `.env` or default) |
| `llm.check_key` | Checks a key with Anthropic by listing the models, which costs nothing |
| `orchestrator.scheduled_run` | A job turned off on the page is skipped on its schedule; a run by hand still runs |
| **Settings** page (eleven pages now) | See below |
| Guide | A "Settings" section, and the steps that used to say "edit `.env`" now point to the page |

## The page

- **AI features:**
  - whether a key is set and where it came from, showing only its last four characters
  - a key box: the key is checked with Anthropic before it is saved, and can be removed again
  - this month's spend against the budget, as a bar
  - the monthly budget, and the two models (sorting and extracting; explaining and analysing)
- **Unusual days:** the threshold, from 1.5 to 3.0 standard deviations.
- **Scheduled jobs:** every job with what it does and its next run, and a switch to turn it off.
- **Where each setting comes from:** Settings page, `.env` or default, for each setting.

Settings that need a restart or belong to a developer (the database address, the data folder, job times) stay in `.env` and `config/schedule.yaml`.

## Decisions

- **Saved values win over `.env`.** The plan had `.env` winning, for developers, but then the page would do nothing for anyone with a `.env`, the author included. Removing a saved value goes back to `.env`.
- **The key is kept in the local database,** as plain text, like `.env` keeps it. Only someone with access to the computer can read either.
- **Tests never read saved settings.** A test that blanks the API key to check that AI jobs are skipped would otherwise pick up a real key saved on the author's dashboard and call Anthropic. Tests that need saved settings are marked `saved_settings`.
- **Error messages** about a missing key now point to the Settings page instead of `.env`.

## Tests

`tests/test_settings.py`:
- a saved value replaces `.env`, is replaced when saved again, and removing it goes back to `.env`
- settings that can't be changed from the page are refused
- a value saved by another process is seen once the 30 seconds pass
- with no database, `.env` alone is used
- a paused job is skipped on its schedule but runs by hand
- the job descriptions are read from `config/schedule.yaml`
- an API key Anthropic refuses is reported

The page renders in `tests/test_ui.py`. Checked in a browser: saving a $5 budget updates the spend bar and the `settings` table.

## On the Mac

```
git checkout main
git pull
uv run sna db upgrade
make ui
```

Open **Settings**: your key and budget show as coming from `.env`. Save the budget there and it shows as coming from the Settings page.
