# Step 17: Event Extractor and QA Checker

**Goal:** turn the rest of each watchlist company's filings into typed events with numbers, and check every event before it is shown. Results, order wins and earnings calls already had their own agents; capex, ratings, management changes, legal matters, deals, fundraises and promoters' actions were only titles in the filings list.

## What was added

| Piece | Why |
| --- | --- |
| `events`, `event_filings` tables (migration 0017) | Each event with its fields, quote, QA status and your review; each filing read and its outcome |
| `agents/events.py` (agent 7) | Picks the filings that may announce an event, downloads their PDFs, reads them (Haiku) and stores the events |
| `agents/qa.py` (agent 8) | Code checks on every event, a second pass (Sonnet) on flagged and important ones, the review queue |
| Filings Collector | The PDFs of filings whose title names an event are now downloaded under the `important` policy too |
| `events` job, 07:25 daily | New events before the digest |
| `sna events run/list/show/review/accept/reject/coverage/reset`, `make events` | Read, browse, decide, see what was found per stock, start over |
| Digest | An "Events" section: importance 3 and up, flagged ones marked *unchecked* |
| Stock page | An **Events** tab: type, importance, sentiment, amount and share of revenue, QA status, the quote and a link to the filing |

## Which filings are read

- **Types:** `other`, `board_meeting`, `credit_rating` and `insider_trading` (SAST and pledge disclosures). Results, order wins and call material are left to their agents.
- **By title:** a filing is read when its title or subject names an event (capacity, appointment, rating, penalty, acquisition, QIP, pledge, fire, agreement, approval and so on) and isn't routine (trading window, certificates, newspaper copies, record dates). Every credit rating filing is read. Most filings never reach the model.
- **PDFs:** only some filing types had their PDF downloaded, so NSE's generic titles ("has informed the Exchange about Credit Rating") were all there was. The run downloads the missing PDFs first, up to 300 a run; a PDF that can't be fetched is read from its title.
- **Copies:** the same announcement on BSE and NSE is read once, as for orders.

## How an event is recorded

Haiku reads six filings per call and lists each filing's events: often one, sometimes none (a routine filing that got past the title filter), sometimes two (a director resigning and another appointed). Each event has:

- type, headline, date, sentiment and importance (1-5)
- the main amount in Rs crore, and as written ("Rs. 450 crore"), with what it is (capex, issue size, penalty)
- the parties: rating agency, regulator, target or partner; the person and role; what happened
- old and new rating, stake percentage
- the sentence it came from, copied from the filing

## How it is checked

**In code, every event:**

1. **Quote:** the sentence is in the filing (ignoring case, spacing and punctuation).
2. **Amount:** the number as written is in the filing, decimal point included.
3. **Unit:** the code converts the amount as written ("Rs 75 lakh" is Rs 0.75 crore, "INR 1,200 million" Rs 120 crore) and replaces the model's figure when it differs: the model's arithmetic is never trusted.
4. **Plausibility:** the amount ÷ the company's revenue for the 12 months before the filing (from Results) is stored as materiality and flagged above 1. A rating's amount is the debt rated, so ratings get none.
5. **Fields:** a rating action needs its agency and new rating; a management change its person, role and action; an acquisition its counterparty.
6. **Date and stake:** a date more than two years before the filing (or five after) is dropped, and so is a stake that isn't a percentage.
7. **Repeats:** the same event from an earlier filing within 30 days (an intimation and its outcome, a resignation and the cessation) is marked a repeat and hidden.

**Second pass, Sonnet:** events with a flag, and every event of importance 4 or 5. It answers whether the filing is about this company, whether the event is real, whether the type and the amount are right. It may correct the type, and the amount when the right one is written in the filing. If the filing isn't about the company, the event isn't real, or the amount is wrong with no right one in the filing, the event fails.

**QA status:** `passed`, `flagged` (a check failed and no second pass settled it, e.g. the budget ran out), `failed`, or `duplicate`. Flagged and failed events wait in `sna events review`; `accept` or `reject` records your decision and a note, kept with the event as training data. Flagged events are shown, marked unchecked; failed and rejected ones are hidden.

## Choices

- **Haiku to read, Sonnet to check:** reading a short letter into a schema is a reading task. Checking every event with Sonnet would cost about ten times as much, so it checks only those that matter or look wrong.
- **Code first:** the checks that need no model (the quote, the number, the unit) run on every event, so the second pass is needed only where they find something.
- **No separate review table:** the queue is the flagged and failed events; the decision is stored on the event itself.
- **Materiality against trailing revenue:** the order agent's idea applied to every amount; a Rs 450 crore plant means more to a Rs 4,000 crore company than to L&T.

## Cost

About $0.0005 a filing with Haiku and $0.005 an event checked by Sonnet. The first run reads 400 days of filings and shows its estimate before it starts.

## On the Mac

```
git checkout main
git pull
uv run sna db upgrade
uv run sna events run
uv run sna events coverage
uv run sna events list
uv run sna events review
make scheduler
```

## Next

The Red-flag Monitor (agent 15), built on the events: auditor exits, pledges, penalties and downgrades as their own alerts. Events can also become evidence for the Move Explainer.
