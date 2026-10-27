# Step 21: Analyst Q&A

**Goal:** ask anything about your companies in plain English and get an answer from your own data, with the sources it came from.

## What was added

| Piece | Why |
| --- | --- |
| `LLM.message` | One turn of a conversation with tools; logs cost like every other call and checks the budget first. The system prompt and tools are cached between turns |
| `questions` table, full-text index on `documents` (migration 0023) | Every question with its answer, sources, lookups and cost; fast word search over filings and news |
| `agents/ask.py` (agent 17) | The tool loop, the three tools and the citations |
| `sna ask`, `sna questions list/show/rerun` | Ask; see, re-read and re-ask questions |
| Dashboard | An **Ask** page (nine pages now) |

## How it answers

Sonnet gets the question, today's date, a few working rules and every table with its columns. The table list is generated from the models, so a new table is known without editing the prompt. It then calls tools until it has enough, at most 10 lookups:

- **`run_sql`:** one SELECT or WITH query. It runs on its own connection in a `READ ONLY` transaction with a 5-second statement limit, and is always rolled back. A write slipped into a CTE is refused by PostgreSQL itself, not just by the check on the first word. At most 100 rows come back, as tab-separated text, with long cells cut to 300 characters.
- **`search_text`:** PostgreSQL full-text search (`websearch_to_tsquery`, so `OR` and `-word` work) over filings and news, earnings-call points, checked events and promises. Optional symbol, kinds and start date. Each hit has its id, date, company and a snippet with the words marked.
- **`read_document`:** a document's title, date, link and first 6,000 characters (for a transcript linked from a filing, the linked text).

A tool error (a bad column name, a timeout) goes back to the model as text so it can fix its query. When the limit is reached it is told to answer with what it has.

The answer cites `[doc:ID]`, `[event:ID]`, `[point:ID]` or `[promise:ID]` after each fact. Only citations that point to stored rows are kept as sources and shown with dates and links.

## Differences from the design

- **Sonnet, not Opus,** by default. Most questions are lookups plus a short summary. `--model claude-opus-5-5` is there for a hard one, at about five times the cost.
- **Full-text search, not vectors.** There is no embeddings API on the account. Word search with stemming finds filings and call points well enough, and a GIN index keeps it fast.
- **Saved reports are kept, not scheduled.** `--save NAME` stores a question; `sna questions rerun NAME` asks it again. Running them from the scheduler can come with email delivery.

## Tests

`tests/test_ask.py` plays back model turns with a fake client:
- the SQL check and the read-only transaction (a hidden `DELETE` changes nothing)
- row limits, and the session still working after a failed query
- search by words, symbol, kind and date
- a full question with three lookups: tool results sent back with matching ids, unknown citations dropped, the question stored with its cost
- the step limit and the monthly budget

## On the Mac

```
git checkout main
git pull
uv run sna db upgrade
uv run sna ask "Which of my companies raised guidance this year?"
uv run sna questions list
make ui
```

## Next

All 17 agents are built. Email delivery of the digest comes next.
