# Step 28: Ready for others

**Goal:** a repository anyone can download and run, with nothing of the author's own in it. Step 28 of the [sharing plan](../design/sharing.md).

## What changed

| Piece | Why |
| --- | --- |
| `config/watchlist.yaml` untracked, in `.gitignore` | It was the author's own list, with the stocks held marked `owned: true`. Each person's own list now stays on their computer |
| `config/watchlist.example.yaml` | Now explains every field, as the old file's header did |
| `sna watchlist load` | Says to copy the example when `config/watchlist.yaml` is missing |
| Test watchlist | Marks no stock as owned; the two tests that need an owned stock set it themselves |
| Docs | Lines that said which stocks the author owns are reworded; company names stay as worked examples |
| `docker-compose.yml` | Pulls the prebuilt image by default (`SNA_PULL_POLICY=always`) |
| Start scripts | If the download fails, use the image already here; if there is none, build it from the folder's code |
| `.env.example`, CI | `SNA_PULL_POLICY=build`: a developer's copy, and CI, build the image from the code |
| [Release notes](../releases/0.1.0.md) | What it does, how to install and update, known limits |

## The history

Untracking the file only stops future commits from carrying it; every earlier commit still holds the list. So once this step is merged and the file is backed up on the Mac, the history is rewritten with `git filter-repo --path config/watchlist.yaml --invert-paths` and force-pushed, and the Mac's copy is cloned again. The steps are in [docs/TODO.md](../TODO.md).

## Checked in the sandbox

- 354 tests pass; the check of your own `config/watchlist.yaml` is skipped when a copy has none.
- `docker compose config` resolves `pull_policy: always` with no `.env` setting.
- The start script, with no internet for Docker: the download failed, then the local image (none), then the build, each with its message, and the database stayed up.

## On the Mac

Back up your watchlist before pulling: the pull deletes the tracked file from your folder. Your stocks are in the database too, so nothing is lost either way.

```
cp config/watchlist.yaml ~/watchlist-backup.yaml
git checkout main
git pull
cp ~/watchlist-backup.yaml config/watchlist.yaml
```

Add this line to your `.env`, so `make start` keeps building from your copy of the code:

```
SNA_PULL_POLICY=build
```
