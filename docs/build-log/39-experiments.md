# Step 39: Experiments compared

**Goal:** try a change to an agent (a prompt or a model), compare it with the baseline case by case, and keep it only if it helps by more than chance, like LangSmith's experiments. This completes the eval platform:
- 35: datasets and a framework
- 36: labelling
- 37: traces
- 38: live monitoring
- 39: experiments

- **Variants:** `sna eval <name> run --variant v1` with `--model` or `--instructions FILE` (other instructions in place of the agent's, through the same call), and `--note` for why. `sna eval <name> instructions` prints the agent's own instructions to start from. Each run records its config (the model, and the agent's own instructions or a digest of the file) and the note (migration 0034). A variant's folder gets a `change.md` with both.
- **Comparison** (`framework.compare`): the latest runs of two variants, paired case by case on the cases both graded.
  - Each case's headline score is averaged over its runs.
  - It lists the cases that got better and worse and how many stayed the same, each metric side by side, the cost a case, the median latency and the failed calls.
  - The verdict comes from the mean of the paired differences and its 95% interval: better or worse only when the interval leaves out zero, no clear difference otherwise, and too few cases to tell under five.
- **On the page:** Agent evals' Look closer has **Compare variants**: two variants, the verdict, the side-by-side table, and the cases that got better or worse with what was expected, what each found.
- **In the terminal:** `sna eval <name> compare [A] [B]`.

### Checked

The tests cover:
- a variant run with other instructions: the model is sent them, the run records config and note, change.md is written, the trace shows them
- the config of the agent's own instructions, even when passed in
- a variant fixing five cases judged better, with the cases, metrics, cost and latency
- worse, no clear difference, too few cases, and cases only one side ran
- the instructions command
- the page's comparison, with the verdict, the why and the cases that got better

Screenshot taken against sample runs in a scratch copy of the database.
