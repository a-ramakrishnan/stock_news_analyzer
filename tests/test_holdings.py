from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest
from test_concalls import LT
from test_orchestrator import loaded  # noqa: F401  (fixture)
from test_orders import KVB

from stock_news_analyzer.agents import digest as dg
from stock_news_analyzer.agents import holdings, redflags
from stock_news_analyzer.models import RedFlag, Shareholding
from stock_news_analyzer.sources import shareholding as shp
from stock_news_analyzer.sources.announcements import IST
from stock_news_analyzer.ui import queries

TOTAL = 1_000_000


def xbrl(end: date, cats: dict[str, int], pledged: float | None = None, scale: float = 1) -> bytes:
    """A shareholding-pattern file like NSE's: one context per category member, plus a
    shareholder's context (a typed member) that must be left out. Percentages as fractions,
    or as percent with scale=100 (files before 2025)."""
    contexts, facts = [], []
    for i, (member, shares) in enumerate({**cats, "ShareholdingPattern": TOTAL}.items()):
        contexts.append(
            f'<xbrli:context id="c{i}"><xbrli:entity><xbrli:segment>'
            f'<xbrldi:explicitMember dimension="in-bse-shp:CategoryAxis">'
            f"in-bse-shp:{member}Member</xbrldi:explicitMember></xbrli:segment></xbrli:entity>"
            f"<xbrli:period><xbrli:instant>{end}</xbrli:instant></xbrli:period></xbrli:context>"
        )
        facts += [
            f'<in-bse-shp:NumberOfShares contextRef="c{i}" decimals="0">{shares}'
            "</in-bse-shp:NumberOfShares>",
            f'<in-bse-shp:ShareholdingAsAPercentageOfTotalNumberOfShares contextRef="c{i}" '
            f'decimals="4">{shares / TOTAL * scale:.4f}'
            "</in-bse-shp:ShareholdingAsAPercentageOfTotalNumberOfShares>",
            f'<in-bse-shp:NumberOfShareholders contextRef="c{i}" decimals="0">{shares // 100}'
            "</in-bse-shp:NumberOfShareholders>",
        ]
        if member == shp.PROMOTER and pledged is not None:
            facts.append(
                f'<in-bse-shp:EncumberedSharesAsAPercentageOfTotalSharesHeld contextRef="c{i}">'
                f"{pledged * scale:.4f}</in-bse-shp:EncumberedSharesAsAPercentageOfTotalSharesHeld>"
            )
    contexts.append(
        '<xbrli:context id="named"><xbrli:entity><xbrli:segment>'
        '<xbrldi:explicitMember dimension="in-bse-shp:CategoryAxis">'
        "in-bse-shp:MutualFundsOrUTIMember</xbrldi:explicitMember>"
        '<xbrldi:typedMember dimension="in-bse-shp:NameAxis"><x>1</x></xbrldi:typedMember>'
        "</xbrli:segment></xbrli:entity><xbrli:period><xbrli:instant>"
        f"{end}</xbrli:instant></xbrli:period></xbrli:context>"
    )
    facts.append('<in-bse-shp:NumberOfShares contextRef="named">999</in-bse-shp:NumberOfShares>')
    facts.append(f'<in-bse-shp:DateOfReport contextRef="d">{end}</in-bse-shp:DateOfReport>')
    return (
        '<?xml version="1.0"?><xbrli:xbrl xmlns:xbrli="http://www.xbrl.org/2003/instance" '
        'xmlns:xbrldi="http://xbrl.org/2006/xbrldi" '
        'xmlns:in-bse-shp="http://www.bseindia.com/xbrl/shp">'
        + "".join(contexts)
        + "".join(facts)
        + "</xbrli:xbrl>"
    ).encode()


def cats(promoter: int, fii: int, mf: int, retail: int) -> dict[str, int]:
    return {
        shp.PROMOTER: promoter,
        "PublicShareholding": TOTAL - promoter,
        "InstitutionsForeign": fii,
        "InstitutionsDomestic": mf + 50_000,
        "MutualFundsOrUTI": mf,
        "InsuranceCompanies": 50_000,
        "ResidentIndividualShareholdersHoldingNominalShareCapitalUpToRsTwoLakh": retail,
    }


class FakeNSE:
    """Serves a listing per symbol and the files it links to."""

    def __init__(self, listings: dict[str, list[dict]], files: dict[str, bytes]):
        self.listings, self.files, self.downloads = listings, files, []

    def nse_shareholdings(self, symbol, index="equities"):
        return self.listings.get(symbol, [])

    def download(self, exchange, urls):
        self.downloads.append(urls[0])
        return urls[0], self.files[urls[0]], True


def row(end: date, record: int, filed: date, promoter="58.27") -> dict:
    return {
        "date": end.strftime("%d-%b-%Y").upper(),
        "broadcastDate": filed.strftime("%d-%b-%Y").upper() + " 10:11:10",
        "recordId": record,
        "xbrl": f"https://nsearchives.nseindia.com/corporate/xbrl/SHP_{record}_WEB.xml",
        "pr_and_prgrp": promoter,
    }


def test_parse_reads_categories_and_leaves_out_named_holders():
    p = shp.parse(xbrl(date(2026, 9, 30), cats(600_000, 100_000, 150_000, 120_000), 0.25))
    assert p.quarter_end == date(2026, 9, 30)
    assert p.pct(shp.PROMOTER) == Decimal("60.0000") and p.shares(shp.TOTAL) == TOTAL
    assert p.shares("MutualFundsOrUTI") == 150_000  # not the named holder's 999
    assert p.pledged_pct == Decimal("25.0000")
    assert p.categories[shp.TOTAL]["holders"] == TOTAL // 100


def test_older_files_write_percent_not_fractions():
    c = cats(600_000, 100_000, 150_000, 120_000)
    new = shp.parse(xbrl(date(2026, 9, 30), c, 0.25))
    old = shp.parse(xbrl(date(2023, 9, 30), c, 0.25, scale=100))
    assert old.categories == new.categories and old.pledged_pct == Decimal("25.0000")
    with pytest.raises(ValueError):
        shp.parse(xbrl(date(2023, 9, 30), c, 0.25, scale=10_000))  # misread: refused


def test_listing_keeps_the_latest_filing_per_quarter():
    q3, q2 = date(2026, 9, 30), date(2026, 6, 30)
    rows = [
        row(q3, 3, date(2026, 10, 17)),
        row(q3, 4, date(2026, 10, 20)),  # revised
        row(q2, 2, date(2026, 7, 16)),
        row(date(2020, 3, 31), 1, date(2020, 4, 15)),
        {**row(date(2026, 3, 31), 9, date(2026, 4, 15)), "xbrl": "-"},
        row(date(2025, 11, 20), 8, date(2025, 11, 25)),  # filed for a share issue
    ]
    found = holdings.filings(rows, date(2025, 1, 1))
    assert [(f["end"], f["record_id"]) for f in found] == [(q2, "2"), (q3, "4")]


@pytest.fixture
def stored(loaded):  # noqa: F811
    """Three quarters of LT (promoters sell 3 points, then pledge 25% of their shares) and
    two of KVB (promoter stake diluted by new shares, not sold)."""
    today = datetime.now(IST).date()
    ends = [d for d in (today - timedelta(days=n) for n in range(400)) if holdings.quarter_end(d)]
    q = sorted(ends[:3])  # the last three quarter ends
    files = {}
    listings = {"LT": [], "KARURVYSYA": []}
    lt = [
        (cats(600_000, 100_000, 150_000, 120_000), None),
        (cats(570_000, 110_000, 165_000, 120_000), None),
        (cats(570_000, 110_000, 165_000, 120_000), 0.25),
    ]
    for i, (c, pledged) in enumerate(lt):
        r = row(q[i], 100 + i, min(q[i] + timedelta(days=15), today))
        files[r["xbrl"]] = xbrl(q[i], c, pledged)
        listings["LT"].append(r)
    for i, promoter in enumerate((500_000, 480_000)):
        r = row(q[i + 1], 200 + i, min(q[i + 1] + timedelta(days=15), today))
        c = cats(promoter, 50_000, 10_000, 300_000)
        files[r["xbrl"]] = xbrl(q[i + 1], c)
        listings["KARURVYSYA"].append(r)
    client = FakeNSE(listings, files)
    result = holdings.import_holdings(loaded, client, since=today - timedelta(days=400))
    assert (result.filings, result.errors) == (5, [])
    # KVB's promoter shares stayed the same: the 2-point fall is dilution.
    kvb = holdings.history(loaded, KVB)[0]
    kvb.promoter_shares = holdings.history(loaded, KVB)[1].promoter_shares
    loaded.commit()
    return loaded, client


@pytest.mark.db
def test_import_stores_quarters_once(stored):
    session, client = stored
    latest = holdings.history(session, LT)[0]
    assert latest.promoter_pct == Decimal("57.0000") and latest.mf_pct == Decimal("16.5000")
    assert latest.fii_pct == Decimal("11.0000") and latest.pledged_pct == Decimal("25.0000")
    assert latest.insurance_pct == Decimal("5.0000") and latest.shareholders == TOTAL // 100
    again = holdings.import_holdings(session, client, since=date(2025, 1, 1))
    assert (again.filings, again.skipped) == (0, 5)
    # A file that can't be read is reported; the other companies' filings still come in.
    end = date(2020, 3, 31)
    bad, good = row(end, 900, end), row(end, 901, end)
    client.listings["LT"].append(bad)
    client.listings["KARURVYSYA"].append(good)
    client.files[bad["xbrl"]] = xbrl(end, cats(1, 1, 1, 1), scale=10_000)
    client.files[good["xbrl"]] = xbrl(end, cats(500_000, 50_000, 10_000, 300_000))
    third = holdings.import_holdings(session, client, since=date(2020, 1, 1))
    assert third.filings == 1 and len(third.errors) == 1 and "LT 2020-03-31" in third.errors[0]
    assert session.query(Shareholding).count() == 6


@pytest.mark.db
def test_red_flags_for_selling_and_pledges_not_dilution(stored):
    session, _ = stored
    result = redflags.scan(session)
    found = {(f.isin, f.kind, f.severity) for f in session.query(RedFlag)}
    assert (LT, "promoter_selling", "medium") in found  # 3 points sold
    assert (LT, "pledge_rising", "medium") in found  # 25% of promoter shares
    assert not any(isin == KVB for isin, _, _ in found)  # diluted, not sold
    assert result.raised == 2 and redflags.scan(session).raised == 0


@pytest.mark.db
def test_flags_with_the_same_ref_for_two_companies(stored):
    session, _ = stored
    kvb = holdings.history(session, KVB)[0]
    kvb.promoter_shares -= 30_000  # now KVB's promoters sold too, in the same quarter as LT's
    session.commit()
    redflags.scan(session)
    assert {f.isin for f in session.query(RedFlag).filter_by(kind="promoter_selling")} == {
        LT,
        KVB,
    }


@pytest.mark.db
def test_moves_digest_and_dashboard(stored):
    session, _ = stored
    found = holdings.moves(session)
    lt = next(m for m in found if m["symbol"] == "LT")
    assert holdings.describe(lt).endswith("pledged 25.0% of promoter shares (+25.0)")
    since = datetime.now(IST) - timedelta(days=150)
    text = dg.build_digest(session, since, datetime.now(IST)).markdown
    assert "## Shareholding" in text and "promoters 57.0% (-3.0)" in text
    df = queries.shareholding(session, LT)
    assert list(df["promoter"]) == [60.0, 57.0, 57.0] and df["pledged"].iloc[-1] == 25.0


@pytest.mark.db
def test_a_sale_flagged_from_its_filing_is_not_flagged_again(stored):
    from test_themes import event

    session, _ = stored
    redflags.scan(session)
    ref = next(f.ref for f in session.query(RedFlag).filter_by(isin=LT, kind="promoter_selling"))
    # The promoters' own disclosure of 25,000 of the 30,000 shares sold that quarter.
    newer, older = holdings.history(session, LT)[1:3]
    when = datetime.combine(older.quarter_end + timedelta(days=10), datetime.min.time(), IST)
    sale = event(session, LT, when, "Promoter sold shares", event_type="promoter_action")
    sale.shares = 25_000
    session.add(
        RedFlag(
            isin=LT,
            kind="promoter_selling",
            severity="medium",
            title="LT: promoter sold 25,000 shares",
            flagged_on=when.date(),
            ref=f"test:{sale.id}",
            event_id=sale.id,
        )
    )
    session.commit()
    assert newer.quarter_end > when.date()
    result = redflags.scan(session)
    assert result.removed == 1
    assert session.query(RedFlag).filter_by(isin=LT, ref=ref).count() == 0
