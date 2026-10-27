# Step 18: Red-flag Monitor

**Goal:** warn early about governance and balance-sheet risk in the companies you own or watch: an auditor or CFO leaving, a rating cut, a promoter's pledge, a penalty or tax demand, results not filed on time.

## What was added

| Piece | Why |
| --- | --- |
| `red_flags` table (migration 0019) | Each flag: company, kind, severity, title, the event or deadline behind it, and whether you dismissed it |
| `agents/redflags.py` (agent 15) | Rules over the checked events, and a check on results deadlines |
| `flags` job, 07:55 daily | New flags before the 08:00 digest |
| `sna flags run/list/dismiss`, `make flags` | Raise, see, dismiss |
| Digest | A "Red flags" section first: high and medium flags about recent filings |
| Dashboard | Red flags on the Today page (last 30 days) and above the Stock page's **Events** tab (last year) |

## The rules

| Flag | Severity |
| --- | --- |
| Statutory auditor resigns or is removed | high; an internal or secretarial auditor: medium |
| CEO, MD or CFO resigns or retires early | high; ceases otherwise (a redesignation, say): medium |
| Independent director resigns mid-term | medium; at the end of a term: none |
| Rating downgrade | high; negative outlook or watch: medium |
| Promoter pledge invoked | high; created or increased: medium; released: none |
| Promoter or large holder sells 1% or more | medium |
| Penalty, tax demand, court or regulator's order | by its amount against a year's revenue: 1% or more high, 0.1% or more medium, smaller low; without an amount, by importance; any SEBI order at least medium; a mixed outcome at most medium |
| Disruption | high at importance 4-5, else medium |
| Results not filed by the deadline | medium; 30 days late: high |

Results deadlines follow SEBI's LODR Regulation 33: 45 days after a quarter or half year, 60 after the year. A company is checked against the period after its latest one read, and the flag clears itself if any results filing has come in since that period ended, even one the Results Reader hasn't read yet.

## Choices

- **No LLM.** The design had Sonnet score severity. The events already carry a type, the people and roles, the amount against revenue, sentiment and importance, all checked by the QA Checker, so the severity follows from rules. It costs nothing to run and every flag can be traced to its event.
- **Only checked events.** Events that failed QA, that you rejected, or that repeat an earlier filing's raise nothing.
- **Once per event.** Each flag carries a reference (`event:123`, `results:Q2 FY27`), so the daily scan raises only new ones.
- **History stays out of the digest.** The first scan raises flags for a year of events; the digest lists only those about filings from the last 14 days. `sna flags list` shows the rest.
- **Dismiss, don't delete.** A dismissed flag keeps your note, as a record of what was known and decided.

## Not yet

- Rising promoter pledges from the quarterly shareholding pattern (only pledges announced in filings are seen), large related-party transactions, and alerts sent the same hour (they wait for the Telegram step).

## On the Mac

```
git checkout main
git pull
uv run sna db upgrade
uv run sna flags run
uv run sna flags list
make scheduler
```

## Next

Telegram delivery for the digest and high-severity flags, or the Bullion Analyst.
