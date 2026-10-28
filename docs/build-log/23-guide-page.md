# Step 23: Guide page

**Goal:** someone new can open the dashboard and learn how to use the system without asking. This is the first step of the [sharing plan](../design/sharing.md).

## What was added

| Piece | Why |
| --- | --- |
| `src/stock_news_analyzer/ui/guide.md` | The Guide's text, in ten sections; readable on GitHub too, linked from the README |
| `ui/guide.py` | Splits the file into sections and makes link names for them |
| **Guide** page (ten pages now) | The sections as a row of choices; `/guide?section=words-used` opens one directly |
| "How to use this page" on every page | Opens that page's part of the Guide, in the same tab |
| One-line descriptions | Filings, News and System had none |
| Sidebar link | "New here? Read the Guide" |

## The sections

| Section | Content |
| --- | --- |
| What it is | What it follows and does; not a trading tool, not advice; runs on your own computer |
| Getting started | Add stocks, load history, start the scheduler, add an API key (optional) |
| A daily routine | What to read each morning, after an unusual day, when results come out, weekly |
| The pages | Each page and the Stock page's tabs |
| Words used | Unusual day, likely cause, promoter, pledge, FII and DII, retail, dilution, order book, book-to-bill, guidance, promise, read-across, red flag, crore |
| How AI is used | Each AI feature, its model, and what still works without a key; the monthly budget and typical cost |
| Where the data comes from | Each source and when it is fetched |
| Keeping it running | The morning window, a computer that was off, checking runs, updating |
| Problems | Port in use, Postgres not reachable, an exchange refusing, budget reached, a stock not found, empty pages, a wrong number |
| Your data | Where it is, how to back it up and start over, where the API key lives |

The text describes the system as it is today, with the commands it still needs. Steps 24 to 27 replace those with buttons and Settings, and the Guide changes with them.

## Decisions

- **Text in a file, not in code:** it can be edited and reviewed like any document, and read before installing.
- **In `src/`, not `docs/`:** the Docker image copies only `src/`, so the dashboard there could not read a file under `docs/`.
- **Streamlit page links, not Markdown links:** a Markdown link opened a new tab each time; `st.page_link` stays in the app.

## Tests

`tests/test_ui.py`:
- the Guide page renders, and the page count is now ten
- the sections are read in order, none empty, with unique link names
- every page's help link points at a section that exists
- `?section=words-used` opens that section

Checked in a browser: the System page's link opens "Keeping it running" in the same tab.

## On the Mac

```
git checkout main
git pull
make ui
```

Open the **Guide** in the sidebar, and try "How to use this page" on a few pages.
