# Step 7: Dashboard (Phase 1 output in the browser)

**Goal:** see what Phase 1 collects without reading terminal tables: the watchlist at a glance, each stock against its benchmarks with its filings on the chart, searchable filings and news, what each kind of filing has done to the price, and whether the scheduler is healthy.

## What was added

| Piece | Why |
| --- | --- |
| `ui/queries.py` | Read-only queries returning tables (pandas) and plain dicts, tested without a browser |
| `ui/charts.py` | The Plotly charts, with fixed colours for light and dark mode |
| `ui/app.py` | The Streamlit app: six pages |
| `sna ui` / `make ui` | Starts it at http://localhost:8501 |
| `ui` service in `docker-compose.yml` | Runs it in Docker next to the scheduler (`make ui-docker`) |
| `.streamlit/config.toml` | No usage statistics sent to Streamlit, local address only, toolbar trimmed |

The dashboard only reads the database. Collecting still happens in the scheduler or with `sna run ...`. Results are cached for a minute; **Refresh data** in the sidebar reloads them now.

## The pages

| Page | What it shows |
| --- | --- |
| Today | Nifty 50 and sector indices; a card per stock: close, day's move, vs Nifty 50 and sector, z-score, an **Unusual** badge, a 3-month sparkline, filings and news in the last 7 days; the latest digest; each job's last run |
| Stock | The stock, its sector index and the Nifty 50, indexed to 100 over 1M–3Y, with key filings (order wins, results, concall transcripts, presentations, ratings) as diamonds and unusual days circled; daily return minus the Nifty's as bars; tabs for its filings, news, how it reacted to each one, and corporate actions |
| Filings | Filter by stock, type, words in the title or PDF text, and date; BSE and NSE copies shown once; select a row to read the extracted text |
| News | Filter by stock, headline words and date; links to the articles |
| What moves the stock | Average return vs Nifty 50 1, 5 and 20 trading days after each kind of filing, per stock or all, with how many events each average rests on |
| System | The schedule with the next run of each job, what is stored, and recent runs (filter to errors) |

## Chart choices

- **One axis per chart.** Stock, sector and Nifty are indexed to 100 on the first day shown, so three price scales never share a chart and the gap between lines is the out- or under-performance.
- **Colour by role:** the stock is blue, its sector index orange, the Nifty 50 gray because it is the baseline. Up/down bars are blue/red rather than green/red so they read for colour-blind viewers too; the metric cards keep Streamlit's arrows and signs.
- **Returns are the adjusted ones** from step 5, so the MSUMI and KVB bonus issues don't show as crashes.
- **The event study uses one scale for all three panels**, so a 1-day bar and a 20-day bar can be compared by length. It warns that averages of a handful of events are mostly noise and shows the count on each row.

## How to check it

```bash
git pull
uv sync
make ui
```

The browser opens http://localhost:8501. Ctrl+C in the terminal stops it. To run it in Docker instead, next to the scheduler:

```bash
make ui-docker
make ui-stop
```

## Tweet draft

> Phase 1 now has a face. A local dashboard over everything the agents collect: each stock vs Nifty and its sector (indexed to 100, bonus issues adjusted), every order win and results filing pinned on the chart, unusual days circled, and a page that asks: what does an order win actually do to the stock after 1, 5, 20 days? #BuildInPublic
