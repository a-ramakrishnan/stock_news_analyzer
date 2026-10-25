# Step 13: Promise Ledger

**Goal:** settle each promise once its date has passed. Was it kept, kept late, partly kept or missed? Then turn the answers into a credibility score per company.

Step 12 recorded promises and let later calls update them. On the first real run, Gravita's 34 promises came back with 11 delayed and only 4 kept. But a call only updates what management chooses to mention. The results and filings after the due date are what show whether it happened.

## What was added

| Piece | Why |
| --- | --- |
| `promise_checks` table (migration 0013) | Every check: verdict, one-sentence finding, the documents cited, and the promise's status before the check, so a reset can put it back |
| `agents/promises.py` | Finds unsettled promises past their date and gathers the company's later documents. Asks Sonnet for a verdict per promise, one call per company. Computes credibility |
| `promises` job, 07:40 daily | After new calls are read at 07:30, before the digest |
| `sna promises check/list/scores/reset`, `make promises` | Check, see the ledger, see the scores, start over |
| Digest | A "Promises" section: what was settled, and what falls due in the next 30 days |
| Stock page | "Promises kept" score on the Earnings calls tab, and how each promise was checked |

## What counts as evidence

- **Documents included,** from 45 days before the promise's due date onwards:
  - results and investor presentations (the first 6,000 and 12,000 characters)
  - other filings whose titles mention commissioning, commercial production, capacity, a plant, expansion, acquisition, a launch, approval, consent, an order, an update or a press release
  - summaries and key points of later earnings calls
- **Not included:** news. Papers repeat what companies say, and news arrives hourly. If news counted as new evidence, every overdue promise would be re-checked, and paid for, every day.
- **Copies:** the same file filed on BSE and NSE is included once.
- **No evidence yet:** a promise answered "no evidence" (for example, the results for its period aren't out) is checked again only when a newer document arrives.

## The score

The score uses settled promises, plus promises long past due:

| Status | Points |
| --- | --- |
| kept | 1 |
| kept late | 0.5 |
| partly kept | 0.5 |
| missed | 0 |
| dropped (a later call abandoned it) | 0 |
| still open or delayed 75 days after its due date | 0 |

The score is the average. It isn't shown until 3 promises count, and it's computed when shown, not stored, so it always reflects the latest checks.

## How to check it

```bash
git pull
uv sync
make migrate
uv run sna promises check
uv run sna promises scores
uv run sna promises list GRAVITA
make ui
```

Cost: one call per company with promises past their date, about $0.05 each. Later runs only check promises with new documents, which costs cents.

## Tweet draft

> Agent #12: the Promise Ledger. Every promise from every earnings call gets a due date. When the date passes, an agent reads the results and filings that came after and marks it kept, late, partly kept or missed, citing the document. The result is a credibility score per management team, built from what they actually reported. #BuildInPublic
