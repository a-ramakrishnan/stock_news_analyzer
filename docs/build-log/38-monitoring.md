# Step 38: Live monitoring

**Goal:** know when an agent starts doing worse on real work, without waiting for an eval run, like LangSmith's online monitoring. It uses only what the agents already record, so it costs nothing.

- **Nine monitors** (`monitoring.py`), each a daily rate read from the agents' own tables and split so a change shows where it came from:

  | Monitor | Better | Split by |
  | --- | --- | --- |
  | Events passing the QA check | higher | prompt version |
  | Event quotes found in the filing | higher | prompt version |
  | Events you rejected | lower | prompt version |
  | Filings the Event Extractor couldn't read | lower | model |
  | Results PDFs read | higher | model |
  | Order amounts found in their filings | higher | model |
  | Earnings-call quotes found | higher | prompt version |
  | Research brief views with parts dropped by the number check | lower | model |
  | AI calls that failed (eval drafts left out) | lower | task |

- **Alerts:** the last 7 days against the 28 before. An alert needs a change for the worse of at least 5 points and beyond 2.5 standard errors, with at least 10 items this week and 20 before, so a quiet week or a small dip doesn't raise one.
- **Monitoring page** (Agents group):
  - alerts at the top, or an all-clear
  - a card per monitor with this week's rate, the change in points (coloured by which way is good) and how much work it rests on
  - a monitor's 7-day rolling rate over 30, 90 or 180 days, overall and by group
  - AI spend over 30 days by task
- **The morning digest** lists alerts under **Agent quality**.

### Checked

The tests cover:
- a drop from 90% to 50% on a new prompt version is an alert, with the two versions split
- a small dip, and too little work, are not alerts
- a lower-is-better monitor (failed calls rising from 0% to 50%), with eval drafts left out, and spend by task
- briefs with parts dropped
- alerts in the digest, and none when there are none
- every monitor's query runs
- the page renders: 21 pages

Screenshot taken against the synthetic database.
