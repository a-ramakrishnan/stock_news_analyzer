# To do

Things decided but deliberately left for later, with what has to happen and why it waits.

## Going public (step 28)

Done in the code: `config/watchlist.yaml` is no longer tracked (`.gitignore`), the example watchlist explains the fields, the test watchlist marks no stock as owned, and the start script pulls the prebuilt image by default. Left, in this order:

1. **Remove the watchlist from the history:** `git filter-repo --path config/watchlist.yaml --invert-paths`, then force-push. Every other clone has to be cloned again. The old pull requests on GitHub keep their own copy of those commits; deleting them needs GitHub Support, or publishing from a new repository.
2. **Make the repository public:** Settings → General → Danger Zone → Change visibility.
3. **Make the image public:** your profile → Packages → stock_news_analyzer → Package settings → Change visibility.
4. **Release 0.1.0:** `make release VERSION=0.1.0`, then publish the release on GitHub with [the release notes](releases/0.1.0.md).

## Later

- **Email delivery** of the digest and high-severity red flags, as an option on Settings (each user's own mail account).
- **Try it on a clean Mac and a Windows machine** (step 29 of the [sharing plan](design/sharing.md)).
- Market Signals: NSE's structured SAST data, monthly mutual fund portfolios, tenders.
