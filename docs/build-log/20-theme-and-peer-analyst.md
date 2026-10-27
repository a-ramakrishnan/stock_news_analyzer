# Step 20: Theme & Peer Analyst

**Goal:** see what links the companies you follow. Which themes are getting stronger, who is in them, and when one company's news is worth a look for another.

## What was added

| Piece | Why |
| --- | --- |
| `config/themes.yaml` | The themes, each with a key, a name and a hint for the model; edit freely |
| `theme_tags`, `peer_signals` tables (migration 0022) | Each item's themes; each read-across from one company's item to another watchlist company |
| `agents/themes.py` (agent 14) | Tagging (Haiku), theme strength and read-across (code) |
| `themes` job, 07:52 daily | After the orders, before the red flags and the digest |
| `sna themes run/list/show/signals/reset`, `make themes` | Tag, see the themes, one theme, read-across, start over |
| Digest | A "Read-across" section |
| Dashboard | A **Themes** page (eight pages now) |

## Tagging

The items are the watchlist's checked events (not management changes, ratings or promoter actions, which belong to no theme), its orders, and the forward-looking points from its earnings calls (guidance, demand, capex, order book, initiatives). Haiku reads 40 a call, each as one line, and gives each up to three theme keys from the list. Keys not on the list are dropped. An item with no theme is stored as `none`, so it isn't read again. It tags by what the item is about, not by the company's usual business: a cable maker's data-centre order is data centres and power T&D, while its new CFO is nothing.

## Strength

Per theme: items and companies in the last 90 days and the 90 before, positive and negative items, and the value of orders. Per month as well. It is all in code, from the tags. A count tells more across many items than a model's opinion of any one.

## Read-across

An important item at one company is listed for the other watchlist companies it may matter to:

- **Important:** an event of importance 4 or 5, or an order of 1% or more of the company's revenue for the 12 months before
- **Matters to:** the company's approved peers on the watchlist, and watchlist companies with an item in the same theme in the previous 180 days
- At most five per item, each once

It is plain code with no direction. The design had Sonnet judge whether a peer's news helps or hurts. A rival's order win can be bad news, and a supplier's can be good. The signal says "worth a look" and why, rather than guess the sign.

## Not yet

- **Customer and supplier map:** read from annual reports and calls. Peers come from the industry list you approve.
- **A weekly theme summary in the digest:** the Themes page and `sna themes list` cover it for now.

## On the Mac

```
git checkout main
git pull
uv run sna db upgrade
uv run sna themes run
uv run sna themes list
uv run sna themes signals
make scheduler
```

## Next

Analyst Q&A (agent 17), the last agent. Email delivery comes later.
