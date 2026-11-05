# Step 32: Shared data for other projects

**Goal:** let a separate project (stock_deep_research, a deep research report for any stock) use the data collected here without depending on this project's code or tables.

- **Read-only views** in a `shared` schema (migration 0030): companies, peers, index members, documents with their text, news triage, daily prices and indices, moves, corporate actions, results, balance sheets, shareholding, checked events, orders, order books, earnings calls and their points, promises, red flags and deals. Their columns are the contract, documented in [shared-data.md](../shared-data.md) with a version (`shared.contract`, 1.0).
- **A login that can only read them:** `research_reader`, with `SELECT` on the views and nothing else (password from `SNA_READER_PASSWORD`, else `research_reader`). Like the main `sna` login, it is reachable wherever Docker publishes port 5433; on a shared network, set both passwords.
- **Why views, not a shared library or an API:** the other project imports nothing from this one, so either can change freely as long as the views keep their shape; an HTTP API would be more code for two apps on one computer.

The other project keeps its own tables in its own database on the same Postgres server.

### Checked

A test reads every view as `research_reader`, checks the contract version and a company's flags, and checks that the login can't read a table directly or write through a view. 396 tests pass.

## On the Mac

```
git pull
make start
```

The migration runs as the app starts; `psql postgresql://research_reader:research_reader@localhost:5433/sna -c "select * from shared.contract"` shows the version.
