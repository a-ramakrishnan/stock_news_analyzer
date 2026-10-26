# Step 14: Order Book Tracker

**Goal:** for order-driven companies, see who is winning orders and who is executing them. That covers orders announced, the order book each quarter, book-to-bill, how fast the book turns into revenue, and how they compare.

## What was added

| Piece | Why |
| --- | --- |
| `orders`, `order_filings`, `order_book_snapshots` tables (migration 0014) | Each order; each order-win filing read and its outcome; each company's order book, inflow and revenue by quarter |
| `agents/orders.py` | Order extraction (Haiku), quarterly order books (Sonnet), and the metrics and peer ranks (code) |
| `orders` job, 07:50 daily | New order filings and order books before the digest |
| `sna orders run/list/book/peers/reset`, `make orders` | Read, list, see the quarterly table, compare, start over |
| Digest | An "Orders" section: each new order with value, client and what it is for |
| Stock page | An **Order book** tab: order book, years of revenue, book-to-bill, execution; announced vs reported inflow chart; quarterly table; orders; peers |

## Three things real filings do

- **NSE's titles say nothing.** BSE's headline reads "L&T Wins Orders (Large*) in New Delhi and Andhra Pradesh". NSE's copy of the same filing reads "…has informed the Exchange about Bagging/Receiving of orders/contracts". Matching titles misses the copy. So copies are caught three ways: an identical attached file, a similar title, or, after reading, an order with the same value (or range) from the same company within 2 days.
- **Ranges, not values.** L&T discloses orders as "significant", "large", "major" or "mega", each a range in Rs crore. The range is stored, and the midpoint counts toward inflow. The value as written is kept and checked against the filing's text.
- **"Orders" that aren't orders.** The filing classifier catches the word "orders", so a SEBI order or a purchase order the company placed can arrive as an order win. Haiku marks those as not order wins, and nothing is stored for them.

## Order books

A company is tracked once it has at least 2 orders. For each quarter, the order book, the quarter's order inflow and its revenue are read from one document, best first:

1. investor presentation (the first 40,000 characters)
2. earnings call transcript (also 40,000)
3. results (20,000)

Each figure is kept as written and checked against the document. A document is read only once. A quarter whose documents don't give the figures waits for a newer one; for example, the presentation is often filed a day after results.

## The measures

- **Book-to-bill:** orders won ÷ revenue over the last four quarters. Above 1, the order book is growing.
- **Years of revenue:** the latest order book ÷ the last four quarters' revenue.
- **Execution:** the last four quarters' revenue ÷ the order book a year earlier. This shows how fast the book turns into revenue.
- **Announced ÷ reported inflow:** how much of what the company won it actually announced.
- **Unexplained change:** closing book − (opening book + inflow − revenue). Negative suggests cancellations, or revenue from outside the order book such as services.
- **Concentration:** government/PSU share, and the largest client's share, of the last year's orders.
- **Peers:** the order-driven watchlist stocks side by side, ranked on book-to-bill, years of revenue and growth in orders announced.

## How to check it

```bash
git pull
uv sync
make migrate
uv run sna filings attachments --pdf important
uv run sna orders run
uv run sna orders list LT
uv run sna orders book LT
uv run sna orders peers
make ui
make scheduler
```

Cost: Haiku reads 8 order filings per call, for a fraction of a cent. The first run covers the whole history. Order books cost about $0.03 per company per quarter with Sonnet. After that, daily runs only read what is new.

## Tweet draft

> Agent #10: the Order Book Tracker. Every order win filed with NSE/BSE becomes a row (client, value, segment, execution period), with the BSE and NSE copies read once. Each quarter's reported order book is set against it: book-to-bill, years of revenue in hand, and how fast the book turns into revenue, ranked across my order-driven stocks. #BuildInPublic
