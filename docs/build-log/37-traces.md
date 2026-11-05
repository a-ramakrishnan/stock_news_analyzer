# Step 37: Traces of every AI call

**Goal:** see exactly what each agent was sent and what it answered, like LangSmith's traces, and turn a call it got wrong into an eval case.

- **Every call traced** (migration 0033). The LLM wrapper records a trace after each structured or conversational call, failed ones included:
  - the instructions, stored once per distinct text in `llm_prompts`
  - the prompt, or the conversation as JSON
  - the answer, as JSON
  - the stop reason, the model that served it, and how long it took
  - the filings it was about (`document:ID`, from the prompt)

  A trace that can't be stored never stops the call.
- **Traces page** (Agents group):
  - calls newest first with task, model, tokens, cost, seconds and outcome
  - filters by task, days, words in the prompt, and failed only
  - a selected call shows its instructions, what it was sent beside what it answered, why it stopped and what it cost
  - a call about filings offers to add each to the Event Extractor's eval
- **Commands:** `sna llm traces [--task] [--days] [--failed]`, `sna llm trace ID`, `sna llm prune`.
- **Kept** `llm_trace_days` (30 by default; Settings; 0 turns tracing off). Older traces and unused instructions are pruned each morning with the digest. The calls themselves and their costs are kept.

### Checked

The tests cover:
- a structured call's trace (prompt, answer, stop reason, served model, latency, the filings it was about), with the instructions stored once
- a failed call and a conversation traced
- traces off
- listing by days, task, failures and words; the full detail
- pruning: the old trace and its now-unused instructions go, the calls stay
- answers made JSON
- the page rendering with 20 pages

Screenshot taken with stand-in calls in a scratch copy of the database.
