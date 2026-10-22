# Step 9: News Triage (agent 6), the first LLM agent

**Goal:** stop reading every headline. For each article about a watchlist stock, an LLM decides whether it is really about that company, what kind of news it is, which way it cuts for a shareholder and how much it matters, so the digest and dashboard can show the few articles that count.

## What was added

| Piece | Why |
| --- | --- |
| `llm.py` | The one place that calls Claude, used by every Phase 2 agent: asks for a structured answer (a pydantic model), logs tokens and cost of every call, refuses calls once the monthly budget is spent |
| `llm_calls` table (migration 0009) | Task, model, tokens (including cache reads/writes), cost in US dollars, success or error |
| `news_triage` table (migration 0009) | Per article and company: relevant, topic, sentiment, importance 1-5, one-line summary, `duplicate_of` |
| `agents/triage.py` | Finds repeats without the LLM, sends the rest to Claude Haiku in batches of 15 per company |
| `triage` job at :25 every hour | Ten minutes after news collection; at most 500 articles per run |
| `sna triage run/list`, `sna llm usage`, `make triage` | Run, read, and watch the spend |
| Digest, News page, Stock page, System page | Off-topic articles and repeats hidden, the rest sorted by importance with topic, sentiment and summary; AI spend against the budget |

## How it works

1. **Repeats first, for free.** Within one company, an article whose headline is at least 90% similar to an earlier one in the previous three days is a copy of the same story (the same PTI piece on five sites). Only the first goes to the LLM; the copies reuse its triage and point to it.
2. **Haiku, in batches.** Up to 15 articles about one company per call: headline, date, publisher and the first 600 characters, with the company's name, industry and aliases. Effort `low`, as the job is classification. The instructions are the same on every call, so they are marked for caching.
3. **A fixed schema.** The answer must match a pydantic model: `relevant`, `topic` (one of 12), `sentiment` (positive/negative/neutral/mixed), `importance` (clamped to 1-5) and `summary`. Ids the model invents are ignored; articles it skips stay pending for the next run.
4. **Safe failure.** A refused or cut-off answer is logged and its articles stay pending; when the budget is reached the run stops and the job reports it. Without an API key the scheduled job skips quietly.

Article text is treated as data: the instructions say so, and the model only returns the fixed fields.

## Cost

Haiku 5.5 costs $0.10 per million input tokens and $0.50 per million output. A batch of 15 articles is about 5,000 tokens in and 1,500 out, roughly a tenth of a cent, so the three-year backlog of a few thousand articles costs around a dollar and daily triage a few cents.

## How to check it

Add your key to `.env` first (`ANTHROPIC_API_KEY=...`), then:

```bash
git pull
uv sync
make migrate
uv run sna triage run --limit 30
uv run sna triage list --min-importance 1 --all
make triage
uv run sna llm usage
make scheduler
make ui
```

Start with `--limit 30` to read a few results before triaging the whole backlog. `make scheduler` rebuilds the Docker scheduler so it picks up the triage job and your key.

## Tweet draft

> Phase 2, agent #6: News Triage. Claude Haiku reads every article about my stocks and answers: is it really about this company, what kind of news, good or bad for shareholders, how much it matters (1-5), in one line. Copies of the same wire story are caught for free first. Cost: about a dollar for 3 years of news. #BuildInPublic
