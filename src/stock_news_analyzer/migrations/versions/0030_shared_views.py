"""shared: read-only views of the collected data, the contract other projects read
(stock_deep_research), and a login that can read only those views

Other projects depend on these views, not on the tables behind them: the tables can change as
long as the views keep their columns. The contract and its version are documented in
docs/shared-data.md. A change that removes or renames a column needs a new major version.

The login `research_reader` (password from SNA_READER_PASSWORD when the migration runs, else
"research_reader", reachable wherever port 5433 is, like the main `sna` login) may read the
`shared` schema and nothing else.

Revision ID: 0030
Revises: 0029
Create Date: 2026-11-05 16:00:00.000000
"""

import os
from collections.abc import Sequence

from alembic import op

revision: str = "0030"
down_revision: str | None = "0029"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CONTRACT_VERSION = "1.0"
READER = "research_reader"

# name -> SELECT. Column names are the contract; keep them stable.
VIEWS = {
    "contract": f"SELECT '{CONTRACT_VERSION}'::text AS version",
    "companies": """
        SELECT c.isin, c.nse_symbol, c.bse_code, c.name, c.industry, c.market_cap_cr,
               c.listed_on, w.isin IS NOT NULL AS on_watchlist,
               coalesce(w.owned, false) AS owned, coalesce(w.study_only, false) AS study_only,
               w.sector_index
        FROM companies c LEFT JOIN watchlist w ON w.isin = c.isin""",
    "peers": "SELECT isin, peer_isin FROM company_peers",
    "index_members": "SELECT index_name, isin, symbol, industry FROM index_members",
    "documents": """
        SELECT d.id AS document_id, dc.isin, d.source, d.doc_type, d.title, d.subject,
               d.published_at, d.first_seen_at, d.url, d.publisher, d.attachment_url,
               d.text_status, d.text
        FROM documents d JOIN document_companies dc ON dc.document_id = d.id""",
    "news_triage": """
        SELECT document_id, isin, relevant, topic, sentiment, importance, summary,
               duplicate_of
        FROM news_triage""",
    "prices_daily": """
        SELECT isin, symbol, series, trade_date, prev_close, open, high, low, close, volume,
               delivery_pct
        FROM prices_daily WHERE isin IS NOT NULL""",
    "index_daily": "SELECT index_name, trade_date, close, pe, pb, div_yield FROM index_daily",
    "stock_moves": """
        SELECT isin, trade_date, stock_return, nifty_return, sector_index, sector_return,
               excess_return, sector_excess_return, zscore, unusual
        FROM stock_moves""",
    "corporate_actions": """
        SELECT symbol, isin, ex_date, subject, kind, price_factor, dividend
        FROM corporate_actions""",
    "results": """
        SELECT isin, period, period_end, months, basis, "primary", revenue_cr,
               other_income_cr, finance_costs_cr, depreciation_cr, pbt_cr, pat_cr, eps,
               model AS source_model, document_id
        FROM results""",
    "balance_sheets": """
        SELECT isin, period_end, months, basis, equity_cr, borrowings_cr, cash_cr,
               total_assets_cr, cfo_cr, capex_cr, source
        FROM balance_sheets WHERE as_written <> '{}'::jsonb""",
    "shareholding": """
        SELECT isin, quarter_end, filed_at, promoter_pct, public_pct, fii_pct, dii_pct,
               mf_pct, insurance_pct, retail_pct, pledged_pct, shareholders
        FROM shareholdings""",
    "events": """
        SELECT id AS event_id, isin, document_id, published_at, event_type, headline,
               event_date, sentiment, importance, value_cr, counterparty, person, role, action,
               quote, quote_found, qa_status, review,
               (review = 'accepted' OR (review IS NULL AND qa_status IN ('passed', 'flagged')))
                   AS shown
        FROM events WHERE duplicate_of IS NULL""",
    "orders": """
        SELECT id AS order_id, isin, document_id, announced_at, kind, client, client_type,
               segment, geography, value_cr, execution_months, description
        FROM orders""",
    "order_books": """
        SELECT isin, quarter, period_end, order_book_cr, inflow_cr, revenue_cr
        FROM order_book_snapshots""",
    "concalls": """
        SELECT id AS concall_id, isin, document_id, quarter, period_end, call_date, tone,
               summary
        FROM concalls WHERE status = 'analysed'""",
    "concall_points": """
        SELECT p.concall_id, c.isin, p.category, p.text, p.sentiment, p.quote, p.quote_found
        FROM concall_points p JOIN concalls c ON c.id = p.concall_id""",
    "promises": """
        SELECT id AS promise_id, isin, statement, metric, target, due, due_date, status,
               status_note
        FROM promises""",
    "red_flags": """
        SELECT id AS flag_id, isin, kind, severity, title, detail, flagged_on, document_id,
               dismissed_at
        FROM red_flags""",
    "deals": """
        SELECT trade_date, isin, symbol, kind, client, side, quantity, price
        FROM deals WHERE isin IS NOT NULL""",
}


def upgrade() -> None:
    password = os.environ.get("SNA_READER_PASSWORD", READER).replace("'", "''")
    op.execute("CREATE SCHEMA IF NOT EXISTS shared")
    for name, query in VIEWS.items():
        op.execute(f"CREATE OR REPLACE VIEW shared.{name} AS {query}")
    op.execute(
        f"""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '{READER}') THEN
                CREATE ROLE {READER} LOGIN PASSWORD '{password}';
            END IF;
        END $$"""
    )
    op.execute(f'GRANT CONNECT ON DATABASE "{_database()}" TO {READER}')
    op.execute(f"GRANT USAGE ON SCHEMA shared TO {READER}")
    op.execute(f"GRANT SELECT ON ALL TABLES IN SCHEMA shared TO {READER}")


def downgrade() -> None:
    op.execute("DROP SCHEMA IF EXISTS shared CASCADE")


def _database() -> str:
    return op.get_bind().exec_driver_sql("SELECT current_database()").scalar()
