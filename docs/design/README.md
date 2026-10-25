# Design documents

| File | Covers |
| --- | --- |
| [design.md](design.md) | Goal and principles, data sources, architecture, core modules, extended ideas, database, tech stack and roadmap, existing products, risks |
| [agent-design.md](agent-design.md) | The agent team, LLMs and costs, tools, data requirements, hosting, the agent-by-agent build guide, the build-in-public plan |

These files are the reference for the design. Change them in a pull request like code: edit the text, bump the version line at the top of each changed file, and add an entry below.

Versions: a minor bump (1.1) for corrections and decisions that fit the existing plan, a major bump (2.0) when the plan itself changes, such as agents added or dropped, or the architecture changed. Building agents in a different order is a minor change.

## Changes

### 1.1 · Oct 25, 2026

The design brought up to date with steps 1–11.

- Both files:
  - a status section: what is built, what is not, and which build step did it
  - "As built" notes under each module or agent that exists
- design.md:
  - data sources marked built or not started
  - a table mapping the tables built so far to the planned ones
  - the tech stack as used: curl_cffi, pypdf, APScheduler, Haiku/Sonnet, Streamlit
  - Phase 1 marked done and Phase 2 in progress
  - the open decisions answered; two new ones added (next agent, unusual-day threshold)
- agent-design.md:
  - the actual LLM costs next to the estimates
  - Sonnet 5.5 instead of Opus 5.5 for the Move Explainer
  - the actual schedule and hosting
  - the one change to the build order: the Move Explainer came before the Event Extractor

The original plan text is unchanged; differences are recorded beside it, so the plan and what was built can be read together.

### 1.0 · Oct 21, 2026

The original design, written before any code. Moved into the repo on Oct 23, 2026 unchanged except for:

- a version line at the top of each file, and links between the two files
- the three diagrams (architecture, roadmap, agent team) redrawn as text; the roadmap table was rebuilt from the data sources table
