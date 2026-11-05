# Step 35: A general eval framework, and a second eval

**Goal:** every AI agent can get an eval the same way, as in LangSmith: datasets, targets, graders and kept runs. This is the first of five steps:
- 35: the framework
- 36: labelling cases in the dashboard
- 37: traces of every AI call
- 38: live monitoring
- 39: experiments compared

The clean install test moves to step 40.

- **Datasets in the database** (migration 0032, `eval_cases`). A case holds the agent's input, frozen, and the expected answer with a status (new, draft, verified, excluded) and a history of every earlier answer, so labelling can move to the dashboard (step 36). `export` and `import` keep the cases in git as YAML. The first command on an empty dataset reads the files by itself, including the files the first version wrote (step 33), so the 40 drafted cases carry over.
- **The framework** (`evals/framework.py`): a `Spec` per agent says how to sample, draft, call and grade. The runner, the summary, the record of runs, the harness gate and the oracle and null checks are shared. The headline is each spec's first metric; extra statistics such as recall are the spec's own.
- **Commands per eval**, generated from the registry: `sna eval <name> sample | draft | show | run | export | import`.
- **Event Extractor** moved onto the framework, unchanged in what it measures.
- **Results reader**, the second eval (`sna eval results`): quarters with XBRL figures and a results PDF, at most two per company. The reader gets the PDF; its answer for the quarter is converted and filtered as it is stored and checked against XBRL. Scores: correct (basis, revenue and profit within 0.1%), basis, revenue, profit, EPS, all figures, quarter found. No labelling: the company's own XBRL is the answer.
- **Agent evals page:** its tables and cards follow each eval's own metrics and statistics. An agent with an eval that hasn't run says how many cases are checked and what to do next. Runs from step 34 still show.

### Checked

The tests cover:
- the registry
- sampling, drafting with history, a clean stop on an API error and its continuation
- the step-33 files read in, written back and edited
- held-back cases
- a full run: grading, a cut-off answer kept apart, recall, precision and specificity, the run kept, failing cases first, resuming
- oracle and null
- the page with both evals
- for the Results reader: sampling with the XBRL answer, a quarter read right through the real prompt, lakh read as crore, a rounded figure, the wrong basis, a missing quarter, and a figure not in the text

413 tests pass. On the synthetic database the commands sample, show, export and check the grader.
