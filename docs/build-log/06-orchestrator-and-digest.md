# Step 6: Orchestrator (agent 0) + daily digest (agent 16, basic)

**Goal:** stop running collectors by hand. A scheduler runs every job at the right time of day, records each run, and writes a daily digest covering everything collected since the previous one. This completes Phase 1.

## What was added

| Piece | Why |
| --- | --- |
| `config/schedule.yaml` | When each job runs, as standard cron expressions in India time; editable, with `enabled: false` to pause a job |
| `agents/orchestrator.py` | The five jobs, a run wrapper that records every run, and the scheduler |
| `runs` table (migration 0008) | Job, start, finish, status (`ok` / `error`), summary and error, for monitoring |
| `agents/digest.py` | The daily digest in Markdown |
| `sna run <job|all>`, `sna runs`, `sna orchestrator show|start`, `sna digest` | Running, monitoring, previewing |
| `scheduler` service in `docker-compose.yml` | Runs the orchestrator in Docker (`make scheduler`), restarting with Docker |

## The schedule (India time)

| Job | When | Why then |
| --- | --- | --- |
| filings | every 30 min, 07:00–23:30 | Companies file through the day and late evening |
| news | hourly at :15, 06:15–23:15 | Feeds refresh through the day |
| prices | 19:30 and 21:30, Mon–Fri | NSE publishes the day's files around 18:00; the 21:30 run catches late files |
| securities | Sunday 09:00 | New listings, symbol changes, market caps |
| digest | 08:00 daily | Read before the market opens at 09:15 |

## How the orchestrator behaves

- **One job at a time**, in a single worker: no two jobs compete for the database or the exchange websites.
- **Every run is recorded**, including crashes. A failing job never stops the scheduler; `sna runs` and the digest's "Data collection" table show what failed.
- **Partial success counts as an error, with a summary**: e.g. filings stored from BSE while NSE returned 403.
- **Sleep:** nothing runs while the Mac sleeps. Missed runs are merged into one and still happen on wake if no more than 3 hours late.
- **No LLM.** The order of work is fixed; judgement comes in Phase 2.

## The digest

Saved under `data/digests/YYYY-MM-DD_HHMM.md` by the scheduled job; `sna digest` prints one without moving the window.

- **Market:** Nifty 50 and each watchlist stock's sector index, latest close and change.
- **Per company:** latest close vs Nifty 50 and sector (with z-score), unusual days, new filings (the BSE and NSE copies of the same announcement shown once, BSE first), news headlines with links (duplicate headlines shown once), and what recent order wins, results and concall filings did to the price after 1, 5 and 20 days.
- **Unusual moves to explain:** a list for the Move Explainer (Phase 2).
- **Data collection:** each job's last run and result.

## First live run (Mac, 21 Oct 2026)

`sna run all`: filings 10 s (2 new, PDFs downloaded), news 14 s (487 read, 89 about the watchlist, 4 new), prices 4 s (117 labels updated), digest under a second; all four recorded in `sna runs`. The Docker scheduler built (about 7 minutes the first time, mostly installing packages) and started, waiting for filings at 21:00, news at 21:15 and prices at 21:30.

Follow-up from that run: `sna news fetch` now prints one line per feed, e.g. `et_stocks: 50 read, 3 about your stocks, 2 new`, like the filings and price commands.

Notes:
- `sna digest` right after a scheduled digest covers only the minutes since; `sna digest --hours 24` shows a full day.
- Run one orchestrator only: if the Docker scheduler runs, don't also start `sna orchestrator start` in a terminal, or each job runs twice.

## A bug the tests caught

APScheduler numbers weekdays from 0 = Monday; standard cron (used in `schedule.yaml`) from 0 = Sunday. Read directly, "Mon–Fri" (`1-5`) would have meant Tue–Sat: prices would have skipped every Monday and run on Saturdays when there is no data. Weekday numbers are now converted to names before APScheduler sees them, with tests for weekday ranges, Sunday as 0 and 7, and lists.

## How to check it

```bash
git pull
make migrate
uv run sna orchestrator show
make run-all
uv run sna runs
make digest
make scheduler
make scheduler-logs
```

`make run-all` runs each job once in order (filings, news, prices, digest). `make scheduler` starts the Docker orchestrator; `make scheduler-logs` shows it waiting for the next run (Ctrl+C leaves it running).

## Tweet draft

> Agent #0: the Orchestrator. Filings every 30 min, news hourly, prices at 19:30 after NSE publishes, and an 8am digest of everything new: filings, headlines, unusual moves, and what each order win did to the stock. Phase 1 done. Fun bug: in APScheduler, Monday is 0; in cron, Sunday is. #BuildInPublic
