# Making it usable by others

Version 1.4 · Oct 28, 2026 · @Ramki · companion to the [system design](design.md) and [agent design](agent-design.md); changes are listed in [README.md](README.md)

## Goal

Anyone who follows Indian stocks should be able to download the system, run it on their own computer, and use it from the browser without knowing Python, Git or the command line. It stays a personal tool, not a hosted service:
- each person runs their own copy
- it uses their own Anthropic key (or none)
- their data stays on their own machine

Three pieces of work get there:
1. A simple install.
2. A dashboard that does everything the command line does today.
3. A Guide screen inside the app that explains how to use it.

## Where it stands today

Setting it up now takes what only a developer has:

| Step today | Why it stops most people |
| --- | --- |
| Install Homebrew, uv, Docker Desktop and Git | Four tools, two of them command-line only |
| `git clone`, `make setup`, `make up`, `make health` | Terminal commands; `make` is missing on Windows |
| Edit `.env` to add the API key | A hidden file, edited by hand |
| Edit `config/watchlist.yaml`, or use Manage stocks | YAML is easy to break |
| `make backfill`, then `make scheduler` | Long jobs started from the terminal; nothing in the app says they're needed |
| Most actions (`sna flags dismiss`, `sna ask`, `sna holdings run`...) | The command line is the only way to run many of them |

Other things tie it to one person:
- `config/watchlist.yaml` in the repository is the author's own list, with `owned: true` on their holdings.
- There is no licence file, so others have no clear right to use or change the code.
- The README assumes a Mac.

## 1. Install

### Choice: one Docker package, set up from the browser

| Option | For | Against | Verdict |
| --- | --- | --- | --- |
| **Docker Compose, prebuilt image** | One download (Docker Desktop) on Mac, Windows and Linux; Postgres, the dashboard and the scheduler start together; already how the scheduler runs | Docker Desktop is a large install and must be running | **Chosen** |
| Python package (`uv tool install`) with SQLite | No Docker | The database code uses Postgres features throughout (full-text search, JSON, arrays); a rewrite of many queries, and users still need Python | No |
| Desktop app (PyInstaller, Briefcase) | Double-click install | Bundling Postgres and a browser UI is fragile; signing for Mac and Windows costs money and time | Not now |

### What the user does

1. Install Docker Desktop and open it once.
2. Download one small folder from the GitHub Releases page. It holds `docker-compose.yml` and start scripts, but no code.
3. Double-click `start` (`start.command` on Mac, `start.bat` on Windows) or run `docker compose up -d`.
4. Open http://localhost:8501. A first-run setup leads the rest of the way (see below).

Updating is the same `start` script: it pulls the newest image and applies database changes on start.

### Work needed

- **Prebuilt image:** a GitHub Actions job builds the image for Intel and Apple Silicon and pushes it to GitHub Container Registry on each release tag, so users never build it.
- **One compose file for users:** Postgres, the dashboard and the scheduler all start by default, using the image rather than `build: .`. The dashboard listens on localhost only. The developer compose file stays as it is.
- **Database changes on start:** the container runs `sna db upgrade` before starting, so there is no `make migrate` step.
- **Settings in the database, not `.env`:** the API key, budget, models and threshold are saved from the Settings page in a `settings` table. A saved value takes the place of `.env`, so the page works for someone who also has a `.env`; removing it goes back to `.env`. Built in step 24.
- **The scheduler reads the job switches from the database:** turning a job off in Settings takes effect within a minute, without editing `config/schedule.yaml` or restarting. Built in step 24.
- **Example watchlist:** `config/watchlist.example.yaml` with a few large companies. The personal `config/watchlist.yaml` stops being tracked in Git.
- **Licence:** MIT is the simplest, if the author agrees. A notice in the README and the Guide says:
  - the data comes from the public NSE, BSE and news websites, for personal use
  - each copy fetches it from the user's own connection, at a polite rate
  - nothing in the app is investment advice
- **Windows check:** the start script, file paths and the data folder volume, tested once on a Windows machine.

## 2. A better interface

The dashboard is the right base: Streamlit keeps it in Python, next to the agents, and is enough for one person on their own machine. A separate web front end (React, with an API) would look more polished but would double the code to maintain, so it stays out of scope. The work is to make the existing app complete and easy to follow.

### First-run setup

Shown until it is finished, in four steps:
1. **Welcome:** what the system does in four lines, and what it needs: a computer left on in the morning, and optionally an Anthropic key.
2. **AI features:**
   - **with a key:** paste it in, test it, and set a monthly budget (default $5, with a note on what that buys)
   - **without one:** skip it, and say which features stay off: triage, move explanations, call summaries, Q&A
3. **Your stocks:** search and add stocks, mark the ones you own; or start from the example list.
4. **History:** load the last year of filings, news, prices and shareholding. A progress bar shows each stock as it runs, and it is safe to close the tab. Then turn on the daily schedule.

### Navigation

Pages grouped in the sidebar, in plain words:

| Group | Pages |
| --- | --- |
| Today | Home (what changed since yesterday), Red flags |
| Research | Stock, Ask, Themes, What moves the stock |
| Library | Filings, News |
| Set up | My stocks, Settings, System |
| Help | Guide |

### Everything from the app

Every action people need, with a button, so the command line is only for developers:
- **Run now:** run any job from System, with its progress shown, such as "Read new filings" or "Explain today's moves".
- **Red flags page:** all open flags, a filter by stock and severity, and Dismiss with a note.
- **Shareholding:** already a Stock-page tab; add a "Who's buying" table across the watchlist.
- **Earnings calls:** read and re-read a call; see promises and their status.
- **AI spend:** this month's cost by agent, against the budget, on Settings.
- **Digest archive:** read any day's digest; download it as a file.

### Look and feel

- One colour scheme for charts and status, readable in light and dark.
- Numbers in Indian format: Rs 1,23,456 crore, lakh shares.
- Every page opens with a one-line "what this shows" and an empty state that says what to do: "No results yet: load history from My stocks."
- AI-made text is marked as such, with its sources, so it is never confused with a filing.
- Wide tables become cards on a narrow window.

## 3. The Guide screen

A Guide page in the app. Its text is one file, `src/stock_news_analyzer/ui/guide.md`, readable on GitHub before installing and linked from the README. It lives with the code because the Docker image copies only `src/`. Built in step 23.

| Section | Content |
| --- | --- |
| What it is | Tracks filings, news, results and earnings calls for your stocks; explains moves; flags risks. Not a trading tool, and not advice |
| A daily routine | 08:00 digest: read Home, then Red flags, then any stock with an unusual day. Weekly: Themes and Shareholding. Quarterly: results and earnings calls |
| Page by page | One short paragraph and a screenshot per page |
| Words used | Unusual day (z-score), promoter, pledge, FII and DII, order book, book-to-bill, read-across, guidance |
| How the AI is used | Which agents use Claude, the models, the cost per month for a 15-stock watchlist, and what each does with no key |
| Where the data comes from | NSE, BSE, RSS and Google News; when each is fetched; how far back |
| Keeping it running | The computer must be on, with Docker Desktop running, at 07:10–08:00 for the morning jobs; what happens if it was off (the next run catches up) |
| Problems | "Port in use", "Docker not running", an NSE block (wait and retry), the budget reached, a stock not found |
| Your data | Where it is stored, how to back it up (one command or button), how to start over |

The Guide is reached from the sidebar and from a "How to use this page" link on each page, which opens that page's section in the same tab (`/guide?section=...`).

## Order of work

Each step is one PR, tested on the Mac like the agents:

| Step | What | Size |
| --- | --- | --- |
| 23 | Guide page and its text file; one-line help and a help link on every page (done) | Small |
| 24 | Settings page and `settings` table; API key, budget and job switches from the app (done) | Medium |
| 25 | Navigation regrouped; Red flags page; Run now buttons with progress (done) | Medium |
| 26 | First-run setup (done) | Medium |
| 27 | Packaging: prebuilt image, user compose file, start scripts, migrations on start, example watchlist, licence | Medium |
| 28 | Try it on a clean Mac and a Windows machine; fix what breaks; write the release notes | Small |

The Guide comes first because it is quick and shows where the app is hard to follow, which shapes steps 24 to 26.

## Decisions for the author

- **Licence:** MIT, or keep it private and share it with people you choose.
- **Repository:** public, to download from GitHub Releases. The personal watchlist and `.env` must not be in its history: the watchlist is tracked today.
- **Default budget for new users:** $5 a month is suggested; $20 is the author's own.
- **Email:** sending the digest by email needs each user's own mail account. It could come after packaging, as an option in Settings.
