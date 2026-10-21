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
