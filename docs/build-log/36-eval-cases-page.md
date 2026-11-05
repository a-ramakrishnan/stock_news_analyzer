# Step 36: Checking eval cases in the dashboard

**Goal:** check and correct the eval's expected answers where you read the filings, not in YAML files, like a LangSmith annotation queue.

- **Eval cases** (a new Agents group in the sidebar, with the Agent map and Agent evals):
  - pick an eval and a view (to check, checked, excluded, all), with a progress bar of what is checked
  - go through the cases with Previous, Next or the list
  - the left side shows what the agent read (for a filing: its title, subject and the start of its text, exactly as the Event Extractor gets them)
  - the right side shows the expected answer as an editable table: type from the agent's own list, amount in Rs crore, the amount as written, a headline; rows can be added and deleted
  - **Confirm** saves it checked, **Nothing to find** records no event, **Exclude** leaves a case out of runs, each with a note
  - the case's **History** shows every earlier answer, its status and who changed it
  - the next case to check opens by itself
  - the Results reader's answers are XBRL, shown read-only, with Exclude and Include again
- **Add to the Event Extractor's eval** on Filings: a filing it read wrongly, or one worth testing, becomes a case to answer on Eval cases.
- **Agent evals:** an agent with cases to check links to Eval cases.
- **The framework** gains what a page needs from a spec: how to show the input, the answer as table rows and back, the empty answer, and a case for one item. It also gains `add_case`.

### Checked

The tests cover:
- the answer as a table and back (an amount left blank, an empty row)
- adding a filing by hand once only, and showing its text
- the page: confirm as drafted, mark nothing to find, exclude with a note, the history recorded, nothing left to check
- the Filings button: added, then already there
- 19 pages in six groups

Screenshot taken with sample cases in a scratch copy of the database.
