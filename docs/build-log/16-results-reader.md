# Step 16: Results Reader

**Goal:** record each watchlist company's reported figures from its results filings: revenue, profit and margins by quarter, or by half year for SME companies. With these, the order metrics for companies like KMEW and DIACABS no longer depend on order-book documents that leave revenue out.

## What was added

| Piece | Why |
| --- | --- |
| `results`, `result_filings` tables (migration 0016) | Each company's figures per period (quarter, half year, year); each results filing read and its outcome |
| `agents/results.py` | Reads results filings (Haiku), converts and checks the figures, and builds the per-period table with growth and margins |
| `results` job, 07:20 daily | New results before the earnings calls and order books |
| `sna results run/list/coverage/reset`, `make results` | Read, see a company's periods, see what was found per stock, start over |
| Order Book Tracker | Revenue the order-book documents left out now comes from results; half-yearly reporters get 12-month revenue from two half years |
| Digest | A "Results" section: revenue and profit with their change on a year earlier, and the EBITDA margin |
| Stock page | A **Results** tab: latest revenue, profit and EBITDA margin; revenue chart; the table |

## How a filing is read

1. **Group:** results filings are grouped by company and the quarter they report. The BSE and NSE copies, the board meeting outcome and the newspaper advertisement of the same results fall in one group.
2. **Best first:** in each group the filing titled as results is read first, then the board meeting outcome, then the newspaper copy. Once a period is read, the rest of its group is marked as copies without an LLM call.
3. **Only the statement:** a results PDF also carries auditors' reports and notes. Only the covering letter's start and the text around each "revenue from operations" (for banks, "interest earned" or "total income") is sent, at most 40,000 characters, so a quarter costs about $0.002 with Haiku.
4. **Copy, don't convert:** Haiku copies each figure exactly as written ("67,00,000.00", "(234.10)" for a loss) and names the statement's unit. The code turns them into Rs crore and checks each one against the filing's text. The model does no arithmetic.
5. **Three periods per filing:** the statement's columns also give the previous quarter and the same quarter a year earlier. Those periods are filled at once, marked as coming from a comparative column, and replaced when their own filing is read.

## Choices

- **Haiku, not Sonnet:** copying numbers from a table is a reading task, and every figure is checked against the text. Sonnet would cost about 20 times as much for two years of results.
- **Consolidated first:** the consolidated statement is used where the filing has one, else standalone. The basis is stored per period.
- **EBITDA in code:** results statements don't report EBITDA. It is computed as profit before tax + finance costs + depreciation − other income.
- **Fill, don't replace:** where an order-book document gave a quarter's revenue, that figure stays; results fill only the gaps (marked `*` in `sna orders book`). L&T's figures already matched its published numbers.
- **Half-yearly SME reporters:** without four quarters, revenue is the 12 months to the latest order book from two half years (or the year). Book-to-bill then uses the orders the company announced in those 12 months when it didn't report its inflow. The dashboard says which was used.

## On the Mac

```
git checkout main
git pull
uv run sna db upgrade
uv run sna results run
uv run sna results coverage
uv run sna results list KMEW
uv run sna orders book KMEW
uv run sna orders peers
make scheduler
```

`results run` reads two years of results, shows its cost estimate first (well under $1) and asks before spending more than $1.

## After the first real run

- **A cut-off answer stopped the run.** The SDK checks the answer against the schema before returning it, so a malformed answer raised a pydantic error the agents didn't catch. It is now an ordinary LLM error: that filing is skipped and tried again on the next run, and the rest carry on. Nine-month columns, which aren't stored, are no longer asked for, so answers are shorter.
- **Profit included minority interests.** KMEW's consolidated profit didn't match its EPS (Q3 FY26: Rs 33 crore profit but EPS 13.35, against Rs 12 crore and 10.37 the quarter before), because its subsidiaries have outside partners. Profit is now the profit attributable to owners, the figure EPS is based on.

## After the second run

237 periods from 136 filings for $0.23. Two more things showed up:

- **L&T's last two quarters weren't found.** Its results come with a press release that mentions "revenue from operations" in paragraph after paragraph. Those mentions used up the text windows before the statement itself. Revenue lines followed by three or more figures, the statement's rows, are now picked first.
- **An unusable answer was asked again every day.** Haiku once repeated itself until 8,000 tokens, and once returned broken JSON. Such a filing is now marked `failed` and the period's next filing is tried instead. Transient API errors are still retried on the next run. Answers are capped at 4,000 tokens.

## L&T's results without a statement

L&T's Q4 FY26 and Q1 FY27 results filings, on both exchanges and under several titles, all attach the same PDF: the results press release with its annexures. The statement pages either aren't in it or aren't text. The press release's "Group Performance – Key Parameters" annexure still gives revenue, EBITDA, finance costs, depreciation and profit after tax for the quarter and a year earlier. Haiku had seen it but said "no results statement", because the prompt asked for one. The prompt now takes such a key-figures table when a filing has no statement. Figures the table doesn't give (other income, profit before tax, EPS) stay empty, so EBITDA isn't worked out for those quarters.

## A dropped decimal point

On the full re-run, three L&T quarters came out 100 times too large: Q4 FY24 revenue of Rs 6,707,868 crore instead of Rs 67,079 crore. Haiku had copied "67,078.68" as "6707868". The check compared the figures with the text ignoring punctuation, so it passed. The same filings had been read correctly the run before.

- **Exact numbers only:** a figure is now kept only if the same number, decimal point included, appears in the filing. A figure that doesn't is left empty and marked as not found.
- **Sonnet as a second try:** KARURVYSYA's long bank statements still made Haiku repeat itself or break off in 9 of its filings, and BLACKBUCK's in 4. When Haiku's answer is unusable, the analysis model now tries the same filing once before it is marked `failed`.

The exact-number check didn't stop it. On the next run the same three L&T quarters were still 100 times too large, and Q4 FY25's profit was too (Rs 549,726 crore). So the number without its point really is in the extracted text: the PDF's text layer loses the decimal point in some table cells, and Haiku copied what it saw.

- **Figures checked against each other:** after each run, each company's revenue is compared with its other periods of the same length, and every other figure with its period's revenue.
- **Restored when it fits a lost point:** a figure 50-200 times too large, written without a decimal point while the others in its column have one, is divided by 100 and noted "decimal point restored".
- **Left out otherwise:** revenue over 20 times the usual, or costs or profit above revenue for another reason, is left out and noted "out of scale, left out".

## XBRL: the exchange's own figures

Companies file every set of results in XBRL as well as PDF: each figure tagged, in rupees. Read from there, a figure needs no LLM and no check against PDF text.

- **Two listings:** NSE's results listing has filings up to January 2025. From February 2025 results are filed as SEBI's Integrated Filing (Financial), listed at `/api/integrated-filing-results`. `sna results probe` found both.
- **Which context:** the listing's files put the filing's period in context `OneD`; their context dates aren't reliable. Integrated filings are read by their context dates, so a Q4 filing gives the quarter and the year.
- **XBRL is filed by the company, so it is checked too.** KMEW's profit-attributable line didn't fit its EPS (Q3 FY26: Rs 0.22 crore against EPS 13.35), and its H1 FY25 was filed under Q2's label (revenue Rs 95.62 crore). Two checks were added:
  - profit must be within 25% of EPS × shares, where shares are paid-up capital ÷ face value from the same file
  - a "quarter" more than 1.75 times the company's nearby quarters is rejected and the PDF reading put back

  XBRL writes only the figures that pass and keeps each replaced value. The half-year check also caught KMEW's genuinely strong Q3 FY26 (Rs 90 crore against about Rs 50 crore around it); its PDF reading was the same, so nothing was lost.
- **Result:** on a full rebuild, 236 periods came from XBRL and 26 PDF readings were corrected. L&T is exact from Q1 FY24 to Q1 FY27. KARURVYSYA's missing revenue and odd EPS are fixed. Four 2023 bank files are no longer on NSE.
- **Daily:** the `xbrl` job at 07:15 runs before the PDF reader, which then skips the periods XBRL covered.

## Next

The rest of the Event Extractor (capex, guidance, management, ratings, fundraises), with the QA Checker.
