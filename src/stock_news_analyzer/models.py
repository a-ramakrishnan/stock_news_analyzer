"""Database tables. Each step adds the tables its agents need; migrations live in `migrations/`."""

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Numeric,
    String,
    Text,
    func,
)
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
