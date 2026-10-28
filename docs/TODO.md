# To do

Things decided but deliberately left for later, with what has to happen and why it waits.

## Before the repository goes public

### Take the personal watchlist out of the repository and its history

`config/watchlist.yaml` is the author's own list, with `owned: true` on the stocks held. It is tracked in Git, so anyone who can see the repository can see it, in every past commit too.

**Why it waits:** removing it now with `git rm --cached` would delete the file from the author's Mac on the next `git pull`. While the repository is private, only the author sees it.

**When going public:**
1. Back up the file outside the project folder, e.g. `cp config/watchlist.yaml ~/watchlist-backup.yaml`.
2. Remove it from every commit, with [git filter-repo](https://github.com/newren/git-filter-repo): `git filter-repo --path config/watchlist.yaml --invert-paths`, then force-push. This rewrites history, so every other clone has to be cloned again.
3. Add `config/watchlist.yaml` to `.gitignore`, and copy the backup back into place.
4. Point the README and the watchlist comments to `config/watchlist.example.yaml`.
5. Check the history for anything else personal (`.env` was never committed; `data/` is ignored).

### Make the prebuilt image public

GitHub Actions publishes the image to `ghcr.io/a-ramakrishnan/stock_news_analyzer` (see the README). A package made from a private repository is private, so pulling it needs `docker login ghcr.io`.

**When going public:** in the package's settings on GitHub (Packages → stock_news_analyzer → Package settings), change its visibility to public. Then the start script can pull it with no login, and `SNA_PULL_POLICY=always` can become the default for new copies.

## Later

- **Email delivery** of the digest and high-severity red flags, as an option on Settings (each user's own mail account).
- **Try it on a clean Mac and a Windows machine** (step 28 of the [sharing plan](design/sharing.md)).
- Market Signals: NSE's structured SAST data, monthly mutual fund portfolios, tenders.
