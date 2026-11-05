## What it is

Stock News Analyzer follows a list of Indian stocks for you. Every morning it reads what each company filed with NSE and BSE, the news about it, its share price, results and earnings calls. It then tells you what changed and why it might matter.

- **What it does:** explains unusual price moves, keeps track of order wins and of what managements promised, reads results and shareholding, and raises red flags.
- **What it is not:** a trading tool. It doesn't look at charts and doesn't say what to buy or sell. Everything it shows is information to check, not advice.
- **Where it runs:** on your own computer. Your list of stocks, your data and your API key stay there. The data comes from the public NSE, BSE and news websites, fetched by your computer for your personal use.
- **Licence:** MIT; the code is free to use and change.

## Getting started

Start the system with **start.command** (Mac) or **start.bat** (Windows) in its folder. It opens Docker Desktop if needed, waits for the database, and opens the dashboard at http://localhost:8501. A new copy opens on a short **setup**: the API key and budget, your stocks, and their history. It does the steps below for you; run it again any time from **Settings**. To do them by hand instead:

1. **Add your stocks** on **Manage stocks**. Search by name or NSE symbol, choose **Stocks I own** or **Watchlist**, and add a few news aliases (such as "L&T" for Larsen & Toubro).
2. **Load history** for each new stock on the same page. It fetches filings, news and prices since October 2023, so the system can compare today with the past. It takes a few minutes per stock.
3. **The scheduler** does the work every morning without you. The start script starts it; to run a job straight away, use **Run a job now** on **System**.
4. **Add an Anthropic API key** on **Settings** if you want the AI features (see "How AI is used"), and set a monthly budget. Without a key, collecting, prices, shareholding and the dashboard still work.

## A daily routine

| When | What to look at |
| --- | --- |
| Each morning after 08:00 | **Today**: the cards show each stock's move against the Nifty and its sector, and the digest lists what was filed and reported overnight. Then **Red flags**: look into new ones and dismiss those dealt with |
| When a stock had an unusual day | Its **Stock** page, **Unusual days** tab: the likely cause, how sure the system is, and the filings or news it is based on |
| When results come out | **Stock** page: the **Results** tab for revenue, profit and margins, then **Earnings calls** for what management said and promised |
| Weekly | **Themes** for what is rising across your companies; the **Shareholding** tab of the stocks you own |
| When you have a question | **Ask**, in plain English: "Which of my companies raised guidance this year?" |

## The pages

The sidebar groups the pages: **Today** (what changed, and the agent map), **Research** (one stock, questions, themes), **Library** (every filing and article), **Set up** (stocks, settings, system) and **Help**.

- **Today:** index levels, a card for each stock (Stocks I own first), the latest digest, recent red flags, and whether the morning jobs ran.
- **Portfolio:** each stock you own with a lean and the evidence behind it, and your sectors against the Nifty 50; explained in its own section below.
- **Red flags:** every flag, filtered by severity, period and stock. Select one to dismiss it with a note once you have looked into it, or to open a dismissed one again.
- **Stock:** one company in depth.
  - The chart compares the stock with its sector index and the Nifty 50, both set to 100 at the start, with key filings marked.
  - Tabs: Unusual days, Results, Shareholding, Events (with red flags), Earnings calls, Order book, Filings, News, Bulk/block deals, How it reacted, Corporate actions.
- **Research brief:** one stock on one page, conclusion first; explained in its own section below.
- **Week by week:** one stock's last 12, 24 or 52 weeks, explained in its own section below.
- **Filings:** every exchange filing, searchable by stock, type, words and date. Select one to read its text.
- **News:** headlines about your stocks, with the AI's relevance and importance, and links to the articles.
- **Themes:** themes across your companies (data centres, defence, credit and so on), whether they are getting stronger, and **read-across**: an important order or event at one company that may matter to another.
- **Ask:** questions in plain English, answered from your own data with the sources listed. Earlier questions are kept.
- **What moves the stock:** how stocks moved on average, 1, 5 and 20 trading days after each kind of filing.
- **What news does to prices:** the evidence across every stock followed, explained in its own section below.
- **Manage stocks:** add, edit and remove stocks; load a new stock's history. **Study only** marks a stock followed for the evidence, like the Nifty 50 added with `sna watchlist nifty50`: its filings, news, prices and results are collected and read by the cheap AI, but its earnings calls and unusual days are not, and on **Today** it is a row in one table instead of a card. Untick it to follow a stock fully; a stock you own always is.
- **Settings:** the API key, the monthly AI budget and models, the unusual-day threshold, and which scheduled jobs run.
- **System:** run any job now and watch it work; the schedule, how much is stored, recent runs and errors, and the AI spend this month by task.
- **Agent map:** how an agentic system works, shown on this one: the collectors perceive, the scheduler plans, the AI agents think, the database remembers, tools act, and guardrails and the run log watch over it, each with a line on what that part does in any agentic system.
  - **Today, live:** each box shows whether its job is running, worked or failed, its next run, and its AI calls and cost today; a faint line traces the path of each job running now; a feed explains each of today's runs in plain words.
  - **Replay the last 7 days:** press Play to watch information move through the system, today's or the week's, at 10 minutes, an hour or six hours a second; drag the slider to jump to a time. Each run lights up its box, a thin line traces the information from source to memory or from memory through Claude and back, and the feed narrates it.
- **Guide:** this page.

## Research brief

One stock on one page, laid out like a research note: the conclusion first, then a fold for each part of the research, opened only when you need it.

- **The lede:** the stock and the date, a one-line headline (valuation against its own history, the balance sheet), a line on the latest quarter, short stances (valuation, balance sheet, last quarter, what's next, red flags) and a ruled row of key numbers: trailing P/E, EPS growth, debt to equity and the next date. A note says what the brief is built from.
- **Evidence badges** on every figure: **Filed** (as filed, from an XBRL file or the exchange), **Read by AI** (read from a filing by an agent, QA passed), **Market** (prices and NSE's index files), **Stale** (older than a half year) and **Not disclosed** (the filings don't carry it).
- **The folds:**
  1. **Valuation:** the trailing P/E week by week against the middle 80% of its own last three years (shaded) and its median, the sector index's and the Nifty 50's P/E, the close, trailing EPS (the four quarters it adds up, adjusted for bonus issues and splits) and the market cap.
  2. **Results:** the last eight quarters, revenue and profit with their growth on the year, margin and EPS.
  3. **Balance sheet and cash flow:** equity, borrowings, cash, net debt, debt to equity, cash from operations, capex, free cash flow, and cash from operations against profit, from the half-yearly and annual XBRL files, with the tag each came from.
  4. **Peers:** a card for the stock and each peer (approved on Manage stocks, else the largest in its industry): P/E, one-year price change, latest revenue growth, market cap.
  5. **What's coming:** board meetings announced, results due (45 days after a quarter, 60 after the year), ex-dates, and management's promises falling due.
  6. **Red flags** still open.

**The view:** press **Write the view** (it needs an API key) and the analysis model writes, from the facts on the page only, a one-line verdict, a short summary, three stances (Favor, Watch, Avoid, Check), what the facts show and what they mean (**Observed → Read**, each citing the facts it rests on: hover a citation such as F12 to read it), why the stock and each peer matter and their key risk, and decision cards (Review now, Watch, Hold steady, Check) with the decisions to make now. Every number it writes is checked against the facts; anything with a number that isn't among them is dropped and listed under **Sources**, which shows all the facts the model was given. One view costs a few cents; each is kept, and earlier ones can be picked from **View**. It is an input for your decisions, not advice.

**Keeping it current:** for the stocks you own, the scheduler writes a new view at 07:57 when there are new results, a new balance sheet, a red flag or a major event since the last one, and the 08:00 digest lists it. A new view is told what changed since the previous one and says so under the headline (**What changed**); the **What changed** fold compares it with the previous view, fact by fact. When filed facts have changed since the view you are reading was written, a note says so. **Ask about** buttons under the peers open **Ask** with a question about that company filled in.

With a view, the brief gains the folds **The view**, **What to watch and decide** and **Sources**; it always has **Order book**, **Management** (promises kept and missed, management changes), **Ownership** (five quarters of shareholding) and **What moves this stock** (its lean and last 12 weeks).

Trailing P/E is the close over the last four quarters' EPS as they were known on each day; it is left out while EPS is not positive. Balance sheets come with the **xbrl** job; `uv run sna results balance SYMBOL` lists what was read and from which tags.

## Portfolio

Inputs for shaping the portfolio, not advice: no buy or sell calls.

- **The lean:** each stock you own leans positive, neutral or negative from its events of the last 90 days (results, order wins, events, red flags, deals). Each event counts for the median move against the Nifty 50 that followed events of its kind across every stock followed, over 20 trading days, from **What news does to prices**. A kind with fewer than 10 cases counts in proportion, and an event's weight halves every 45 days. The weighted medians add up to the score: above +1% leans positive, below −1% negative. An open high-severity red flag keeps a lean from being positive.
- **The reasons:** each event with what such events usually did, how many cases that rests on and how often the stock rose, its weight, and **since then**: how far the stock has already moved against the Nifty 50 after it. A move as big as such events usually bring may already be priced in.
- **The last 12 weeks** from **Week by week**: the stock's move against the Nifty 50, and how often its moves went the way its news pointed.
- **Your sectors against the Nifty 50:** your weight in each NSE industry (from the quantities on Manage stocks, or equal weights without them) beside the index's, by market cap, once `uv run sna watchlist nifty50` has saved its members. Over- and underweights show where the portfolio differs from the market.

The lean is only as good as the evidence. With few cases it stays near neutral; it firms up as the Nifty 50's history is read and new events come in.

## Week by week

One stock, week by week, to see whether it behaves the way its news says it should. Choose the stock and 12, 24 or 52 weeks.

- **The chart:** each week's move against the Nifty 50, coloured by what the news said: in line with the news, against it, moved without news, or quiet. Hover a bar for the week's main items.
- **The weeks, newest first:** each week's move against the Nifty 50 and the sector, its unusual days with their likely cause, then everything that came out: results, order wins, events, red flags and deals, the news (most important first, linked) and the filings. A green or red dot marks what pointed up or down.
- **The verdict:** the week's news tone adds up positive and negative news and events of importance 3 or more, good or weak results, order wins and red flags. A week that moved more than the stock's usual week is *in line with the news* when it went the way the tone pointed, *against the news* when it went the other way, and *moved without news* when nothing pointed either way. Smaller moves are *quiet*.
- Mostly in line: the stock trades on its news. Often against or without news: something else drives it (the market, the sector, flows), or the news was expected. News published after Friday's close counts in the next week.

## What news does to prices

Rules of thumb, such as "a big order win lifts the stock" or "good results with a profit fall sink it", tested against what happened. Every event stored is a case: results (revenue and profit growth on the year, dated by the results filing), order wins (sized against the company's revenue over the last four quarters), events of importance 3 or more that passed the QA check, red flags, and bulk and block deals. For each kind:

- **Median move:** half the cases did better than this against the Nifty 50 (or the sector index), half worse, over 1, 5 or 20 trading days from the first close that could reflect the news.
- **Middle half:** a band from the 25th to the 75th percentile, a tick at the median and a line at zero. A band clear of the line is a consistent pattern.
- **Rose:** how often the stock beat the benchmark; about 50% is a coin toss.
- **Few cases:** under 10, a hint rather than evidence.

Pick a kind to see the cases behind it.

**Group the cases by Size of move** turns it round: every case is put in a band by how far the stock moved (from "−5% or worse" through "0% to +0.5%" to "+5% or better"), and each band lists the kinds of event behind its moves, with how many of each kind's cases fell there ("2 of 15"), and the stocks, yours in bold. A kind bunched at one end is a pattern; one spread evenly says little. Pick a band to see its cases. More stocks make the evidence firmer: `uv run sna watchlist nifty50` adds the Nifty 50 as study-only stocks. The cases overlap and the market moves for many reasons, so this shows what usually followed, not what caused it, and big news is often priced in before the close. It is an input for your decisions, not advice.

## Settings

| Setting | What it does |
| --- | --- |
| API key | Turns the AI features on. It is checked with Anthropic before it is saved, which costs nothing |
| Monthly budget | AI calls stop for the rest of the month once this much is spent; 0 turns them off. The bar shows this month's spend |
| Models | Haiku for sorting and extracting, Sonnet for explaining and analysing. Opus is stronger and costs about twice Sonnet |
| Unusual days | How big a move against the Nifty 50 counts as unusual: 2.0 marks about 1 trading day in 20, 2.5 about 1 in 80 |
| Scheduled jobs | Turn a job off to stop it running on its schedule, for example the AI jobs while you are away |

A setting saved here takes the place of the same one in the `.env` file; "Where each setting comes from" shows which is in use. The scheduler picks up a change within a minute, with no restart.

## Words used

| Word | Meaning |
| --- | --- |
| Unusual day | A day when the stock moved more than usual against the Nifty 50: by 2 standard deviations of its last 60 days or more, about 1 trading day in 20 |
| Likely cause | The filing or news the AI judges most likely to explain an unusual day, with its confidence. "No clear cause" is a fair answer |
| Promoter | The founders or parent company that control the company; they must disclose every sale and pledge |
| Pledge | Shares a promoter has given as security for a loan. If the loan goes bad, the lender can sell them |
| FII, DII | Foreign and domestic institutional investors. Mutual funds and insurers are part of DII |
| Retail | Individuals holding shares worth up to Rs 2 lakh |
| Dilution | A stake that falls because the company issued new shares, not because anyone sold |
| Order book | Work a company has won but not yet delivered. **Book-to-bill** is the order book divided by a year's revenue |
| Guidance | What management says to expect: growth, margins, a plant starting |
| Promise | A specific, checkable statement from an earnings call ("Plant 2 by March 2027"), later marked kept, late, partly kept or missed |
| Read-across | News at one company that may matter to another: a peer, or one in the same theme |
| Red flag | A warning about governance or money: an auditor or CFO leaving, a rating cut, a pledge, promoters selling, a penalty, results filed late |
| Rs crore | Rs 1 crore is Rs 10 million. Amounts in the app are in crore unless marked |

## How AI is used

Some of the work uses Anthropic's Claude models through your own API key, which you pay for. A cheaper model (Haiku) sorts and extracts; a stronger one (Sonnet) explains and analyses.

| Feature | Model | Without a key |
| --- | --- | --- |
| News triage: relevance, topic, importance | Haiku | All articles listed, unsorted |
| Unusual-day explanations | Sonnet | Unusual days listed without a cause |
| Earnings call summaries, promises, promise checks | Sonnet | Not available |
| Orders from filings, quarterly order books | Haiku, Sonnet | Not available |
| Results read from PDFs | Haiku | Results from XBRL files still read |
| Events from filings, and their check | Haiku, Sonnet | Not available; their red flags too |
| Gold and silver notes on unusual days | Sonnet | The price split still shown |
| Themes | Haiku | Not available |
| Ask | Sonnet | Not available |

These work without any AI: collecting filings and news, prices and unusual days, bulk and block deals, results from XBRL files, shareholding patterns, overdue-results and shareholding red flags, the digest and this dashboard.

**Cost:** a monthly budget, set on **Settings** ($20 by default), stops all AI calls when reached. Reading a new stock's history costs the most, once. After that a 15-stock watchlist costs a few dollars a month, and an Ask question a few cents. **System** shows this month's spend by task.

## Where the data comes from

| Data | Source | When |
| --- | --- | --- |
| Filings and their PDFs | BSE and NSE announcement pages | Every 30 minutes, 07:00–23:00 |
| News | Business news RSS feeds and Google News searches | Every hour, 06:15–23:15 |
| Prices, index levels, corporate actions | NSE's daily files | Weekday evenings, 19:30 and 21:30 |
| Bulk and block deals | NSE | Weekday evenings |
| Results | NSE's XBRL files, else the results PDF | Each morning |
| Shareholding patterns | NSE's XBRL files | Each morning at 07:10 |
| Gold, silver, US dollar | NSE gold and silver ETFs; global prices from Yahoo Finance | Each morning |

All times are India time. Everything is fetched from public websites by your own computer, at a polite rate, for your personal use. History goes back to October 2023.

## Keeping it running

- **The morning jobs** run from 07:10 to 08:00 (new Research brief views for the stocks you own at 07:57) and the digest is ready at 08:00. Your computer must be on and Docker Desktop running then; the start script starts the scheduler.
- **If the computer was off,** nothing is lost: the next run picks up whatever was filed in between. Prices and deals also run at 07:05 and 07:06 the next morning, in case the computer was asleep in the evening.
- **To catch up,** press **Catch up** on **System** or the **Agent map**. It appears when a job missed its scheduled run (shown in amber on the map), and runs each missed job in order, each from where it last stopped.
- **To see what ran,** open **System**, or the job health on **Today**.
- **To stop a job,** turn it off on **Settings**; it stops running on its schedule within a minute.
- **To run a job now,** for example after adding a stock or when a morning run failed, use **Run a job now** on **System**. It shows the job's progress; keep the tab open until it finishes.
- **To update** to a newer version: replace the folder's files with the new download (keep the `data` folder) and run the start script again. Database changes are applied as it starts.
- **To stop it,** run **stop.command** or **stop.bat**. Your data is kept.

## Problems

| What you see | What to do |
| --- | --- |
| "Port 8501 is not available" | The dashboard is already running: open http://localhost:8501. If that fails, run the stop script, then the start script |
| "Docker didn't start" or "Postgres is not reachable" | Open Docker Desktop, wait until it says it is running, then run the start script again |
| NSE or BSE returned HTTP 401 or 403 | The exchange refused for a while. The job retries on its next run; wait an hour |
| "...has reached the $20.00 budget" | AI calls stop until the 1st. Raise the budget on **Settings** if you want more |
| A stock isn't found on Manage stocks | Try its NSE symbol, or part of its name. If it listed recently, run the **securities** job on **System** |
| A page says "No ... yet" | That data hasn't been collected: load history on Manage stocks, or wait for the morning run |
| A wrong number | Check it against the filing, linked from the row. Results, orders and events record the text they came from |

## Your data

- **Where it is:** the database lives in Docker, and filing PDFs and digests in the `data` folder of the project.
- **Back up the database:** `docker compose exec db pg_dump -U sna sna > backup.sql` saves it to one file.
- **Start over:** `docker compose down -v` in the folder deletes the database (the `data` folder stays). The start script then gives you an empty one, with the setup.
- **Your API key** is kept on your computer, in the database (saved on Settings) or the `.env` file. It is never sent anywhere except to Anthropic.
