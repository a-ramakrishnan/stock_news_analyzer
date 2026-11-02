# Feeding the design brief to Lovable, step by step

The [design brief](ui-brief.md) split into prompts to paste into Lovable one at a time, in this order. Copy the text inside each box exactly. After each prompt, wait until Lovable has finished building and look at the preview before sending the next one.

## Step 0: start the project and set its rules

1. On lovable.dev, start a **new project**. Don't connect Supabase or GitHub if it offers.
2. Open the project's settings and look for **Knowledge** (project instructions). Paste this in and save it. If you can't find Knowledge, paste it at the start of prompt 1 instead.

```
This project is a set of clickable DESIGN MOCK-UPS for "Stock News Analyzer", a dashboard that follows a list of Indian stocks for one person. Every morning it reads what each company filed with the stock exchanges (NSE and BSE), the news about it, its share price, quarterly results, shareholding and earnings calls, and shows what changed and why it might matter. It runs on the user's own computer.

Rules for everything in this project:
- Front end only, with hard-coded sample data. No Supabase, no database, no login, no API calls, no payments. Never add them, even if it seems useful.
- Sample data uses made-up companies only: Aravalli Infra (ARAVINFRA), Konkan Bank (KONKANBNK), Deccan Cables (DECCANCAB), Sahyadri Foods (SAHYFOODS), Narmada Marine (NARMADAMAR), Vindhya Pharma (VINDHYAPH). ARAVINFRA, KONKANBNK and DECCANCAB are "Stocks I own"; the rest are "Watchlist". Never use real company names.
- The readers are individual investors, not traders. It shows information to check, never buy or sell advice. No candlestick charts, no technical indicators.
- Formats: rupees as ₹1,234.50; large amounts in crore with Indian grouping (Rs 1,23,456 cr); dates as 21 Oct 2026; times in India time (IST); percentages with a sign (+1.24%, −0.37%).
- Colours: green for up and red for down; red / amber / grey for high / medium / low red flags, the same everywhere. Light and dark themes, with a switch.
- AI-written text (explanations, summaries, answers) carries a small "AI" mark and lists its sources, so it is never mistaken for a filing.
- Desktop first; at a narrow width, wide tables become stacked cards.
- Simple building blocks only, because these designs will be rebuilt in Streamlit (Python): a sidebar, cards, number tiles with a change underneath, tables, tabs, line and bar charts, expandable sections, badges, simple forms. No drag-and-drop, no custom hover interactions, no modals on top of modals, no animation.
- Every page opens with a one-line "what this shows", has a small "How to use this page" link to the Guide, and has an empty state that says what to do (for example "No results yet: load history on Manage stocks").
```

## Prompt 1: the frame and the Today page

```
Build the app frame and the Today page.

Sidebar on the left, with the app name at the top and the pages in groups:
- Today: Today, Red flags
- Research: Stock, Ask, Themes, What moves the stock
- Library: Filings, News
- Set up: Manage stocks, Settings, System
- Help: Guide
Every page exists, with a title and "coming soon" for now; only Today is designed in full. Add a light/dark theme switch.

Today is the first page each morning: what changed since yesterday. From top to bottom:
- Header: "Today", and under it "Last trading day loaded: Wed 21 Oct 2026".
- Index tiles in a row: Nifty 50, Nifty Bank, Nifty Infrastructure, Nifty Auto, Nifty IT, Nifty FMCG. Each shows its level (22,811.35) and the day's change (▼ −0.34% in red, or ▲ +0.52% in green).
- "Red flags, last 30 days": 3 to 5 one-line items such as "21 Oct · auditor resigned · DECCANCAB: Statutory auditor resigns citing lack of information". High in red, medium in amber. A link: "All red flags".
- Stock cards in two groups, "Stocks I own (3)" and "Watchlist (3)", three cards to a row. Each card shows: the symbol in bold and the company name; the close (₹1,234.50) and the day's change (+1.24%) with a small 3-month sparkline; "vs Nifty 50 +0.87% · vs Nifty Bank +0.40% · z 2.4"; for one or two cards an "Unusual" red badge with "Likely cause: order win" under it; "Last 7 days: 4 filings, 12 news articles"; and an "Open" link to the Stock page.
- Bullion: tabs Gold and Silver. Each a 30-day table: day, ETF close (₹), move in rupees, then that move split into global price, USD/INR and other, z-score, driver, and a short note on unusual days.
- Two columns at the bottom: on the left "Latest digest", a collapsed section that opens to a long morning report with headings per company; on the right "Data collection", a small table of jobs (filings, news, prices, results, events, explain, digest) with the last run time and "✅ ok" or "⚠️ error".
```

## Prompt 2: the Stock page, top half

```
Design the Stock page (one company in depth). Use ARAVINFRA (Aravalli Infra) as the example.

- Top bar: a stock picker (all six companies) and a range switch: 1M, 3M, 6M, 1Y, 3Y (1Y selected).
- Heading: "Aravalli Infra", and under it "NSE ARAVINFRA · benchmark Nifty 50 and Nifty Infrastructure · owned".
- Four number tiles: "ARAVINFRA over 1Y +18.2%", "Nifty 50 over 1Y +6.1%", "Nifty Infrastructure over 1Y +9.4%", "Unusual days 7".
- Main chart: three lines (the stock, Nifty Infrastructure, Nifty 50), each starting at 100 a year ago. Diamond markers on the stock line for key filings (results, order wins, ratings) and circles for unusual days.
- Second chart, smaller: "Daily return minus the Nifty 50's", one bar per day; unusual days solid, the rest faint.
- A caption: "Adjusted for bonus issues, splits and dividends."
- Below, tabs: Unusual days, Results, Shareholding, Events, Earnings calls, Order book, Filings, News, Bulk/block deals, How it reacted, Corporate actions. Design the first four now; the others say "coming next".

Tab "Unusual days": a table of 6 days with: day, stock move, move vs Nifty 50, z, likely cause (order win, results, news, sector move, no clear cause), confidence (high/medium/low), explanation (AI-marked, 2–3 sentences), and "Based on" (one or two filing or news titles).

Tab "Results": three tiles for the latest quarter (Q2 FY27): Revenue Rs 1,240 cr (+18% y/y), Profit after tax Rs 96 cr (+22% y/y), EBITDA margin 14.2%. A chart of 8 quarters: revenue as bars, profit as a line. A table, newest first: period, revenue, revenue y/y, EBITDA, EBITDA margin, profit after tax, profit y/y, net margin, EPS (Rs), and a "checked" tick.

Tab "Shareholding": four tiles for Sep 2026: Promoters 54.21% (−0.40 pts), Foreign inst. 18.30% (+0.90 pts), Domestic inst. 14.75% (+0.20 pts), Retail 9.10% (−0.60 pts). A line chart of those four over 12 quarters. A table, newest first, with those plus mutual funds, insurers, pledged % (of the promoters' shares) and the number of shareholders.

Tab "Events": first "Red flags, last 12 months" (two items, one red, one amber). Then a table of 8 events read from filings: filed date, type (capex, rating, management change, legal, deal, fundraise, promoter action, disruption), importance 1–5 shown as a small bar, sentiment, headline, amount (for example "Rs 450 cr · 9% of revenue"), QA result (passed / repeat / unchecked), a short quote from the filing, and an "open" link.
```

## Prompt 3: the Stock page, the other tabs

```
Now design the remaining tabs of the Stock page, with the same company and style.

Tab "Earnings calls":
- A call picker: "Q2 FY27 · filed 15 Oct 2026 · positive" (and two earlier calls).
- The tone with a coloured dot, and an AI-marked summary paragraph.
- Two columns: "To watch" (3 bullets) and "Since the previous call" (3 bullets, each starting with a kind: raised, cut, new, dropped).
- "What management said": a table of topic (guidance, demand, margins, capex, order book, risks), point, good or bad for shareholders, and a short quote.
- "What analysts pressed on": topic, question, answer.
- "Transcript text": a collapsed section.
- "Promise ledger": a tile "Promises kept 67%" with "Of 9 settled: 5 kept, 1 kept late, 1 partly, 2 missed. 4 still to come."; then a table of promises: promise, target, due (as said), status (open, kept, late, partly, missed, dropped), due by, overdue tick, latest update, said in, and the quote.

Tab "Order book":
- Four tiles: Order book Rs 12,400 cr; Years of revenue 2.8; Book-to-bill 1.3x; Execution 36%.
- A chart by quarter: orders announced and inflow reported as bars side by side, the order book as a line.
- A table by quarter: announced (Rs cr), number of orders, reported inflow, order book, revenue, book-to-bill.
- "Orders announced (14)", collapsed: date, Rs crore, client type (government, PSU, private, export), months, what for.
- "Compared with your other order-driven stocks": a small table of 3 stocks with book-to-bill, years, execution and order growth.

Tab "Filings": a table of published (IST), exchange (BSE/NSE), type, title and a "PDF" link. Clicking a row shows the filing's text in a box underneath.

Tab "News": published, importance (★ 1–5), topic, good or bad for shareholders, headline, an AI one-line summary, and a "read" link.

Tab "Bulk/block deals": day, bulk or block, buy or sell, shares, price (₹), % of the day's volume, client.

Tab "How it reacted": each filing or article with its date and title, and the stock's return vs the Nifty 50 1, 5 and 20 trading days later (blank when too recent).

Tab "Corporate actions": ex-date, kind (bonus, split, dividend), price factor, dividend (₹).
```

## Prompt 4: Red flags and Ask

```
Design the Red flags page and the Ask page.

Red flags: warnings about governance and money (an auditor or CFO leaving, a rating cut, pledged shares, promoters selling, a penalty, results filed late).
- Filters in a row: severity (high, medium, low; high and medium selected), "Raised in the last" (30 days, 90 days, 1 year, 3 years; 1 year selected), stocks (all by default), and a "Show dismissed" switch.
- A table of about 10 flags: raised (date), severity (coloured), stock, kind, what happened, status (open or dismissed), your note, and a "filing" link.
- Selecting a flag shows it underneath with a note box ("e.g. a planned retirement; successor named") and a "Dismiss" button; for a dismissed flag, an "Open it again" button instead.

Ask: questions in plain English, answered from the user's own data.
- A text box with the placeholder "Which of my companies raised guidance this year?", an optional "Save as report" name, and an "Ask" button.
- While it works: a progress box with lines such as "Looking up events...", "Searching call points for 'guidance'...".
- The answer (AI-marked): a short paragraph and a table of companies with what they raised and when, then numbered sources under it, such as "[3] ARAVINFRA Q2 FY27 call (15 Oct 2026), guidance: revenue growth raised to 20–22%". Small text: "4 lookups, $0.07".
- "Earlier questions": a list of 5 earlier questions with date and time, each opening to its answer.
```

## Prompt 5: Themes, What moves the stock, Filings and News

```
Design four pages: Themes, What moves the stock, Filings and News.

Themes: themes across the user's companies.
- A table: theme (data centres, defence, credit growth, exports, rural demand, power transmission), items in the last 90 days, items in the 90 days before, positive, negative, orders (Rs crore), and the companies involved. A small arrow shows whether each theme is rising.
- A theme picker, then for the chosen theme a monthly bar chart and a list of items (date, item, Rs crore).
- "Read-across": news at one company that may matter to another: date, the item, and the companies it may affect.

What moves the stock: how stocks moved on average 1, 5 and 20 trading days after each kind of filing.
- A stock picker with "All stocks" as the first choice.
- A grouped bar chart: filing types (results, order win, rating, dividend, management change, fundraise) with three bars each (1, 5, 20 days), labelled with the number of events.
- A clear warning box: "Averages of a handful of events are mostly noise. The number in brackets is how many events each is based on."
- A table of the averages with the number of events.

Filings (library): every filing of the user's stocks.
- Filters: stock, type (multi-select), "Search title and text", "Since" date, and a "Show BSE and NSE copies once" switch (on).
- "128 filings", then the same filings table as on the Stock page; clicking a row shows its text underneath.

News (library): articles about the user's stocks.
- Filters: stock, "Search headlines", "Since" date, a "Hide off-topic and repeats" switch (on), "Importance at least" (1–5), and topic.
- "312 articles, 14 not triaged yet", then the same news table as on the Stock page.
```

## Prompt 6: Manage stocks, Settings and System

```
Design three set-up pages: Manage stocks, Settings and System.

Manage stocks:
- "Add a stock": a search box ("Company name, NSE symbol, BSE code or ISIN"); typing "kon" shows matches such as "KONKANBNK · Konkan Bank · BSE 532911". After picking one: a choice of "Stocks I own" or "Watchlist", "Other names in the news" (comma-separated, e.g. "KBL, Konkan"), a sector benchmark picker, and an "Add" button. After adding, a note and a "Load history now" button, with a progress box showing lines as it works.
- "Your stocks": an editable table: symbol, company, "I own it" checkbox, sector benchmark (dropdown), other names, peers, and a "remove" checkbox; and a "Save changes" button.

Settings:
- "AI features": a green note "An API key is set, ending in ...x7Qa" (or an amber one "No API key: the AI features are off"); a password box "Anthropic API key" with "Check and save the key"; "Remove the saved key". A bar: "Nov 2026: $3.40 spent of the $20.00 budget". A form: monthly budget (US$), "Model for sorting and extracting" and "Model for explaining and analysing" (Haiku, Sonnet, Opus), and "Save".
- "Unusual days": a slider from 1.5 to 3.0 (2.0 selected): "Mark a day unusual when the stock's move against the Nifty 50 is at least this many standard deviations of its last 60 days", with the note "2.0 marks about 1 trading day in 20".
- "Scheduled jobs": a table of about 15 jobs: on/off checkbox, job, what it does, next run (India time); and "Save the jobs".
- "First-run setup": a "Run the setup again" button.
- "Where each setting comes from": a small table of setting and source ("Settings page", ".env" or "default").

System:
- "Run a job now": a job picker ("explain: likely cause of each unusual day") and a "Run now" button; while running, a box with live log lines.
- Two columns: "Schedule (India time)", each job with its next run or "off on Settings"; and "Stored data", counts such as filings 18,240, news articles 42,915, daily prices 1,903,112.
- "AI usage": spent this month ($3.40), monthly budget ($20.00), articles waiting for triage (14), a progress bar, and a table of cost by task.
- "Recent runs": a table of started, job, status, seconds, result and error, with an "Only errors" switch.
```

## Prompt 7: Guide and the first-run Setup

```
Design the Guide page and the first-run Setup.

Guide: one long help page shown as an accordion, one section open at a time. Sections: What it is, Getting started, A daily routine, The pages, Settings, Words used, How AI is used, Where the data comes from, Keeping it running, Problems, Your data. Fill each with two or three short paragraphs or a small table of plausible help text. The "How to use this page" links on other pages open the matching section.

Setup: shown instead of the sidebar on a new installation. A progress bar at the top ("Step 2 of 4: AI features"), and Back and Next buttons at the bottom.
1. Welcome: "Welcome to Stock News Analyzer"; what it does in four lines; what it needs (this computer on in the morning, 07:10 to 08:00 India time; optionally an Anthropic API key); "Not advice: everything it shows is information to check." Buttons: "Start", and "Skip the setup; I'll set it up myself".
2. AI features: what the key turns on (explanations, earnings calls, news sorting, Ask) and what works without it; a link to get a key; a key box with "Check and save the key"; "Monthly budget, US$" set to 5. Buttons: "Next", or "Continue without AI" when there is no key.
3. Your stocks: first "Download the company list" with a progress box; then the add-a-stock form from Manage stocks, or a button "Or start with five large companies"; a line listing the stocks added ("3 stocks: ARAVINFRA (own), KONKANBNK, SAHYFOODS"). Next stays disabled until there is at least one stock.
4. History: "How far back": 1 year, 2 years, Since October 2023; an estimate ("From 21 Oct 2025: about 250 trading days, then a few minutes per stock"); a "Load history" button with a progress box listing each stock; problems listed if any; then a "Go to Today" button.
```

## Prompt 8: a final pass

```
Go over the whole app once more:
- Check every page in both light and dark themes, and fix any text or chart that is hard to read.
- Make sure every page has its one-line description, its "How to use this page" link, and an empty state (show one example empty state on Red flags and on the Stock page's Results tab).
- At a narrow width (a phone), wide tables become stacked cards and tiles wrap.
- Use the same colours, card style, spacing and number formats everywhere.
Don't add any backend, login or real data.
```

## If Lovable goes off track

Send one of these:
- It adds Supabase, a login or a database: `Remove that: this is front end only, with hard-coded sample data. No backend, no login.`
- It uses real company names: `Use only the made-up companies from the project instructions.`
- A page comes out thin: `The <page> page is too thin. Design it fully from the brief: <paste that page's section from the prompt above>.`
- Something too fancy appears (drag-and-drop, animation, pop-ups on pop-ups): `Make that simpler: these designs will be rebuilt in Streamlit, so stick to cards, tables, tabs, charts and simple forms.`

## When it looks right

Share the Lovable project link (or screenshots of the pages you like) here, with a line per page on what you like, and the pages are rebuilt in the real dashboard one pull request at a time.
