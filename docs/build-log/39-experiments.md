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

## Follow-up: the first real runs, and a diagnosis

The Results reader's first baseline scored 36% fully correct.
- Six cases took the standalone statement where the company reports consolidated.
- Seven read nothing or no quarter.
- Four had a wrong unit or table.
- Bank statements were cut off at 4,000 tokens.

Variant v1 (prefer consolidated; one statement, its own unit) lifted basis from 68% to 81%, but correct only from 33% to 37%: no clear difference over 27 cases. With the right statement chosen, most figures then came out empty, which suggests the model never saw them.

So:
- `sna eval results diagnose`: for each miss, whether the XBRL figures are in the PDF's text and in the excerpt the reader sends, in which unit, and so whether the PDF, the excerpt or the model is to blame. No AI calls.
- The eval's answer keeps the reader's note on what the document is, and the figures it wrote that weren't in the text.
- The reader's output limit goes from 4,000 to 8,000 tokens, so long bank statements aren't cut off. This applies in production too.

The diagnosis of v1's 20 misses:
- 9 had the figures nowhere in the PDF's text (covering letters, scanned files, garbled tables)
- 5 had them in the text but outside the excerpt
- 6 had them in the excerpt and Haiku misread them; two of those were the token cut-offs

So:
- **The excerpt** (the reader, so production too): revenue lines with figures on the same line still come first, but the rest of the 40,000-character allowance now goes to the other revenue lines, those near "consolidated" first. A consolidated statement laid out with its figures on the lines below, after a standalone one, used to be dropped whenever the standalone row was found. Airtel's 228,000-character PDF was sent as 11,500 characters.
- **Sampling** takes only a results PDF whose text holds the quarter's XBRL revenue or profit. `diagnose --exclude-missing` excludes the existing cases that measure the PDF, and `sample --n N` replaces them.
