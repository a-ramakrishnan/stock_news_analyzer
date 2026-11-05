# Evals

An eval measures one AI agent on a fixed set of cases with checked answers, so a change (a new prompt, a different model) can be judged by a number instead of a feeling. One agent per eval; the first is the Event Extractor.

## The Event Extractor (`sna eval events`)

**What it measures:** given one filing, does the agent (agents/events.py, Haiku) find the events it announces, of the right types and amounts, with quotes that are really in the filing? It grades the agent's raw answer, before the QA Checker corrects or rejects anything, so it measures the extractor alone.

**Cases** are YAML files in `evals/events/cases/`, one per filing: the filing as the agent reads it (title, subject, text, frozen from your database so the eval doesn't change when the database does) and the expected events (type, amount in Rs crore, the amount as written, a headline to read). Exchange filings are public, so the cases live in the repo.

| Score | What it means |
| --- | --- |
| **Correct** (the headline) | An event when there should be one and none when there shouldn't; the same event types; every expected amount right within 1% |
| Detect | An event found when there is one, none when there isn't |
| Types F1 | The event types found against those expected (1 when both are none) |
| Amounts | Share of expected events whose amount, or its absence, is right |
| Quotes found | Share of the events found whose quote is in the filing and holds the amount |

The summary also gives recall (filings with events in which it found one), precision (filings it found events in that have them) and specificity (routine filings it left alone), the cost and the latency.

**Noise:** 40 cases × 3 runs gives Correct to about ±9 points (95%). A change smaller than that may be chance.

## Running it

```
uv run sna eval events sample        # freeze 40 filings from your database (25 with events, 15 without)
uv run sna eval events draft         # Opus drafts each expected answer (about $0.30 in all)
uv run sna eval events show          # the cases as a table (also evals/events/cases.md)
```

Then open each file in `evals/events/cases/`, correct its `expected:` events and set `verified: true`. The answers are what the score is measured against, so they're yours to check. Then:

```
uv run sna eval events run --mode oracle --unverified    # the answers themselves: must score 100%
uv run sna eval events run --mode null --unverified      # no events at all: scores only the routine filings
uv run sna eval events run --case doc123 --case doc456 --unverified --variant baseline --reps 1 --approve-harness
uv run sna eval events run                               # all cases, 3 runs each, the agent's own model
```

The first real run needs `--approve-harness`, after you've read the runner and grader (src/stock_news_analyzer/evals/events.py). If they change later, the run refuses until you approve again, so a score can't silently change meaning.

Results go to `.claude/hillclimb/events/<variant>/`:
- `summary.md`: the scores and the cases it got wrong
- `results.jsonl`: one row per case and run
- `traces/`: what the agent saw and said
- `errors.jsonl`: failed calls, which are kept apart from wrong answers

Each row is written as it finishes; rerunning resumes where it stopped. `--variant v1 --model claude-sonnet-5-5` measures a change next to the baseline.
