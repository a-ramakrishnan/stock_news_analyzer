# Step 27: Packaging

**Goal:** someone with only Docker Desktop can start the system with a double-click. Step 5 of the [sharing plan](../design/sharing.md).

## Decisions

The author chose the **MIT licence** and to **keep the repository private** for now. Two parts of the plan wait for a public repository:
- **A prebuilt image:** on a private repository it would be private too, so every user would need a GitHub token to pull it. The start script builds the image on the user's computer instead, which takes a few minutes the first time.
- **Untracking the author's watchlist:** `git rm --cached` would delete the file from the author's Mac on the next pull. Before going public, the file comes out of the Git history, and `config/watchlist.example.yaml` takes its place.

## What was added

| Piece | Why |
| --- | --- |
| `start.command`, `start.bat` | Open Docker Desktop if it isn't running and wait for it, `docker compose up -d`, wait for the database and the dashboard, open it |
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

## Prebuilt image (added after the first merge)

The author asked for the prebuilt image anyway, private for now:
- **`.github/workflows/image.yml`** builds the image for linux/amd64 and linux/arm64 (Apple Silicon) and pushes it to `ghcr.io/a-ramakrishnan/stock_news_analyzer`:
  - a tag `v0.2.0` publishes `0.2.0` and `latest`
  - every push to main publishes `main`
  - each build also gets `sha-<commit>`
  - it can be run by hand from the Actions tab
  - layers are cached between runs
- **`make release VERSION=0.2.0`** tags a release.
- **Only builds when the image would change.** A push to main builds only when it touches what the image is made from: `src/`, `pyproject.toml`, `uv.lock`, the `Dockerfile`, `.streamlit/` or the workflow itself. Docs, tests, the README and the start scripts don't trigger a build. Release tags always build.
- **First run:** the merge of the workflow built and published `main` for both platforms in about 5½ minutes.
- **The compose file** names that image for every app service:
  - `pull_policy: ${SNA_PULL_POLICY:-build}` keeps building here by default
  - `SNA_PULL_POLICY=always` in `.env` pulls the newest instead; `SNA_VERSION` picks a release
  - the start scripts no longer pass `--build`, which would override the setting
- **While the repository is private,** pulling needs `docker login ghcr.io` with a token that can read packages.
- **docs/TODO.md** lists what waits for a public repository: taking the watchlist out of the history, and making the package public.


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

## Later: one command to start

The start scripts first only checked that Docker was running, and stopped if it wasn't. Now:
- **Docker Desktop:** opened if it isn't running (`open -a Docker` on a Mac; Docker Desktop's program on Windows), then up to 3 minutes' wait for it
- **The database:** waited for with `pg_isready`, so `uv run sna` commands work as soon as the script finishes
- **The dashboard:** a clear message, with the `docker compose logs` command to run, if the database or dashboard doesn't come up; the first version opened the browser anyway
- **`make start`:** runs `./start.command`, so Terminal and the double-click do the same thing

Checked in the sandbox: with Docker stopped and started 10 seconds later, the script waited, then went on to `docker compose up`; the database wait returned on its second try.
