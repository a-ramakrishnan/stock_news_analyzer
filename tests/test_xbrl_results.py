from datetime import date
from decimal import Decimal

import pytest
from test_concalls import LT
from test_orchestrator import loaded  # noqa: F401  (fixture)

from stock_news_analyzer.agents import results as rs
from stock_news_analyzer.agents import xbrl_results as xr
from stock_news_analyzer.models import QuarterlyResult


def instance(facts: dict[str, str], context="OneD") -> bytes:
    body = "".join(
        f'<in-capmkt:{tag} contextRef="{context}" unitRef="INR">{v}</in-capmkt:{tag}>'
        for tag, v in facts.items()
    )
    return (
        '<xbrli:xbrl xmlns:xbrli="http://www.xbrl.org/2003/instance" '
        f'xmlns:in-capmkt="http://example/in-capmkt">{body}</xbrli:xbrl>'
    ).encode()


LT_Q3 = instance(
    {
        "RevenueFromOperations": "349842800000.00",
        "OtherIncome": "11973800000.00",
        "FinanceCosts": "5425100000.00",
        "DepreciationDepletionAndAmortisationExpense": "4879600000.00",
        "ProfitBeforeTax": "30614600000.00",
        "ProfitLossForPeriod": "24193800000.00",
        "ProfitOrLossAttributableToOwnersOfParent": "0.00",
        "BasicEarningsLossPerShareFromContinuingAndDiscontinuedOperations": "17.60",
    }
)


def test_figures_by_kind_of_company():
    lt = xr.figures(LT_Q3, bank=False)
    assert lt["revenue"] == (Decimal("34984.28"), "349842800000.00")
    assert lt["pat"][0] == Decimal("2419.38")  # a zero attributable line is passed over
    assert lt["eps"][0] == Decimal("17.60")
    bank = xr.figures(
        instance(
            {
                "Income": "29534400000.00",
                "ProfitLossAfterTaxesMinorityInterestAndShareOfProfitLossOfAssociates": (
                    "4960300000.00"
                ),
                "BasicEarningsPerShareAfterExtraordinaryItems": "6.16",
            }
        ),
        bank=True,
    )
    assert bank["revenue"][0] == Decimal("2953.44") and bank["pat"][0] == Decimal("496.03")
    sme = xr.figures(
        instance(
            {
                "RevenueFromOperations": "1418744000.00",
                "Revenue": "1425098000.00",
                "ProfitLossForThePeriod": "164465000.00",
            }
        ),
        bank=False,
    )
    assert sme["revenue"][0] == Decimal("141.8744") and sme["pat"][0] == Decimal("16.4465")
    year_to_date = xr.figures(instance({"RevenueFromOperations": "1"}, "FourD"), bank=False)
    assert year_to_date == {}


def test_one_filing_per_period_consolidated_first():
    rows = [
        {
            "fromDate": "01-Oct-2024",
            "toDate": "31-Dec-2024",
            "consolidated": "Non-Consolidated",
            "xbrl": "https://x/a.xml",
        },
        {
            "fromDate": "01-Oct-2024",
            "toDate": "31-Dec-2024",
            "consolidated": "Consolidated",
            "xbrl": "https://x/b.xml",
        },
        {
            "fromDate": "01-APR-2024",
            "toDate": "30-SEP-2024",
            "consolidated": "Non-Consolidated",
            "xbrl": "https://x/c.xml",
        },
        {"fromDate": "01-Apr-2010", "toDate": "30-Sep-2010", "xbrl": "https://x/-"},
    ]
    picked = xr.filings(rows, since=date(2024, 1, 1))
    assert [r["xbrl"] for r in picked] == ["https://x/c.xml", "https://x/b.xml"]
    assert [r["months"] for r in picked] == [6, 3] and picked[1]["consolidated"]


@pytest.mark.db
def test_import_replaces_the_pdf_reading_and_skips_next_time(loaded):  # noqa: F811
    loaded.add(
        QuarterlyResult(
            isin=LT,
            period="Q3 FY25",
            period_end=date(2024, 12, 31),
            months=3,
            basis="consolidated",
            primary=True,
            revenue_cr=Decimal("3498428.00"),
            unit="crore",
            as_written={},
            model="claude-haiku-5-5",
        )
    )
    loaded.commit()

    class FakeNSE:
        downloads = 0

        def nse_financial_results(self, symbol, period="Quarterly", index="equities"):
            if symbol != "LT" or period != "Quarterly":
                return []
            return [
                {
                    "fromDate": "01-Oct-2024",
                    "toDate": "31-Dec-2024",
                    "bank": "N",
                    "consolidated": "Non-Consolidated",
                    "xbrl": "https://x/INDAS_1.xml",
                }
            ]

        def nse_integrated_results(self, symbol, index="equities"):
            return []

        def download(self, exchange, urls):
            self.downloads += 1
            return urls[0], LT_Q3, True

    client = FakeNSE()
    result = xr.import_results(loaded, client)
    assert (result.periods, result.corrected, result.errors) == (1, 1, [])
    row = loaded.query(QuarterlyResult).filter_by(isin=LT, period="Q3 FY25").one()
    assert (row.revenue_cr, row.model, row.basis) == (Decimal("34984.28"), "xbrl", "standalone")
    assert row.as_written["revenue"]["source"] == "https://x/INDAS_1.xml"
    assert rs.check_scale(loaded, LT) == 0  # XBRL figures are left alone
    shown = rs.table(loaded, LT)[0]
    assert shown["from_xbrl"] and shown["ebitda_cr"] == pytest.approx(
        3061.46 + 542.51 + 487.96 - 1197.38
    )
    again = xr.import_results(loaded, client)
    assert (again.periods, again.skipped, client.downloads) == (0, 1, 1)


def q4_file() -> bytes:
    """An integrated filing for Q4 FY26: the quarter (OneD) and the year (FourD), with dates."""
    contexts = "".join(
        f'<xbrli:context id="{cid}"><xbrli:period><xbrli:startDate>{s}</xbrli:startDate>'
        f"<xbrli:endDate>2026-03-31</xbrli:endDate></xbrli:period></xbrli:context>"
        for cid, s in (("OneD", "2026-01-01"), ("FourD", "2025-04-01"))
    )
    facts = (
        '<in-capmkt:RevenueFromOperations contextRef="OneD">827620000000'
        "</in-capmkt:RevenueFromOperations>"
        '<in-capmkt:ProfitOrLossAttributableToOwnersOfParent contextRef="OneD">53260000000'
        "</in-capmkt:ProfitOrLossAttributableToOwnersOfParent>"
        '<in-capmkt:RevenueFromOperations contextRef="FourD">2860000000000'
        "</in-capmkt:RevenueFromOperations>"
    )
    return (
        '<xbrli:xbrl xmlns:xbrli="http://www.xbrl.org/2003/instance" '
        f'xmlns:in-capmkt="http://example/in-capmkt">{contexts}{facts}</xbrli:xbrl>'
    ).encode()


@pytest.mark.db
def test_integrated_filings_give_the_quarter_and_the_year(loaded):  # noqa: F811
    class FakeNSE:
        def nse_financial_results(self, symbol, period="Quarterly", index="equities"):
            return []

        def nse_integrated_results(self, symbol, index="equities"):
            if symbol != "LT":
                return []
            return [
                {
                    "type": "Integrated Filing- Governance",
                    "qe_Date": "31-MAR-2026",
                    "xbrl": "https://x/gov.xml",
                },
                {
                    "type": "Integrated Filing- Financials",
                    "qe_Date": "31-MAR-2026",
                    "consolidated": "Standalone",
                    "xbrl": "https://x/standalone.xml",
                },
                {
                    "type": "Integrated Filing- Financials",
                    "qe_Date": "31-MAR-2026",
                    "consolidated": "Consolidated",
                    "xbrl": "https://x/consolidated.xml",
                },
            ]

        def download(self, exchange, urls):
            assert urls == ["https://x/consolidated.xml"]
            return urls[0], q4_file(), True

    result = xr.import_results(loaded, FakeNSE(), since=date(2025, 1, 1))
    assert (result.periods, result.errors) == (2, [])
    rows = {r.months: r for r in rs.periods(loaded, LT)}
    assert rows[3].period == "Q4 FY26" and rows[3].revenue_cr == Decimal("82762.00")
    assert rows[3].pat_cr == Decimal("5326.00") and rows[3].basis == "consolidated"
    assert rows[12].period == "FY26" and rows[12].revenue_cr == Decimal("286000.00")
    again = xr.import_results(loaded, FakeNSE(), since=date(2025, 1, 1))
    assert (again.periods, again.skipped) == (0, 1)


def test_profit_must_fit_eps_times_shares():
    shares = {"PaidUpValueOfEquityShareCapital": "2750000000", "FaceValueOfEquityShareCapital": "2"}
    wrong_owner_line = instance(
        {
            **shares,
            "RevenueFromOperations": "349842800000",
            "ProfitOrLossAttributableToOwnersOfParent": "2248000",  # filed in the wrong unit
            "ProfitLossForPeriod": "24193800000",
            "BasicEarningsLossPerShareFromContinuingAndDiscontinuedOperations": "17.60",
        }
    )
    # 1,375,000,000 shares x Rs 17.60 = Rs 2,420 crore: the period's profit fits, not the line
    assert xr.figures(wrong_owner_line, bank=False)["pat"][0] == Decimal("2419.38")
    nothing_fits = instance(
        {
            **shares,
            "ProfitLossForPeriod": "2248000",
            "BasicEarningsLossPerShareFromContinuingAndDiscontinuedOperations": "17.60",
        }
    )
    assert "pat" not in xr.figures(nothing_fits, bank=False)


@pytest.mark.db
def test_xbrl_fills_only_what_passes_and_half_years_go_back(loaded):  # noqa: F811
    def pdf(end, revenue, pat):
        loaded.add(
            QuarterlyResult(
                isin=LT,
                period=rs.period_label(end, 3),
                period_end=end,
                months=3,
                basis="consolidated",
                primary=True,
                revenue_cr=revenue,
                pat_cr=pat,
                eps=Decimal("10.00"),
                unit="crore",
                as_written={},
                model="claude-haiku-5-5",
            )
        )

    pdf(date(2024, 9, 30), Decimal("52.00"), Decimal("12.00"))
    pdf(date(2024, 12, 31), Decimal("58.00"), Decimal("16.00"))
    pdf(date(2025, 3, 31), Decimal("47.00"), Decimal("11.00"))
    loaded.commit()
    shares = {"PaidUpValueOfEquityShareCapital": "10800000", "FaceValueOfEquityShareCapital": "10"}
    files = {
        # A half year under Q2's label: revenue and EPS about double.
        "https://x/q2.xml": instance(
            {
                **shares,
                "RevenueFromOperations": "956245000",
                "ProfitLossForPeriod": "228000000",
                "BasicEarningsPerShare": "21.17",
            }
        ),
        # Q3 with its profit line in the wrong unit: revenue taken, profit kept from the PDF.
        "https://x/q3.xml": instance(
            {
                **shares,
                "RevenueFromOperations": "576073000",
                "ProfitLossForPeriod": "2248000",
                "BasicEarningsPerShare": "14.77",
            }
        ),
    }

    class FakeNSE:
        def nse_financial_results(self, symbol, period="Quarterly", index="equities"):
            if symbol != "LT" or period != "Quarterly":
                return []
            return [
                {"fromDate": "01-Jul-2024", "toDate": "30-Sep-2024", "xbrl": "https://x/q2.xml"},
                {"fromDate": "01-Oct-2024", "toDate": "31-Dec-2024", "xbrl": "https://x/q3.xml"},
            ]

        def nse_integrated_results(self, symbol, index="equities"):
            return []

        def download(self, exchange, urls):
            return urls[0], files[urls[0]], True

    result = xr.import_results(loaded, FakeNSE(), since=date(2024, 1, 1))
    assert result.rejected == 1
    rows = {r.period: r for r in rs.periods(loaded, LT, 3)}
    q2, q3 = rows["Q2 FY25"], rows["Q3 FY25"]
    assert (q2.revenue_cr, q2.eps, q2.model) == (
        Decimal("52.00"),
        Decimal("10.00"),
        "xbrl-rejected",
    )
    assert q3.revenue_cr == Decimal("57.61") and q3.model == "xbrl"
    assert q3.pat_cr == Decimal("16.00")  # the PDF's profit: XBRL's didn't fit EPS x shares
    assert q3.as_written["revenue"]["before"] == "58.00"
    again = xr.import_results(loaded, FakeNSE(), since=date(2024, 1, 1))
    assert (again.periods, again.skipped) == (0, 2)
