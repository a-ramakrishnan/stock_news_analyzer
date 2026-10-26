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
    assert xr._months(picked[0]["_start"], picked[0]["_end"]) == 6


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
