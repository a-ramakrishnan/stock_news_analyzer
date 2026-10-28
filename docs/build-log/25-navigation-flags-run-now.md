# Step 25: Grouped navigation, Red flags page, Run now

**Goal:** the dashboard does what the command line did for red flags and jobs, and its pages are easy to find. Step 3 of the [sharing plan](../design/sharing.md).

## What was added

| Piece | Why |
| --- | --- |
| Sidebar in groups | Today (Today, Red flags), Research (Stock, Ask, Themes, What moves the stock), Library (Filings, News), Set up (Manage stocks, Settings, System), Help (Guide) |
| **Red flags** page (twelve pages now) | Replaces `sna flags list` and `sna flags dismiss` |
| **Run a job now** on System | Replaces `sna run <job>` |
| `redflags.restore` | Open a dismissed flag again, keeping its note |
| `queries.flag_table` | Flags with their status, note and a link to the filing behind each |
| `orchestrator.running` | Whether a job is already running, so it isn't started twice |
| Guide | The sidebar's groups, the Red flags page, and running a job by hand |

## Red flags page

- **Filters:** severity (high and medium by default), period (30 days to 3 years), stock, and whether to show dismissed flags.
- **The table:** date raised, severity, stock, kind, what happened, status, your note, and a link to the filing.
- **Select a flag** to dismiss it with an optional note, or to open a dismissed one again.
- The red flags on Today and on the Stock page's Events tab now link here instead of naming the commands.

## Run a job now

- **Choosing a job:** every job, in the order `sna run all` runs them, each with its description from the schedule file.
- **While it runs:** the job's log lines appear in a status box as it works. It then shows the job's summary, or its error.
- **Recorded like a scheduled run:** it appears in Recent runs, and a job turned off on Settings still runs when started here.
- **One at a time:** if the job is already running (started in the last three hours and not finished), the button is disabled until it ends. A run left "running" by a restart longer ago doesn't block it.

The System page's schedule now shows jobs turned off on Settings, and drops the cron expressions.

## Decisions

- **"Manage stocks" keeps its name.** The plan suggested "My stocks"; the first-run setup in step 26 may change that page, so renaming it waits.
- **A run by hand blocks the page until it finishes.** Streamlit runs a page's code in one go. A long job such as a first `events` run takes minutes, and the page says to keep the tab open. Running jobs in the background would need a queue, which the scheduler already is.

## Tests

`tests/test_ui.py`:
- the Red flags page renders, and twelve pages sit in five groups
- a flag's text includes its detail; it is dismissed with a note, shown with "Show dismissed", and opened again
- a running job is seen, and one left "running" five hours ago isn't

Checked in a browser:
- the grouped sidebar shows
- the Red flags page lists flags, and dismissing one with a note saves both
- running `flags` from System shows its result

## On the Mac

```
git checkout main
git pull
make ui
```

Open **Red flags**, and try **Run a job now** on **System** with `flags`, which is quick and needs no AI.
