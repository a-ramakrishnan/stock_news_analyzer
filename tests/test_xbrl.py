from stock_news_analyzer.sources import xbrl

SAMPLE = b"""<?xml version="1.0" encoding="UTF-8"?>
<xbrli:xbrl xmlns:xbrli="http://www.xbrl.org/2003/instance"
    xmlns:xbrldi="http://xbrl.org/2006/xbrldi"
    xmlns:in-capmkt="http://www.sebi.gov.in/xbrl/2025-03-31/in-capmkt">
  <xbrli:context id="OneD">
    <xbrli:entity><xbrli:identifier scheme="http://www.nseindia.com">LT</xbrli:identifier></xbrli:entity>
    <xbrli:period><xbrli:startDate>2026-04-01</xbrli:startDate><xbrli:endDate>2026-06-30</xbrli:endDate></xbrli:period>
  </xbrli:context>
  <xbrli:context id="OneI">
    <xbrli:entity><xbrli:identifier scheme="http://www.nseindia.com">LT</xbrli:identifier>
      <xbrli:segment><xbrldi:explicitMember dimension="in-capmkt:SegmentsAxis"
        >in-capmkt:Infra</xbrldi:explicitMember></xbrli:segment>
    </xbrli:entity>
    <xbrli:period><xbrli:instant>2026-06-30</xbrli:instant></xbrli:period>
  </xbrli:context>
  <in-capmkt:RevenueFromOperations contextRef="OneD" unitRef="INR" decimals="-5"
    >679420000000</in-capmkt:RevenueFromOperations>
  <in-capmkt:ProfitLossForPeriod contextRef="OneD" unitRef="INR" decimals="-5"
    >41230000000</in-capmkt:ProfitLossForPeriod>
  <in-capmkt:NameOfTheCompany contextRef="OneD"
    >Larsen &amp; Toubro Limited</in-capmkt:NameOfTheCompany>
  <in-capmkt:Empty contextRef="OneD"></in-capmkt:Empty>
</xbrli:xbrl>"""


def test_facts_and_contexts():
    found = xbrl.facts(SAMPLE)
    assert ("RevenueFromOperations", "OneD", "679420000000") in found
    assert ("NameOfTheCompany", "OneD", "Larsen & Toubro Limited") in found
    assert len(found) == 3  # the empty fact is left out
    periods = xbrl.contexts(SAMPLE)
    assert periods["OneD"] == "2026-04-01..2026-06-30"
    assert periods["OneI"] == "2026-06-30 ['in-capmkt:Infra']"
