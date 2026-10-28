# Step 27: Packaging

**Goal:** someone with only Docker Desktop can start the system with a double-click. Step 5 of the [sharing plan](../design/sharing.md).

## Decisions

The author chose the **MIT licence** and to **keep the repository private** for now. Two parts of the plan wait for a public repository:
- **A prebuilt image:** on a private repository it would be private too, so every user would need a GitHub token to pull it. The start script builds the image on the user's computer instead, which takes a few minutes the first time.
- **Untracking the author's watchlist:** `git rm --cached` would delete the file from the author's Mac on the next pull. Before going public, the file comes out of the Git history, and `config/watchlist.example.yaml` takes its place.

## What was added

| Piece | Why |
| --- | --- |
| `start.command`, `start.bat` | Check Docker is running, `docker compose up -d --build`, wait for the dashboard, open it |
| `stop.command`, `stop.bat` | `docker compose stop`; the data is kept |
| `docker-compose.yml` | See below |
| `make start`, `make stop` | The same, for developers |
| `LICENSE` | MIT |
| `config/watchlist.example.yaml` | Five large companies, for `sna watchlist load` |
| `.gitattributes` | Windows line endings for the `.bat` files, Unix ones for the `.command` files |
| README | A quick start at the top; the developer setup below it; a licence and data note |
| Guide | Starting, stopping and updating with the scripts; problems in the same terms |
| Dashboard | Pages that said "run `make prices`" or "`sna events run`" now name the job to run on System |

## The compose file

- **One `docker compose up`** starts everything: the database, then a `migrate` service that runs `sna db upgrade` and exits, then the dashboard and the scheduler, which wait for `migrate` to finish without error. The dashboard and scheduler no longer need `--profile`. `app` (the health check) moved to a `tools` profile, so it doesn't start with the rest.
- **The project name is pinned** to `stock_news_analyzer`, so the data volume keeps its name whatever the folder is called. That matters when someone unzips a new version into a differently named folder. It is also the name the author's existing volume already has.
- **The dashboard listens on 127.0.0.1 only,** so other machines on the same Wi-Fi can't open it.

## Tests

- **`tests/test_watchlist.py`:**
  - the example watchlist loads without crashing
  - the compose file starts the dashboard and scheduler after the migrations, without profiles, on 127.0.0.1, under the pinned name
- **CI:** the Docker job now runs `docker compose up -d --build` as the start script does, then checks that the dashboard answers on `/_stcore/health`, that `migrate` exited with 0 and that the scheduler is running.

The sandbox can't build the image (the container registry is blocked), so CI is the first full run of the compose file.

## On the Mac

You run the dashboard with `make ui` and the scheduler with `make scheduler`, and those still work. To try the start script:

```
git checkout main
git pull
make scheduler-stop
```

Stop `make ui` too (Ctrl+C in its Terminal window), so port 8501 is free. Then double-click **start.command** in the project folder. If Finder blocks it the first time, right-click it and choose Open.
