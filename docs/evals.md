# Evals

An eval measures one AI agent on a fixed set of cases with checked answers, so a change (a new prompt, a different model) can be judged by a number instead of a feeling.

## The framework

Every agent's eval is built the same way (`src/stock_news_analyzer/evals/framework.py`):

| Part | What it is |
| --- | --- |
| **Dataset** | Cases in the database (`eval_cases`). Each holds the agent's input, frozen so the eval doesn't change when your data does, and the expected answer with its status: *new* (no answer yet), *draft* (drafted, not checked), *verified* (checked by you, or taken from an exact source), *excluded*. Every earlier answer and status is kept in the case's history. |
| **Target** | The agent's own entry point, called on one case, so the eval measures what runs in production |
| **Graders** | Code that scores the answer against the expected one; the first metric is the headline |
| **Runs** | Each run's scores and every case's result are kept in `eval_runs` and `eval_results` and shown on the **Agent evals** page. Results, transcripts and a summary also go to `.claude/hillclimb/<eval>/<variant>/`. |

**Checking answers** happens on the dashboard's **Eval cases** page (Agents group):
- what the agent read is shown beside the expected answer as an editable table
- **Confirm**, **Nothing to find** and **Exclude**, with a note
- each case's history of earlier answers

The **Filings** page adds any filing to the Event Extractor's eval. The YAML files are only for keeping the cases in git.

An agent gets an eval by adding a `Spec` (`evals/<name>.py`, registered in `evals/__init__.py`). The spec says:
- how to sample cases from your database
- how to draft an answer for you to check (or that the answers come with the cases)
- how to call the agent and grade its answer
- how to describe an answer in a line

The commands, the runner and the page are shared.

| Command | Does |
| --- | --- |
| `sna eval <name> sample [--n N]` | Adds cases from your database (never one already there) |
| `sna eval <name> draft` | Drafts answers for cases without one, with Opus. It stops cleanly on an API error, and running it again continues |
| `sna eval <name> show` | The cases and their answers as a table |
| `sna eval <name> run` | Runs the agent on the checked cases (3 runs each by default) and grades them. The run is kept for the page; rerunning resumes where it stopped |
| `sna eval <name> export` / `import` | Writes the cases to `evals/<name>/cases/*.yaml` to keep them in git, or reads them back. The first command on an empty dataset reads the files by itself |

`run` options:
- `--variant v1 --model ...` measures a change next to the baseline
- `--case KEY` runs a pilot on chosen cases
- `--unverified` includes cases not checked yet
- `--mode oracle` and `--mode null` check the grader for free: the expected answers must score 100%, and no answer at all scores only what has nothing to find

A rerun resumes where it stopped, but only from attempts made with the same agent code, instructions, model and case. Any others are run again, and the old ones are moved to `results.stale.jsonl`, so a variant name reused after a code change measures the new code. Scores count only the cases in the eval now: a case excluded later drops out of the summary, the page and `compare`, which lists it as left out.

The first real run needs `--approve-harness`, after you've read the runner and the eval's grader. If either changes later, runs refuse until you approve again, so a score can't silently change meaning. Failed calls (timeouts, refusals, cut-off answers, no credit) are kept apart from wrong answers, and the served model is checked against the one asked for.

## Experiments

A variant is a run with something changed: another model (`--model`), or other instructions from a file (`--instructions FILE`). Every run records what it used (`eval_runs.config`: the model, and the agent's own instructions or a digest of the file) and why (`--note`). For a variant, that goes into `change.md` too.

```
uv run sna eval events instructions > v1.txt          # the agent's instructions, to edit
uv run sna eval events run --variant v1 --instructions v1.txt --note "stricter about lakh and crore"
uv run sna eval events compare baseline v1
```

`compare` (and **Compare variants** on the Agent evals page) pairs the two runs case by case on the cases both graded and gives:
- which cases got better, which got worse, and how many stayed the same
- each metric side by side
- the cost a case, the median latency and the failed calls

The verdict on the headline metric comes from the paired differences:
- **better** or **worse** only when the 95% interval of the mean difference leaves out zero
- **no clear difference** otherwise
- **too few cases to tell** under five cases

A change you keep then goes into the agent's code with a new prompt version, and live monitoring shows how it does on real work.

## Traces

Every AI call is traced (`llm_traces`, migration 0033), failed calls included. A trace holds:
- the instructions, stored once per distinct text
- what the call was sent: the prompt, or the conversation for Ask
- what it answered
- the stop reason, the model that served it, and how long it took
- the filings it was about

The **Traces** page and `sna llm traces` / `sna llm trace ID` show them. A call about filings can add them to the Event Extractor's eval. Traces are kept `llm_trace_days` (30 by default, set on Settings, 0 for none) and pruned each morning with the digest (`sna llm prune` by hand). Live monitoring (step 38) reads them.

## Live monitoring

Evals measure an agent on fixed cases; monitoring watches it on real work (`monitoring.py`), from what the agents already record, with no extra AI calls:
- events passing the QA check
- event quotes found
- events you rejected
- filings the Event Extractor couldn't read
- results PDFs read
- order amounts found in their filings
- earnings-call quotes found
- Research brief views with parts dropped
- AI calls that failed

Each is a daily rate, split by prompt version, model or task. The last 7 days are compared with the 28 before. An **alert** needs a change for the worse of at least 5 points and beyond 2.5 standard errors of the difference, with at least 10 items this week and 20 before. Alerts show on the **Monitoring** page and in the morning digest (**Agent quality**).

## The evals

### Event Extractor (`sna eval events`)

**What it measures:** given one filing, does the agent find the events it announces, of the right types and amounts, with quotes that are really in the filing? It grades Haiku's raw answer, before the QA Checker corrects or rejects anything.

**Cases:** filings from your database:
- 60% that Haiku found events in, spread over the event types, with the ones you rejected first
- 40% that it found none in

Answers are drafted by Opus and checked by you.

| Score | What it means |
| --- | --- |
| **Correct** (the headline) | An event when there should be one and none when there shouldn't; the same event types; every expected amount right within 1% |
| Detect | An event found when there is one, none when there isn't |
| Types F1 | The event types found against those expected (1 when both are none) |
| Amounts | Share of expected events whose amount, or its absence, is right |
| Quotes found | Share of the events found whose quote is in the filing and holds the amount |

Over all runs it also gives recall (filings with events in which it found one), precision (filings it found events in that have them) and specificity (routine filings it left alone).

### Results reader (`sna eval results`)

**What it measures:** given a results PDF, does the agent read the quarter's figures the way the company filed them in XBRL? Its answer for the quarter is converted to Rs crore and filtered as the reader stores it: a figure is kept only if it is written in the text (garbled tables included: columns run together, dots or spaces for commas, a comma for the point).

**Cases:** quarters that have the exchange's XBRL figures and a results PDF whose text holds the quarter's revenue or profit, in any unit, at most two per company. A covering letter, a scanned file or a garbled table would measure the PDF's conversion to text, not the reader. The XBRL figures are the answer, exact and filed by the company, so nothing needs drafting or checking.

| Score | What it means |
| --- | --- |
| **Correct** (the headline) | The same basis (consolidated or standalone), and revenue and profit within 0.1% (or Rs 0.02 crore) |
| Basis, Revenue, Profit, EPS | Each right or not |
| All figures | Share of the XBRL figures it got right (revenue, other income, finance costs, depreciation, profit before and after tax, EPS) |
| Quarter found | It found the quarter's column at all |

Each answer keeps the reader's own note on what the document is, and any figure it wrote that isn't in the text (and so was left out, as the reader stores it).

**Diagnosing the misses** (`sna eval results diagnose [--variant v1] [--all]`, no AI calls): for each case the latest run got wrong, code looks for the XBRL revenue and profit in two places:
- the PDF's text
- the excerpt the reader sends the model (the whole filing when it fits in 40,000 characters, else the start and windows around its revenue lines)

It looks in every unit a statement may use (crore, lakh, million...), allowing for rounding. Each miss is then put down to one cause:
- no text in the PDF
- figures not in the text (another document, or garbled text)
- figures in the text but outside the excerpt
- figures in the excerpt, so the model misread them, which is where instruction variants help

`--exclude-missing` excludes the cases whose figures aren't in the PDF's text, with the cause as their note. `sample --n N` then adds fresh ones, and new samples only take PDFs that hold the figures.

## Noise

The margin on a pass rate is about ±1.96·√(p(1−p)/n), where n is the number of graded runs. 40 cases × 3 runs gives about ±9 points at 95%, so a change smaller than that may be chance.
