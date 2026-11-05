# Step 34: The Agent evals page

**Goal:** see at a glance how each AI agent is performing, like the Agent map shows how they work.

- **Every eval run is kept in the database** (migration 0031: `eval_runs`, `eval_results`). That holds the variant, model, prompt version, scores, cases passing and failing, failed calls and cost, plus each case's runs with what was expected and what the agent found. The eval runs from the project folder and the dashboard in Docker; the database is what both see.
- **Agent evals** (Today group, after the Agent map):
  - the agents with an eval, the cases passing and failing, and the last run
  - a card per AI agent:
    - an agent with an eval shows its fully-correct share, with the change since the last baseline and the margin on hover; a bar of passing cases; recall, precision and specificity; badges for unchecked answers or failed calls
    - an agent without one says how it could be graded
  - **Look closer:** the score run by run per variant with its error bars; the latest run of each variant side by side; the cases, failing first; each failing case's expected events next to those found
- **Docs:** a Guide section, design 1.32 (an Evals section in agent-design.md), docs/evals.md, README, the system map.

### Checked

- A run with a fake model is recorded with its scores, pass and fail counts, failed calls and the harness digest.
- The page's queries list failing cases first, with what was expected and found.
- The page renders empty and with three runs.
- 18 pages are registered, and the Guide has the new section.

Screenshots were taken with made-up runs in a scratch copy of the database.

Draft post: "Agent #7 now has a report card. 40 filings, answers I checked, three runs each: how often does it get the events, types and amounts exactly right? The Agent evals page shows it next to the agent map, and every other agent's card says how it will be graded. #BuildInPublic"
