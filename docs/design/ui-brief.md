# Dashboard design brief (for Lovable)

It asks for clickable mock-ups with sample data, not a working app: the real dashboard stays in Python (Streamlit), and the chosen designs are rebuilt there. To feed it to Lovable, use [lovable-prompts.md](lovable-prompts.md): the same brief split into prompts to paste one at a time.

---

## What to build

Clickable design mock-ups for **Stock News Analyzer**, a dashboard that follows a list of Indian stocks for one person. Every morning it reads what each company filed with the stock exchanges (NSE and BSE), the news about it, its share price, quarterly results, shareholding and earnings calls, and shows what changed and why it might matter. It runs on the user's own computer at http://localhost:8501.

Rules for the mock-ups:
- **Front end only, with hard-coded sample data.** No Supabase, no database, no login, no API calls, no payments.
- **Sample data uses made-up companies,** for example Aravalli Infra (ARAVINFRA), Konkan Bank (KONKANBNK), Deccan Cables (DECCANCAB), Sahyadri Foods (SAHYFOODS), Narmada Marine (NARMADAMAR) and Vindhya Pharma (VINDHYAPH). Two or three are "Stocks I own", the rest "Watchlist".
- **Readers:** individual investors, not traders. It shows information to check, never buy or sell advice. There are no candlestick charts or technical indicators.
- **Formats:** rupees as ₹1,234.50; large amounts in crore with Indian grouping (Rs 1,23,456 cr); dates as 21 Oct 2026; times in India time (IST); percentages with a sign (+1.24%, −0.37%).
- **Colours:** green for up and red for down, and the same red / amber / grey for high / medium / low red flags everywhere. Light and dark themes.
- **AI-written text** (explanations, summaries, answers) is marked as such and lists its sources, so it is never mistaken for a filing.
- **Desktop first;** at a narrow width, wide tables become stacked cards.
- **Keep the building blocks simple,** because the designs will be rebuilt in Streamlit: a sidebar, cards, number tiles with a change underneath, tables, tabs, line and bar charts, expandable sections, badges, simple forms. Avoid drag-and-drop, custom hover interactions, modals on top of modals, and animation.

Design every page below. Each one opens with a one-line "what this shows", has a small "How to use this page" link to the Guide, and has an empty state that says what to do (for example "No results yet: load history on Manage stocks").

## Navigation

A left sidebar, in groups:

| Group | Pages |
| --- | --- |
| Today | Today, Red flags |
| Research | Stock, Ask, Themes, What moves the stock |
| Library | Filings, News |
| Set up | Manage stocks, Settings, System |
| Help | Guide |

A new installation first shows a 4-step **Setup** instead of the sidebar (see the end).

## Today (the home page)

The first page each morning: what changed since yesterday.
- **Header:** "Last trading day loaded: Wed 21 Oct 2026".
- **Index tiles,** in a row: Nifty 50, Nifty Bank, Nifty Infrastructure, Nifty Auto and so on. Each shows its level (22,811.35) and the day's change (▼ −0.34%).
- **Red flags, last 30 days:** up to about 5 lines, such as "21 Oct · auditor resigned · DECCANCAB: Statutory auditor resigns citing...", red for high and amber for medium. A link goes to the Red flags page.
- **Stock cards in two groups,** "Stocks I own (3)" and "Watchlist (6)", three cards to a row. Each card shows:
  - the symbol and company name
  - the close (₹1,234.50) and the day's change (+1.24%), with a 3-month sparkline
  - the move against the Nifty 50 and against its sector index (vs Nifty 50 +0.87%, vs Nifty Bank +0.40%), and the z-score (z 2.4)
  - an **Unusual** badge when the move was unusually large, with "Likely cause: order win" under it
  - "Last 7 days: 4 filings, 12 news articles", and an Open link to the Stock page
- **Bullion:** tabs for Gold and Silver. A 30-day table with these columns: day, ETF close (₹), move in rupees, then the move split into global price, USD/INR and other, z-score, driver, and a note on unusual days.
- **Latest digest:** the morning report (long text with headings), collapsed until opened.
- **Data collection:** a small table of each job (filings, news, prices...) with its last run time and ✅ ok or ⚠️ error.

## Red flags

Warnings about governance and money: an auditor or CFO leaving, a rating cut, pledged shares, promoters selling, a penalty, results filed late.
- **Filters:** severity (high, medium, low; high and medium chosen by default), "Raised in the last" (30 days, 90 days, 1 year, 3 years), stocks, and a "Show dismissed" switch.
- **Table columns:** raised (date), severity, stock, kind, what happened, status (open or dismissed), your note, and a link to the filing.
- **Dismissing:** select a flag, then press **Dismiss** with an optional note ("Planned retirement; successor named"). A dismissed flag can be opened again.

## Stock (one company in depth)

- **Top bar:** a stock picker, and a range switch (1M, 3M, 6M, 1Y, 3Y).
- **Heading:** the company name, then "NSE ARAVINFRA · benchmark Nifty 50 and Nifty Infrastructure · owned".
- **Four number tiles:** the stock over the range (+18.2%), the Nifty 50 over the range (+6.1%), the sector index over the range (+9.4%), and the number of unusual days (7).
- **Main chart:** the stock, its sector index and the Nifty 50 as three lines, each starting at 100. Diamond markers show key filings (results, order wins, ratings), and circles show unusual days.
- **Second chart:** daily bars of the stock's return minus the Nifty 50's, with unusual days solid.
- **Tabs below:**
  1. **Unusual days:** day, stock move, move vs Nifty 50, z, likely cause, confidence (high, medium, low), explanation (AI, 2–3 sentences), and "Based on" (the filings and news it used).
  2. **Results:** tiles for the latest quarter's revenue (Rs 1,240 cr, +18% y/y), profit after tax (Rs 96 cr, +22% y/y) and EBITDA margin (14.2%). A bar chart of quarterly revenue with profit as a line. A table of each quarter: revenue, y/y, EBITDA, margin, profit, y/y, net margin, EPS, and a "checked" tick.
  3. **Shareholding:** tiles for promoters, foreign institutions, domestic institutions and retail, as % with the change in points since the last quarter. A line chart of the four over 12 quarters. A table with those plus mutual funds, insurers, pledged % and the number of shareholders.
  4. **Events:** red flags for the last 12 months on top, then a table of events read from filings: filed date, type (capex, rating, management change, legal, deal, fundraise, promoter action, disruption), importance 1–5 as a bar, sentiment, headline, amount (with its share of revenue), a QA check result, the quote from the filing, and a link.
  5. **Earnings calls:**
     - a call picker ("Q2 FY27 · filed 15 Oct 2026 · positive")
     - the tone and an AI summary paragraph
     - "To watch" bullets, and "Since the previous call" bullets
     - "What management said": topic (guidance, demand, margins, capex, order book, risks), point, good or bad for shareholders, and the quote
     - "What analysts pressed on": topic, question, answer
     - the transcript text, collapsed
     - the **Promise ledger:** "Promises kept 67%" with the counts (kept, late, partly, missed, dropped, overdue), and a table of each promise, its target, when it is due, status, latest update and quote
  6. **Order book** (for companies that win orders):
     - tiles for the order book (Rs 12,400 cr), years of revenue (2.8), book-to-bill (1.3x) and execution (36%)
     - a quarterly bar chart of orders announced against the inflow reported, with the order book as a line
     - a table by quarter, and the list of orders announced (date, Rs crore, client type, months, what for)
     - a comparison with the other order-driven stocks
  7. **Filings:** published (IST), exchange, type, title and a PDF link. Selecting a row shows the filing's text underneath.
  8. **News:** published, importance (★ 1–5), topic, good or bad for shareholders, headline, AI one-line summary, and a link.
  9. **Bulk/block deals:** day, bulk or block, buy or sell, shares, price, % of the day's volume, and the client.
  10. **How it reacted:** each filing or article, with the stock's return vs the Nifty 50 1, 5 and 20 trading days later.
  11. **Corporate actions:** ex-date, kind (bonus, split, dividend), price factor, and dividend in ₹.

## Ask

Questions in plain English, answered from the user's own data.
- **The question box:** a text box ("Which of my companies raised guidance this year?"), an optional "Save as report" name, and an Ask button.
- **While it works:** progress lines ("Looking up events... 4 lookups").
- **The answer:** formatted text, often with a table, and numbered sources under it ("[3] ARAVINFRA Q2 FY27 call (15 Oct 2026), guidance: ..."). The cost is shown small ("4 lookups, $0.07").
- **Earlier questions:** a list of earlier questions, each opening to its answer.

## Themes

Themes across the user's companies, such as data centres, defence, credit growth or exports.
- **The theme table:** theme, items in the last 90 days, items in the 90 days before (showing whether it is rising), positive and negative counts, orders in Rs crore, and the companies involved.
- **One theme:** a picker, a monthly bar chart, and the list of items (date, item, Rs crore).
- **Read-across:** news at one company that may matter to another, with the date, the item and the companies it may affect.

## What moves the stock

How stocks moved on average 1, 5 and 20 trading days after each kind of filing (results, order win, rating, dividend...).
- **Charts and table:** a stock picker (or all stocks), a grouped bar chart by filing type, and a table of averages with the number of events behind each.
- **A visible warning:** averages of a handful of events are mostly noise.

## Filings and News (the library)

- **Filings:** filters for stock, type, a search of the title and text, a "since" date, and a "show BSE and NSE copies once" switch. The table and row selection are as on the Stock page, with a count ("128 filings").
- **News:** filters for stock, a headline search, a "since" date, "hide off-topic and repeats", "importance at least" (1–5), and topic. The table is as on the Stock page, with a count ("312 articles, 14 not triaged yet").

## Manage stocks

- **Add a stock:** a search box ("Company name, NSE symbol, BSE code or ISIN") and a list of matches. Then a choice of **Stocks I own** or **Watchlist**, "Other names in the news" (comma-separated aliases), a sector benchmark picker, and **Add**. After adding, a **Load history now** button and a progress box.
- **Your stocks:** an editable table with symbol, company, "I own it" checkbox, sector benchmark, aliases, peers and a remove checkbox, and **Save changes**.

## Settings

- **AI features:**
  - whether an Anthropic API key is set ("ending in ...x7Qa"), a password box with **Check and save the key**, and **Remove the saved key**
  - this month's spend against the budget as a bar ("Nov: $3.40 spent of the $20.00 budget")
  - a monthly budget box, and two model pickers: one for sorting and extracting, one for explaining and analysing
- **Unusual days:** a slider from 1.5 to 3.0 standard deviations, with the note "2.0 marks about 1 trading day in 20".
- **Scheduled jobs:** a table with an on/off checkbox, job, what it does and its next run, and **Save the jobs**.
- **First-run setup:** **Run the setup again**.
- **Where each setting comes from:** setting, and "Settings page", ".env" or "default".

## System

- **Run a job now:** a job picker ("explain: likely cause of each unusual day") and **Run now**. While it runs, a live log appears in a box.
- **Schedule:** each job's next run (India time), or "off on Settings".
- **Stored data:** counts of filings, articles, prices, events and so on.
- **AI usage:** spent this month, the budget, articles waiting for triage, and a table of cost by task.
- **Recent runs:** started, job, status, seconds, result and error, with an "only errors" switch.

## Guide

One long help page shown as an accordion. The sections are: What it is, Getting started, A daily routine, The pages, Settings, Words used, How AI is used, Where the data comes from, Keeping it running, Problems, Your data. A link from any page opens its own section.

## Setup (a new installation only)

Four steps with a progress bar ("Step 2 of 4: AI features"), and Back and Next buttons:
1. **Welcome:** what it does in a few lines; what it needs (the computer on in the morning, optionally an API key); "Not advice". **Start**, or "Skip the setup".
2. **AI features:** what the key turns on and what works without it; a key box with check-and-save; a monthly budget ($5 suggested). **Next** or **Continue without AI**.
3. **Your stocks:** first a **Download the company list** button with a progress box, then the add-a-stock form, or one button to "Start with five large companies". **Next** waits for at least one stock.
4. **History:** how far back (1 year, 2 years, since October 2023) with a time estimate; **Load history** with a progress box listing each stock; problems listed; then **Go to Today**.

---

## After Lovable

Send the Lovable project link, or screenshots of the pages you like, with a note on what you want from each. The designs are rebuilt in the Streamlit dashboard page by page, in pull requests as usual.
