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

The first real run needs `--approve-harness`, after you've read the runner and the eval's grader. If either changes later, runs refuse until you approve again, so a score can't silently change meaning. Failed calls (timeouts, refusals, cut-off answers, no credit) are kept apart from wrong answers, and the served model is checked against the one asked for.

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

**What it measures:** given a results PDF, does the agent read the quarter's figures the way the company filed them in XBRL? Its answer for the quarter is converted to Rs crore and filtered as the reader stores it: a figure is kept only if it is written in the text.

**Cases:** quarters that have the exchange's XBRL figures and a results PDF with text, at most two per company. The XBRL figures are the answer, exact and filed by the company, so nothing needs drafting or checking.

| Score | What it means |
| --- | --- |
| **Correct** (the headline) | The same basis (consolidated or standalone), and revenue and profit within 0.1% (or Rs 0.02 crore) |
| Basis, Revenue, Profit, EPS | Each right or not |
| All figures | Share of the XBRL figures it got right (revenue, other income, finance costs, depreciation, profit before and after tax, EPS) |
| Quarter found | It found the quarter's column at all |

## Noise

The margin on a pass rate is about ±1.96·√(p(1−p)/n), where n is the number of graded runs. 40 cases × 3 runs gives about ±9 points at 95%, so a change smaller than that may be chance.
