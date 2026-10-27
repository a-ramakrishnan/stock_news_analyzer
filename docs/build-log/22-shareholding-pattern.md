# Step 22: Shareholding pattern

**Goal:** see who owns each company and how that changes each quarter: promoters, foreign and domestic institutions, mutual funds and retail investors, and how much of the promoters' stake is pledged.

## What was added

| Piece | Why |
| --- | --- |
| `sna holdings probe` | Checked NSE's data on the Mac first, since the build sandbox can't reach NSE |
| `shareholdings` table (migration 0024) | One row per company and quarter, with the main stakes in columns and every category in `categories` |
| `sources/shareholding.py` | Reads the XBRL file |
| `agents/holdings.py` (part of agent 4, Market Signals) | Imports filings, works out moves and raises red flags |
| `holdings` job, 07:10 daily | Before the red flags and the digest |
| `sna holdings run/show/moves`, `make holdings` | Read, see a stock, see what moved |
| Red-flag Monitor | Promoters selling and pledges rising |
| Digest | A "Shareholding" section |
| Dashboard | A **Shareholding** tab on the Stock page |

## What the probe showed

- **The listing:** NSE's `corporate-share-holdings-master` API has one row per quarter, with the quarter end, the time of filing, a record id and a link to the XBRL file. L&T has 22 quarters and Sathlokhar 9. SME stocks answer the same way under `index=sme`.
- **The file:** each holder category is a dimension member: `ShareholdingOfPromoterAndPromoterGroupMember`, `MutualFundsOrUTIMember`, `InstitutionsForeignMember`, `ShareholdingPatternMember` (the total) and so on.
  - Facts include `NumberOfShares`, `ShareholdingAsAPercentageOfTotalNumberOfShares` (a fraction: 0.1939 is 19.39%) and `NumberOfShareholders`.
  - Contexts that also name a single shareholder, for the lists of large holders, are left out.
- **No promoters:** L&T has none, so its file has no promoter member at all, and the listing says `pr_and_prgrp=0`. That is stored as 0%.

## First run

The first run on the Mac stopped at a 2023 filing with a promoter stake of 5,117%. Files from 2025 on write percentages as fractions (0.5117), but older ones write percent (51.17). The parser now reads the scale from each file's total category, 1 or 100, and refuses any percentage outside 0–100. A file that fails is reported and skipped; until now one bad file stopped the whole run.

The second run read 189 quarters for the 15 stocks. Sathlokhar's promoters went 62.71% → 58.27% (Nov 2025) → 62.71% (Dec 2025) → 58.27% (Mar 2026) while holding the same 15.1 million shares. The November pattern was filed for a share issue and already counted the new shares; the December quarterly one did not yet. Patterns filed for an event on a date other than a quarter end are now left out, and any already stored are removed with their flags.

After that, 168 quarters remained and three flags were raised:
- **Shaily:** promoters went from 19.94 million to 18.90 million shares in the June quarter, 2.3% of the company. No filing had flagged it, so it is new.
- **BlackBuck:** promoters went from 49.1 million to 45.5 million shares in the December quarter. The founder's sale of 20 lakh shares had been flagged from its filing; the other 16 lakh had not.
- **KMEW:** a 2.07-point fall. This was the 19 June open-market sale of 5.1 lakh shares, already flagged from its filing.

To avoid the repeat, a quarter's fall in promoter shares that sales already flagged from filings account for (80% or more) raises nothing more, and such a flag already raised is removed. KMEW's goes; Shaily's and BlackBuck's stay.

After the fix, `sna flags run` removed KMEW's repeat flag. Two flags from the shareholding pattern remain, each telling something the filings did not: Shaily's promoter sale of 2.3% and BlackBuck's 16 lakh shares beyond the founder's disclosed sale. Thirteen flags are open in all: six high, seven medium.

## Red flags

- **Promoters selling:** only when the promoters hold fewer shares than the quarter before. A stake that falls because new shares were issued, such as a QIP or a merger, is dilution and raises nothing.
  - Severity by the fall in stake: 5 points or more is high, 2 or more medium, 1 or more low.
- **Pledges:** the pledged or encumbered share of the promoters' holding must have risen by 2 points or more.
  - Severity by the level it reached: 50% of their shares is high, 20% medium, less low.
  - The XBRL tag for encumbered shares wasn't in the probe output, because neither probed company has pledges. The parser takes any promoter figure tagged "pledge" or "encumber" and uses the largest, which is the total.

While wiring this in, I found the Red-flag Monitor matched existing flags by reference alone. Two companies with the same overdue quarter ("results:Q2 FY27") would get only one flag. It now matches by company and reference.

## Tests

`tests/test_holdings.py` uses XBRL files shaped like NSE's and covers:
- the categories read, with named holders left out
- one filing per quarter when a filing was revised
- import and skip on a second run
- selling flagged, dilution not
- a pledge rise flagged
- two companies with the same flag reference
- the digest section and the dashboard query

## On the Mac

```
git checkout main
git pull
uv run sna db upgrade
uv run sna holdings run
uv run sna holdings moves
uv run sna holdings show SSEGL
uv run sna flags run
```

## Next

Email delivery of the digest and high-severity red flags is the one large piece left. It waits while other work comes first. Smaller Market Signals pieces remain: NSE's structured SAST data, monthly mutual fund portfolios and tenders.
