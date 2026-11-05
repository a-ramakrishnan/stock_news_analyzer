# Step 33: Evals, starting with the Event Extractor

**Goal:** measure an agent on fixed cases with checked answers, so changes to prompts or models are judged by a number. The clean install test on Mac and Windows moves to step 34.

- **`sna eval events sample`:** freezes filings from your database into cases (`evals/events/cases/*.yaml`): 25 the agent found events in, spread over the event types with the ones you rejected first, and 15 it found none in. A seed makes the sample repeatable; sampling again adds new filings only.
- **`sna eval events draft`:** Opus drafts each expected answer with the agent's own instructions. It is a stronger model than the one tested, so the answers aren't Haiku's own mistakes. You check each one and set `verified: true`.
- **`sna eval events run`:** calls the agent's real entry point (`events._ask`, one filing per call) on every case, 3 runs each by default, and grades by code: correct (the headline), detect, types F1, amounts, quotes found; plus recall, precision, specificity, cost and latency.
  - Rows are written as they finish and a rerun resumes.
  - Failed calls go to `errors.jsonl` with a class (timeout, refusal, bad answer, API error, model mismatch), not scored as wrong.
  - The served model is checked against the one asked for, and the client's timeout caps each call.
  - The runner and grader are digested, so a changed harness needs your `--approve-harness`.
  - `--mode oracle` and `--mode null` check the grader for free.
- **The LLM wrapper** keeps its last structured call (usage, served model, stop reason) for the eval.

### Checked

The grader is tested on a right reading, a routine filing, a missed event, a wrong type, a lakh-for-crore amount, an amount within 1%, a made-up quote, a quote without its figure, and two events of a kind with one found. Sampling covers strata, rejected filings first, the frozen filing giving the agent the same text as the stored one, and adding without repeats. Drafting is tested with a fake Opus. A run with a fake model covers grading, an answer cut off recorded as an error, the summary's recall, precision and specificity, the harness gate and resuming. Oracle scores 100% and null scores the routine share. 402 tests pass.

Not run here: the real sample, drafts and baseline (they need your database and key). See docs/evals.md.
