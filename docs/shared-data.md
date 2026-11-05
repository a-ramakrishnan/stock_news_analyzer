# Shared data: the contract for other projects

Version 1.0 · Nov 5, 2026

Other projects, starting with [stock_deep_research](https://github.com/a-ramakrishnan/stock_deep_research), read the data this one collects through read-only views in the `shared` schema of the same database. They depend on these views, not on the tables behind them: the tables can change as long as the views keep their columns.

## Connecting

| | |
| --- | --- |
| Host and port | `localhost:5433` (the Docker Postgres) |
| Database | `sna` |
| Login | `research_reader`, password `research_reader` (set `SNA_READER_PASSWORD` in `.env` before the first `make start` or `uv run sna db upgrade` to choose another; like the main `sna` login it is reachable wherever Docker publishes port 5433, so on a shared network set both) |
| Rights | `SELECT` on the `shared` views only; nothing in `public`, no writes |

```
postgresql+psycopg://research_reader:research_reader@localhost:5433/sna
```

`SELECT version FROM shared.contract` gives the contract's version.

## Versions

A new view or a new column is a minor version (1.1). Removing or renaming a column, or changing what a column means, is a major version (2.0), announced in this file first. The views are created by migration 0030 and any later migration that changes them.

## The views

Money is in Rs crore, percentages in percent (19.39 means 19.39%) unless the column says otherwise, times are with time zone, dates are India dates.

| View | One row per | Columns |
| --- | --- | --- |
| `contract` | – | `version` |
| `companies` | listed company (NSE main board, SME, BSE) | `isin`, `nse_symbol`, `bse_code`, `name`, `industry` (NSE's, Nifty 500 members), `market_cap_cr` (BSE's), `listed_on`, `on_watchlist`, `owned`, `study_only`, `sector_index` (its benchmark) |
| `peers` | approved peer pair | `isin`, `peer_isin` |
| `index_members` | index member as NSE last listed it | `index_name`, `isin`, `symbol`, `industry` |
| `documents` | filing or article and company it is about | `document_id`, `isin`, `source` (`bse`, `nse`, `news:<feed>`), `doc_type` (`results`, `order_win`, `board_meeting`, `news`, ...), `title`, `subject`, `published_at`, `first_seen_at`, `url`, `publisher`, `attachment_url`, `text_status`, `text` |
| `news_triage` | article and company | `document_id`, `isin`, `relevant`, `topic`, `sentiment`, `importance` (1–5), `summary`, `duplicate_of` |
| `prices_daily` | trading day and listing | `isin`, `symbol`, `series`, `trade_date`, `prev_close` (not adjusted), `open`, `high`, `low`, `close`, `volume`, `delivery_pct` |
| `index_daily` | NSE index and day | `index_name`, `trade_date`, `close`, `pe`, `pb`, `div_yield` |
| `stock_moves` | watchlist stock and day | `isin`, `trade_date`, `stock_return` (adjusted for bonuses, splits and dividends), `nifty_return`, `sector_index`, `sector_return`, `excess_return`, `sector_excess_return`, `zscore`, `unusual` |
| `corporate_actions` | action | `symbol`, `isin`, `ex_date`, `subject`, `kind`, `price_factor`, `dividend` (Rs a share) |
| `results` | reported period | `isin`, `period` (`Q2 FY27`, `H1 FY27`, `FY27`), `period_end`, `months`, `basis`, `primary` (the one to use), `revenue_cr`, `other_income_cr`, `finance_costs_cr`, `depreciation_cr`, `pbt_cr`, `pat_cr`, `eps` (Rs, basic), `source_model` (`xbrl` = as filed; otherwise read by a model), `document_id` |
| `balance_sheets` | half year or year end | `isin`, `period_end`, `months` (the cash flow's span), `basis`, `equity_cr`, `borrowings_cr`, `cash_cr`, `total_assets_cr`, `cfo_cr`, `capex_cr`, `source` (the XBRL file) |
| `shareholding` | quarter | `isin`, `quarter_end`, `filed_at`, `promoter_pct`, `public_pct`, `fii_pct`, `dii_pct`, `mf_pct`, `insurance_pct`, `retail_pct`, `pledged_pct` (of the promoters' shares), `shareholders` |
| `events` | typed event (not repeats) | `event_id`, `isin`, `document_id`, `published_at`, `event_type`, `headline`, `event_date`, `sentiment`, `importance`, `value_cr`, `counterparty`, `person`, `role`, `action`, `quote`, `quote_found`, `qa_status`, `review`, `shown` (passed the QA check or accepted: use these) |
| `orders` | order | `order_id`, `isin`, `document_id`, `announced_at`, `kind`, `client`, `client_type`, `segment`, `geography`, `value_cr`, `execution_months`, `description` |
| `order_books` | reported quarter | `isin`, `quarter`, `period_end`, `order_book_cr`, `inflow_cr`, `revenue_cr` |
| `concalls` | earnings call analysed | `concall_id`, `isin`, `document_id`, `quarter`, `period_end`, `call_date`, `tone`, `summary` |
| `concall_points` | point made on a call | `concall_id`, `isin`, `category`, `text`, `sentiment`, `quote`, `quote_found` |
| `promises` | management promise | `promise_id`, `isin`, `statement`, `metric`, `target`, `due`, `due_date`, `status`, `status_note` |
| `red_flags` | flag | `flag_id`, `isin`, `kind`, `severity`, `title`, `detail`, `flagged_on`, `document_id`, `dismissed_at` |
| `deals` | bulk or block deal | `trade_date`, `isin`, `symbol`, `kind`, `client`, `side`, `quantity`, `price` |

Everything is point in time where the source allows: a document's `published_at` is when the exchange or publisher released it, `first_seen_at` when this system saw it.
