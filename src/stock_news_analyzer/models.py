"""Database tables. Each step adds the tables its agents need; migrations live in `migrations/`."""

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Company(Base):
    """Master list of listed Indian securities, keyed by ISIN, built from NSE and BSE lists."""

    __tablename__ = "companies"

    isin: Mapped[str] = mapped_column(String(12), primary_key=True)
    name: Mapped[str] = mapped_column(Text)
    nse_symbol: Mapped[str | None] = mapped_column(String(32), index=True)
    nse_series: Mapped[str | None] = mapped_column(String(4))
    bse_code: Mapped[str | None] = mapped_column(String(10), index=True)
    bse_symbol: Mapped[str | None] = mapped_column(String(32))
    # Broad NSE industry (from the Nifty 500 list) and finer BSE industry, when known.
    industry: Mapped[str | None] = mapped_column(Text)
    bse_industry: Mapped[str | None] = mapped_column(Text)
    # Market capitalisation in Rs crore, from BSE's scrip list (as of the last refresh).
    market_cap_cr: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    in_nifty500: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    listed_on: Mapped[date | None] = mapped_column(Date)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class WatchlistItem(Base):
    """A stock or bullion instrument you track, and whether you own it."""

    __tablename__ = "watchlist"
    __table_args__ = (
        CheckConstraint(
            "(kind = 'equity' AND isin IS NOT NULL AND commodity IS NULL)"
            " OR (kind = 'commodity' AND commodity IS NOT NULL AND isin IS NULL)",
            name="watchlist_kind_fields",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(16))  # 'equity' or 'commodity'
    isin: Mapped[str | None] = mapped_column(ForeignKey("companies.isin"), unique=True)
    commodity: Mapped[str | None] = mapped_column(String(16), unique=True)  # 'GOLD', 'SILVER'
    display_name: Mapped[str] = mapped_column(Text)
    owned: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    quantity: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    notes: Mapped[str | None] = mapped_column(Text)
    # Other names the news uses for the company, e.g. "L&T". Short ones match case-sensitively.
    aliases: Mapped[list[str]] = mapped_column(
        ARRAY(Text), default=list, server_default="{}", nullable=False
    )
    # Phrases that look like this company but are another one, e.g. "L&T Technology".
    exclude: Mapped[list[str]] = mapped_column(
        ARRAY(Text), default=list, server_default="{}", nullable=False
    )
    # NSE sector index used as a second benchmark, e.g. "Nifty Bank" (Nifty 50 is always used).
    sector_index: Mapped[str | None] = mapped_column(String(64))
    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CompanyPeer(Base):
    """A peer you approved for a company; used later to read news across peers."""

    __tablename__ = "company_peers"

    isin: Mapped[str] = mapped_column(ForeignKey("companies.isin"), primary_key=True)
    peer_isin: Mapped[str] = mapped_column(ForeignKey("companies.isin"), primary_key=True)
    source: Mapped[str] = mapped_column(String(32))  # how it was suggested, e.g. 'industry'
    approved_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Document(Base):
    """Any raw item collected: exchange filings now, news articles later. Never edited.

    `published_at` is when the source made it public; `first_seen_at` is when we collected it.
    A future model may only use what was seen before the moment it is predicting.
    """

    __tablename__ = "documents"
    __table_args__ = (UniqueConstraint("source", "source_id", name="documents_source_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(64))  # 'bse', 'nse', 'news:<feed key>'
    source_id: Mapped[str] = mapped_column(String(64))
    doc_type: Mapped[str] = mapped_column(String(32), index=True)  # see announcements.classify
    title: Mapped[str] = mapped_column(Text)
    subject: Mapped[str | None] = mapped_column(Text)
    category: Mapped[str | None] = mapped_column(Text)
    url: Mapped[str | None] = mapped_column(Text)  # the article's web page (news)
    publisher: Mapped[str | None] = mapped_column(Text)  # e.g. 'Economic Times'
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    attachment_url: Mapped[str | None] = mapped_column(Text)
    attachment_path: Mapped[str | None] = mapped_column(Text)  # relative to DATA_DIR
    attachment_sha256: Mapped[str | None] = mapped_column(String(64), index=True)
    attachment_bytes: Mapped[int | None] = mapped_column(BigInteger)
    text: Mapped[str | None] = mapped_column(Text)
    # 'pending', 'ok', 'partial' (source file broken; some text recovered),
    # 'empty' (scanned PDF, no text layer), 'skipped', 'failed'
    text_status: Mapped[str] = mapped_column(String(16), default="pending")
    raw: Mapped[dict] = mapped_column(JSONB)


class DocumentCompany(Base):
    """Which companies a document is about."""

    __tablename__ = "document_companies"

    document_id: Mapped[int] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), primary_key=True
    )
    isin: Mapped[str] = mapped_column(ForeignKey("companies.isin"), primary_key=True, index=True)


class PriceDaily(Base):
    """One row per NSE symbol, series and trading day, from NSE's full bhavcopy.

    All listed stocks are stored, not just the watchlist, so peers and later models have data.
    """

    __tablename__ = "prices_daily"

    symbol: Mapped[str] = mapped_column(String(32), primary_key=True)
    series: Mapped[str] = mapped_column(String(4), primary_key=True)
    trade_date: Mapped[date] = mapped_column(Date, primary_key=True, index=True)
    isin: Mapped[str | None] = mapped_column(String(12), index=True)  # main series only
    prev_close: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))  # adjusted on ex-dates
    open: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    high: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    low: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    last: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    close: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    avg_price: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    volume: Mapped[int | None] = mapped_column(BigInteger)
    turnover_lacs: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    trades: Mapped[int | None] = mapped_column(BigInteger)
    delivery_qty: Mapped[int | None] = mapped_column(BigInteger)
    delivery_pct: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))


class IndexDaily(Base):
    """Daily close of every NSE index (Nifty 50, sector indices), with P/E, P/B and yield."""

    __tablename__ = "index_daily"

    index_name: Mapped[str] = mapped_column(String(64), primary_key=True)
    trade_date: Mapped[date] = mapped_column(Date, primary_key=True, index=True)
    open: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    high: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    low: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    close: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    pe: Mapped[Decimal | None] = mapped_column(Numeric(8, 2))
    pb: Mapped[Decimal | None] = mapped_column(Numeric(8, 2))
    div_yield: Mapped[Decimal | None] = mapped_column(Numeric(8, 2))


class StockMove(Base):
    """A watchlist stock's daily return against its benchmarks, and whether it was unusual."""

    __tablename__ = "stock_moves"

    isin: Mapped[str] = mapped_column(ForeignKey("companies.isin"), primary_key=True)
    trade_date: Mapped[date] = mapped_column(Date, primary_key=True)
    stock_return: Mapped[float] = mapped_column()
    nifty_return: Mapped[float | None] = mapped_column()
    sector_index: Mapped[str | None] = mapped_column(String(64))
    sector_return: Mapped[float | None] = mapped_column()
    excess_return: Mapped[float | None] = mapped_column()  # stock minus Nifty 50
    sector_excess_return: Mapped[float | None] = mapped_column()  # stock minus sector index
    # Excess return divided by the standard deviation of the previous 60 days' excess returns.
    zscore: Mapped[float | None] = mapped_column()
    unusual: Mapped[bool] = mapped_column(Boolean, default=False, index=True)


class EventLabel(Base):
    """What a stock did after a filing or article: the training label for a future model.

    `day0` is the first trading day whose close could reflect the news (same day if published
    before 15:30 IST on a trading day, otherwise the next trading day). Returns are compounded
    from day0 over 1, 5 and 20 trading days; None until enough days have passed.
    """

    __tablename__ = "event_labels"

    document_id: Mapped[int] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), primary_key=True
    )
    isin: Mapped[str] = mapped_column(ForeignKey("companies.isin"), primary_key=True)
    day0: Mapped[date | None] = mapped_column(Date)
    return_1d: Mapped[float | None] = mapped_column()
    return_5d: Mapped[float | None] = mapped_column()
    return_20d: Mapped[float | None] = mapped_column()
    excess_1d: Mapped[float | None] = mapped_column()  # vs Nifty 50
    excess_5d: Mapped[float | None] = mapped_column()
    excess_20d: Mapped[float | None] = mapped_column()
    sector_index: Mapped[str | None] = mapped_column(String(64))
    sector_excess_1d: Mapped[float | None] = mapped_column()
    sector_excess_5d: Mapped[float | None] = mapped_column()
    sector_excess_20d: Mapped[float | None] = mapped_column()
    complete: Mapped[bool] = mapped_column(Boolean, default=False)  # all windows filled
    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class CorporateAction(Base):
    """NSE corporate actions (bonus, split, dividend...) used to adjust daily returns.

    Keyed by NSE symbol rather than ISIN: NSE's records sometimes carry an older ISIN.
    """

    __tablename__ = "corporate_actions"

    symbol: Mapped[str] = mapped_column(String(32), primary_key=True)
    ex_date: Mapped[date] = mapped_column(Date, primary_key=True)
    subject: Mapped[str] = mapped_column(Text, primary_key=True)
    series: Mapped[str | None] = mapped_column(String(4))
    isin: Mapped[str | None] = mapped_column(String(12))
    kind: Mapped[str] = mapped_column(String(16))  # bonus, split, consolidation, dividend, ...
    price_factor: Mapped[float] = mapped_column(default=1.0)
    dividend: Mapped[Decimal | None] = mapped_column(Numeric(14, 4))
    raw: Mapped[dict] = mapped_column(JSONB)


class Run(Base):
    """One run of a scheduled job (filings, news, prices, digest...), for monitoring."""

    __tablename__ = "runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    job: Mapped[str] = mapped_column(String(32), index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(16))  # 'running', 'ok', 'error'
    summary: Mapped[str | None] = mapped_column(Text)
    error: Mapped[str | None] = mapped_column(Text)


class LlmCall(Base):
    """One call to an LLM: what it was for, tokens used and what it cost (for the budget)."""

    __tablename__ = "llm_calls"

    id: Mapped[int] = mapped_column(primary_key=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    task: Mapped[str] = mapped_column(String(32), index=True)  # e.g. 'triage'
    model: Mapped[str] = mapped_column(String(64))
    input_tokens: Mapped[int] = mapped_column(default=0)
    output_tokens: Mapped[int] = mapped_column(default=0)
    cache_read_tokens: Mapped[int] = mapped_column(default=0)
    cache_write_tokens: Mapped[int] = mapped_column(default=0)
    cost_usd: Mapped[Decimal] = mapped_column(Numeric(10, 5), default=0)
    ok: Mapped[bool] = mapped_column(Boolean, default=True)
    error: Mapped[str | None] = mapped_column(Text)


class NewsTriage(Base):
    """News Triage (agent 6): what one article means for one watchlist company.

    Copies of the same story (near-identical headline within a few days) point to the first
    article with `duplicate_of` and reuse its triage; `model` is empty for those.
    """

    __tablename__ = "news_triage"

    document_id: Mapped[int] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), primary_key=True
    )
    isin: Mapped[str] = mapped_column(ForeignKey("companies.isin"), primary_key=True)
    relevant: Mapped[bool] = mapped_column(Boolean)  # really about this company?
    topic: Mapped[str] = mapped_column(String(32), index=True)
    sentiment: Mapped[str] = mapped_column(String(16))  # positive/negative/neutral/mixed
    importance: Mapped[int] = mapped_column()  # 1 (noise) .. 5 (could move the stock)
    summary: Mapped[str] = mapped_column(Text)
    duplicate_of: Mapped[int | None] = mapped_column(
        ForeignKey("documents.id", ondelete="SET NULL"), index=True
    )
    model: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class MoveExplanation(Base):
    """Move Explainer (agent 7): the likely reason for one unusual day of one stock."""

    __tablename__ = "move_explanations"

    isin: Mapped[str] = mapped_column(ForeignKey("companies.isin"), primary_key=True)
    trade_date: Mapped[date] = mapped_column(Date, primary_key=True)
    # results, order, company_news, sector, market, corporate_action, flows, unexplained
    cause: Mapped[str] = mapped_column(String(32), index=True)
    confidence: Mapped[str] = mapped_column(String(8))  # low / medium / high
    explanation: Mapped[str] = mapped_column(Text)
    evidence: Mapped[list[int]] = mapped_column(ARRAY(BigInteger), default=list)  # document ids
    model: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Deal(Base):
    """An NSE bulk or block deal: who bought or sold how many shares at what price."""

    __tablename__ = "deals"
    __table_args__ = (
        UniqueConstraint(
            "kind",
            "trade_date",
            "symbol",
            "client",
            "side",
            "quantity",
            "price",
            name="deals_key",
            postgresql_nulls_not_distinct=True,  # a deal without a price is still one deal
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(8))  # 'bulk' or 'block'
    trade_date: Mapped[date] = mapped_column(Date, index=True)
    symbol: Mapped[str] = mapped_column(String(32), index=True)
    isin: Mapped[str | None] = mapped_column(String(12), index=True)
    security_name: Mapped[str | None] = mapped_column(Text)
    client: Mapped[str] = mapped_column(Text)
    side: Mapped[str] = mapped_column(String(4))  # BUY / SELL
    quantity: Mapped[int] = mapped_column(BigInteger)
    price: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    remarks: Mapped[str | None] = mapped_column(Text)


class Concall(Base):
    """Concall Analyst (agent 11): one earnings call transcript and what it says.

    One row per transcript filing looked at, so nothing is read twice. Only rows with status
    'analysed' carry an analysis; the others say why not in `note`: 'duplicate' (the same call
    filed on the other exchange), 'no_text' (scanned, or a letter whose link could not be
    fetched), 'skipped' (not an earnings call, e.g. an AGM).
    """

    __tablename__ = "concalls"

    id: Mapped[int] = mapped_column(primary_key=True)
    isin: Mapped[str] = mapped_column(ForeignKey("companies.isin"), index=True)
    document_id: Mapped[int] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), unique=True
    )
    status: Mapped[str] = mapped_column(String(16), index=True)
    note: Mapped[str | None] = mapped_column(Text)
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    quarter: Mapped[str | None] = mapped_column(String(16))  # results quarter, e.g. 'Q2 FY27'
    period_end: Mapped[date | None] = mapped_column(Date)  # last day of that quarter
    call_date: Mapped[date | None] = mapped_column(Date)
    # Where the text came from: the filing's PDF, or a transcript the filing only linked to.
    text_source: Mapped[str | None] = mapped_column(String(16))  # 'filing' or 'link'
    text_chars: Mapped[int | None] = mapped_column()
    linked_url: Mapped[str | None] = mapped_column(Text)
    linked_path: Mapped[str | None] = mapped_column(Text)  # relative to DATA_DIR
    linked_text: Mapped[str | None] = mapped_column(Text)
    tone: Mapped[str | None] = mapped_column(String(16))  # positive/neutral/cautious/negative
    summary: Mapped[str | None] = mapped_column(Text)
    analysis: Mapped[dict | None] = mapped_column(JSONB)  # the model's full structured answer
    model: Mapped[str | None] = mapped_column(String(64))
    prompt_version: Mapped[str | None] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ConcallPoint(Base):
    """One point from a call: guidance, demand, margins, capex, order book, risk, initiative."""

    __tablename__ = "concall_points"

    id: Mapped[int] = mapped_column(primary_key=True)
    concall_id: Mapped[int] = mapped_column(
        ForeignKey("concalls.id", ondelete="CASCADE"), index=True
    )
    category: Mapped[str] = mapped_column(String(16), index=True)
    text: Mapped[str] = mapped_column(Text)
    sentiment: Mapped[str] = mapped_column(String(16))  # positive/neutral/negative
    quote: Mapped[str | None] = mapped_column(Text)  # the speaker's words, from the transcript
    quote_found: Mapped[bool] = mapped_column(Boolean, default=False)  # quote is in the text


class Promise(Base):
    """The promise ledger: a forward-looking commitment from a call, and whether it was kept.

    Written by the Concall Analyst; each later call updates `status` when management mentions
    it again. Checking promises against results is the Promise Ledger's job (agent 12).
    """

    __tablename__ = "promises"

    id: Mapped[int] = mapped_column(primary_key=True)
    isin: Mapped[str] = mapped_column(ForeignKey("companies.isin"), index=True)
    concall_id: Mapped[int] = mapped_column(
        ForeignKey("concalls.id", ondelete="CASCADE"), index=True
    )
    statement: Mapped[str] = mapped_column(Text)
    metric: Mapped[str] = mapped_column(Text)  # e.g. 'EBITDA margin', 'Plant 2 commissioning'
    target: Mapped[str] = mapped_column(Text)  # e.g. '18-20%', 'complete'
    due: Mapped[str] = mapped_column(Text)  # as said: 'Q3 FY27', 'FY28', 'by March 2027'
    due_date: Mapped[date | None] = mapped_column(Date, index=True)  # end of that period
    quote: Mapped[str | None] = mapped_column(Text)
    quote_found: Mapped[bool] = mapped_column(Boolean, default=False)
    # open, on_track, delayed, revised (still to come); kept, kept_late, partly, missed,
    # dropped (settled). Calls set the first group and dropped; the Promise Ledger the rest.
    status: Mapped[str] = mapped_column(String(16), default="open", server_default="open")
    status_note: Mapped[str | None] = mapped_column(Text)
    status_concall_id: Mapped[int | None] = mapped_column(
        ForeignKey("concalls.id", ondelete="SET NULL")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class PromiseCheck(Base):
    """Promise Ledger (agent 12): one check of a promise against what the company reported
    after its due date. Every check is kept, including 'no_evidence', as a record of what was
    known when."""

    __tablename__ = "promise_checks"

    id: Mapped[int] = mapped_column(primary_key=True)
    promise_id: Mapped[int] = mapped_column(
        ForeignKey("promises.id", ondelete="CASCADE"), index=True
    )
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    verdict: Mapped[str] = mapped_column(String(16))  # kept/kept_late/partly/missed/no_evidence
    note: Mapped[str] = mapped_column(Text)
    evidence: Mapped[list[int]] = mapped_column(ARRAY(BigInteger), default=list)  # document ids
    model: Mapped[str] = mapped_column(String(64))
    # The promise's status and note before this check, so a reset can put them back.
    previous_status: Mapped[str] = mapped_column(String(16))
    previous_note: Mapped[str | None] = mapped_column(Text)


class OrderFiling(Base):
    """Order Book Tracker (agent 10): an order-win filing looked at, so it is read once.

    status: 'extracted' (its orders are in `orders`), 'duplicate' (the same announcement on the
    other exchange), 'not_order' (e.g. a regulator's order), 'no_text'.
    """

    __tablename__ = "order_filings"

    document_id: Mapped[int] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), primary_key=True
    )
    isin: Mapped[str] = mapped_column(ForeignKey("companies.isin"), index=True)
    status: Mapped[str] = mapped_column(String(16))
    note: Mapped[str | None] = mapped_column(Text)
    model: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Order(Base):
    """An order a company announced: who gave it, for how much, and how long it runs."""

    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(primary_key=True)
    isin: Mapped[str] = mapped_column(ForeignKey("companies.isin"), index=True)
    document_id: Mapped[int] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), index=True
    )
    announced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    kind: Mapped[str] = mapped_column(String(16))  # order, loi, l1, extension
    client: Mapped[str | None] = mapped_column(Text)
    client_type: Mapped[str] = mapped_column(String(16))  # government/psu/private/export/unknown
    segment: Mapped[str | None] = mapped_column(Text)
    geography: Mapped[str] = mapped_column(String(16))  # domestic / export / unknown
    # Rs crore. When the filing gives only a range (e.g. L&T's "large": 2,500-5,000), value_cr
    # is its midpoint. None when no value is disclosed.
    value_cr: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    value_low_cr: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    value_high_cr: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    value_as_written: Mapped[str | None] = mapped_column(Text)
    value_found: Mapped[bool] = mapped_column(Boolean, default=False)  # as written, in the text
    # The size label the company used instead of a value, e.g. L&T's 'large'. Its range is
    # learned from the company's filings that state it (agents/orders.apply_scales).
    size_class: Mapped[str | None] = mapped_column(String(32))
    execution_months: Mapped[int | None] = mapped_column()
    description: Mapped[str] = mapped_column(Text)
    model: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class OrderBookSnapshot(Base):
    """The order book a company reported for a quarter, with that quarter's order inflow and
    revenue, read from an investor presentation, call transcript or results. One per quarter;
    `tried` lists the documents read so a better one filed later is still tried."""

    __tablename__ = "order_book_snapshots"
    __table_args__ = (UniqueConstraint("isin", "quarter", name="order_book_quarter"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    isin: Mapped[str] = mapped_column(ForeignKey("companies.isin"), index=True)
    quarter: Mapped[str] = mapped_column(String(16))  # 'Q2 FY27'
    period_end: Mapped[date] = mapped_column(Date)
    document_id: Mapped[int | None] = mapped_column(ForeignKey("documents.id", ondelete="SET NULL"))
    order_book_cr: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    inflow_cr: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))  # orders won that quarter
    revenue_cr: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))  # revenue that quarter
    # The figures as written in the document, and whether each was found in its text.
    as_written: Mapped[dict] = mapped_column(JSONB, default=dict)
    note: Mapped[str | None] = mapped_column(Text)
    tried: Mapped[list[int]] = mapped_column(ARRAY(BigInteger), default=list)  # document ids
    model: Mapped[str | None] = mapped_column(String(64))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class ResultFiling(Base):
    """Results Reader: a results filing looked at, so it is read once.

    status: 'read' (its figures are in `results`), 'duplicate' (that period was already read
    from another filing, e.g. the other exchange's copy), 'no_figures' (no results statement
    in it, e.g. a board meeting about something else), 'no_text' (a scanned PDF), 'failed' (the
    model's answer was unusable, e.g. cut off).
    """

    __tablename__ = "result_filings"

    document_id: Mapped[int] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), primary_key=True
    )
    isin: Mapped[str] = mapped_column(ForeignKey("companies.isin"), index=True)
    status: Mapped[str] = mapped_column(String(16))
    period: Mapped[str | None] = mapped_column(String(16))  # 'Q2 FY27', 'H1 FY27'
    note: Mapped[str | None] = mapped_column(Text)
    model: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class QuarterlyResult(Base):
    """A company's reported figures for one period, from its results statement: a quarter
    (3 months), a half year (6 months; SME companies report half-yearly) or a year (12).

    `primary` is true when the period is the filing's own; figures from a comparative column
    (the previous quarter, the same quarter a year ago) fill periods not read directly, and
    give way when that period's own filing is read. Rs crore, converted in code from the
    figures as written and the statement's unit.
    """

    __tablename__ = "results"
    __table_args__ = (UniqueConstraint("isin", "period_end", "months", name="result_period"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    isin: Mapped[str] = mapped_column(ForeignKey("companies.isin"), index=True)
    period: Mapped[str] = mapped_column(String(16))  # 'Q2 FY27', 'H1 FY27', 'FY27'
    period_end: Mapped[date] = mapped_column(Date, index=True)
    months: Mapped[int] = mapped_column()
    basis: Mapped[str] = mapped_column(String(16))  # consolidated / standalone
    document_id: Mapped[int | None] = mapped_column(ForeignKey("documents.id", ondelete="SET NULL"))
    primary: Mapped[bool] = mapped_column(Boolean, default=False)
    revenue_cr: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    other_income_cr: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    finance_costs_cr: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    depreciation_cr: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    pbt_cr: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    pat_cr: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))  # attributable to owners
    eps: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))  # Rs, basic
    unit: Mapped[str] = mapped_column(String(16))  # as the statement gives it: lakh, crore...
    # Each figure as written, and whether it was found in the filing's text.
    as_written: Mapped[dict] = mapped_column(JSONB, default=dict)
    model: Mapped[str] = mapped_column(String(64))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class EventFiling(Base):
    """Event Extractor (agent 7): a filing looked at for events, so it is read once.

    status: 'extracted' (its events are in `events`), 'no_event' (routine, nothing to record),
    'duplicate' (the same announcement on the other exchange), 'failed' (the model's answer was
    unusable).
    """

    __tablename__ = "event_filings"

    document_id: Mapped[int] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), primary_key=True
    )
    isin: Mapped[str] = mapped_column(ForeignKey("companies.isin"), index=True)
    status: Mapped[str] = mapped_column(String(16))
    note: Mapped[str | None] = mapped_column(Text)
    model: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Event(Base):
    """A typed event from a filing: capex, guidance, a management change, a rating action, a
    legal or regulatory matter, an acquisition, a fundraise, a promoter's action, a disruption,
    an agreement or an approval. Each carries the sentence it came from.

    The QA Checker (agent 8) sets `qa_status`: 'pending' (not checked yet), 'passed', 'flagged'
    (a check failed and no second pass settled it), 'failed' (the second pass disagreed) or
    'duplicate' (the same event from an earlier filing). Flagged and failed events wait in the
    review queue; `review` records your decision ('accepted' or 'rejected').
    """

    __tablename__ = "events"

    id: Mapped[int] = mapped_column(primary_key=True)
    isin: Mapped[str] = mapped_column(ForeignKey("companies.isin"), index=True)
    document_id: Mapped[int] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), index=True
    )
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    event_type: Mapped[str] = mapped_column(String(24), index=True)
    headline: Mapped[str] = mapped_column(Text)
    event_date: Mapped[date | None] = mapped_column(Date)  # when it happens or takes effect
    sentiment: Mapped[str] = mapped_column(String(16))  # positive/negative/neutral/mixed
    importance: Mapped[int] = mapped_column()  # 1 (routine) .. 5 (could move the stock)
    # The main amount, in Rs crore (capex, issue size, consideration, penalty...); four
    # decimals, so a penalty of Rs 4,55,000 is 0.0455, not 0.05.
    value_cr: Mapped[Decimal | None] = mapped_column(Numeric(16, 4))
    value_as_written: Mapped[str | None] = mapped_column(Text)
    value_kind: Mapped[str | None] = mapped_column(Text)
    # value_cr divided by the company's revenue for the 12 months before the filing.
    materiality: Mapped[float | None] = mapped_column()
    counterparty: Mapped[str | None] = mapped_column(Text)  # agency, regulator, target...
    person: Mapped[str | None] = mapped_column(Text)
    role: Mapped[str | None] = mapped_column(Text)
    action: Mapped[str | None] = mapped_column(Text)  # appointed, upgraded, pledge created...
    rating_from: Mapped[str | None] = mapped_column(Text)
    rating_to: Mapped[str | None] = mapped_column(Text)
    stake_pct: Mapped[float | None] = mapped_column()
    shares: Mapped[int | None] = mapped_column(BigInteger)  # bought, sold, pledged or issued
    quote: Mapped[str | None] = mapped_column(Text)
    quote_found: Mapped[bool] = mapped_column(Boolean, default=False)
    qa_status: Mapped[str] = mapped_column(
        String(16), default="pending", server_default="pending", index=True
    )
    qa_notes: Mapped[list[str]] = mapped_column(
        ARRAY(Text), default=list, server_default="{}", nullable=False
    )
    duplicate_of: Mapped[int | None] = mapped_column(ForeignKey("events.id", ondelete="SET NULL"))
    qa_model: Mapped[str | None] = mapped_column(String(64))  # the second pass, if any
    review: Mapped[str | None] = mapped_column(String(16))
    review_note: Mapped[str | None] = mapped_column(Text)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    model: Mapped[str] = mapped_column(String(64))
    prompt_version: Mapped[str] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class RedFlag(Base):
    """Red-flag Monitor (agent 15): a governance or balance-sheet warning about a company.

    Raised by rules over the checked events (an auditor or CFO leaving, a rating downgrade, a
    pledge, a penalty...) and over the filings (results not filed by the deadline). `ref` names
    what raised it ('event:123', 'results:Q2 FY27'), so a flag is raised once.
    """

    __tablename__ = "red_flags"
    __table_args__ = (UniqueConstraint("isin", "kind", "ref", name="red_flag_ref"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    isin: Mapped[str] = mapped_column(ForeignKey("companies.isin"), index=True)
    kind: Mapped[str] = mapped_column(String(32), index=True)  # auditor_exit, downgrade...
    severity: Mapped[str] = mapped_column(String(8), index=True)  # high / medium / low
    title: Mapped[str] = mapped_column(Text)
    detail: Mapped[str | None] = mapped_column(Text)
    flagged_on: Mapped[date] = mapped_column(Date, index=True)  # the filing's date, or a deadline
    ref: Mapped[str] = mapped_column(String(64))
    event_id: Mapped[int | None] = mapped_column(ForeignKey("events.id", ondelete="CASCADE"))
    document_id: Mapped[int | None] = mapped_column(ForeignKey("documents.id", ondelete="SET NULL"))
    dismissed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    note: Mapped[str | None] = mapped_column(Text)  # why you dismissed it
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
