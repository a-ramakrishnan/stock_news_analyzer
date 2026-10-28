## What it is

Stock News Analyzer follows a list of Indian stocks for you. Every morning it reads what each company filed with NSE and BSE, the news about it, its share price, results and earnings calls. It then tells you what changed and why it might matter.

- **What it does:** explains unusual price moves, keeps track of order wins and of what managements promised, reads results and shareholding, and raises red flags.
- **What it is not:** a trading tool. It doesn't look at charts and doesn't say what to buy or sell. Everything it shows is information to check, not advice.
- **Where it runs:** on your own computer. Your list of stocks, your data and your API key stay there.

## Getting started

1. **Add your stocks** on **Manage stocks**. Search by name or NSE symbol, choose **Stocks I own** or **Watchlist**, and add a few news aliases (such as "L&T" for Larsen & Toubro).
2. **Load history** for each new stock on the same page. It fetches filings, news and prices since October 2023, so the system can compare today with the past. It takes a few minutes per stock.
3. **Start the scheduler** so the work happens every morning without you: `make scheduler` in the project folder.
4. **Add an Anthropic API key** on **Settings** if you want the AI features (see "How AI is used"), and set a monthly budget. Without a key, collecting, prices, shareholding and the dashboard still work.

## A daily routine

| When | What to look at |
| --- | --- |
| Each morning after 08:00 | **Today**: the cards show each stock's move against the Nifty and its sector, and the digest lists what was filed and reported overnight. Then the red flags at the top of the digest |
| When a stock had an unusual day | Its **Stock** page, **Unusual days** tab: the likely cause, how sure the system is, and the filings or news it is based on |
| When results come out | **Stock** page: the **Results** tab for revenue, profit and margins, then **Earnings calls** for what management said and promised |
| Weekly | **Themes** for what is rising across your companies; the **Shareholding** tab of the stocks you own |
| When you have a question | **Ask**, in plain English: "Which of my companies raised guidance this year?" |

## The pages

- **Today:** index levels, a card for each stock (Stocks I own first), the latest digest, recent red flags, and whether the morning jobs ran.
- **Stock:** one company in depth.
  - The chart compares the stock with its sector index and the Nifty 50, both set to 100 at the start, with key filings marked.
  - Tabs: Unusual days, Results, Shareholding, Events (with red flags), Earnings calls, Order book, Filings, News, Bulk/block deals, How it reacted, Corporate actions.
- **Filings:** every exchange filing, searchable by stock, type, words and date. Select one to read its text.
- **News:** headlines about your stocks, with the AI's relevance and importance, and links to the articles.
- **Themes:** themes across your companies (data centres, defence, credit and so on), whether they are getting stronger, and **read-across**: an important order or event at one company that may matter to another.
- **Ask:** questions in plain English, answered from your own data with the sources listed. Earlier questions are kept.
- **What moves the stock:** how stocks moved on average, 1, 5 and 20 trading days after each kind of filing.
- **Manage stocks:** add, edit and remove stocks; load a new stock's history.
- **Settings:** the API key, the monthly AI budget and models, the unusual-day threshold, and which scheduled jobs run.
- **System:** the schedule, how much is stored, recent runs and errors, and the AI spend this month by task.
- **Guide:** this page.

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

- **The morning jobs** run from 07:10 to 08:00 and the digest is ready at 08:00. Your computer must be on and Docker Desktop running then, with the scheduler started (`make scheduler`).
- **If the computer was off,** nothing is lost: the next run picks up whatever was filed in between.
- **To see what ran,** open **System**, or the job health on **Today**.
- **To stop a job,** turn it off on **Settings**; it stops running on its schedule within a minute.
- **To update** to a newer version: `git pull`, then `uv run sna db upgrade`, then restart the scheduler and dashboard.

## Problems

| What you see | What to do |
| --- | --- |
| "Port 8501 is not available" | The dashboard is already running somewhere: `make ui-stop`, or close the other Terminal window running it |
| "Postgres is not reachable" | Open Docker Desktop, wait for it to start, then `make up` |
| NSE or BSE returned HTTP 401 or 403 | The exchange refused for a while. The job retries on its next run; wait an hour |
| "...has reached the $20.00 budget" | AI calls stop until the 1st. Raise the budget on **Settings** if you want more |
| A stock isn't found on Manage stocks | Try its NSE symbol, or part of its name. Run `uv run sna securities refresh` if it listed recently |
| A page says "No ... yet" | That data hasn't been collected: load history on Manage stocks, or wait for the morning run |
| A wrong number | Check it against the filing, linked from the row. Results, orders and events record the text they came from |

## Your data

- **Where it is:** the database lives in Docker, and filing PDFs and digests in the `data` folder of the project.
- **Back up the database:** `docker compose exec db pg_dump -U sna sna > backup.sql` saves it to one file.
- **Start over:** `docker compose down -v` deletes the database (the `data` folder stays). Then `make up` and `make migrate` give you an empty one.
- **Your API key** is kept on your computer, in the database (saved on Settings) or the `.env` file. It is never sent anywhere except to Anthropic.
