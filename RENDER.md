# Deploy Hearing Tracker on Render

This folder is meant to be its **own Git repository** (the parent `Python` repo gitignores `hearing-tracker/`).

## What you get

- Git push → automatic redeploy
- Persistent disk at `/var/data` (hearings, feeds, API key)
- Background RSS pull every 60 minutes (configurable)
- Single Gunicorn worker (safe for JSON file storage)

Estimated cost: **~$7/month** (Starter web service + 1 GB disk). No reliable free option for persistent data + always-on RSS.

---

## 1. Create a GitHub repo

```bash
cd hearing-tracker
git init
git add .
git commit -m "Initial hearing tracker deploy"
git branch -M main
git remote add origin https://github.com/YOUR_ORG/jf-hearing-tracker.git
git push -u origin main
```

Do **not** commit secrets. `congress_api.json` is gitignored; set the API key in the app after deploy (Feeds page).

---

## 2. Connect Render

1. [dashboard.render.com](https://dashboard.render.com) → **New** → **Blueprint**
2. Connect the GitHub repo (repo root = this `hearing-tracker` folder)
3. Render reads `render.yaml` and creates the web service + disk
4. Wait for the first deploy to finish

Your URL will look like: `https://hearing-tracker-xxxx.onrender.com`

---

## 3. First-run checks

| Check | How |
|--------|-----|
| Site loads | Open the Render URL → dashboard |
| Data seeded | Logs should show no errors; `/var/data/hearings.json` created from repo copy on first boot |
| Congress.gov API | Feeds → paste API key (stored on disk) |
| RSS auto-pull | Logs: `[RSS auto-pull]` after ~10s, then hourly |

---

## 4. Environment variables (optional)

Set in Render → **Environment**:

| Variable | Default | Purpose |
|----------|---------|---------|
| `DATA_DIR` | `/var/data` | Persistent JSON location (set in `render.yaml`) |
| `FLASK_SECRET_KEY` | auto-generated | Session/flash security |
| `RSS_AUTO_PULL` | `1` | `0` to disable background import |
| `RSS_PULL_INTERVAL_MINUTES` | `60` | Minutes between auto-pulls |
| `RSS_AUTO_PULL_INITIAL_DELAY_SEC` | `10` | Delay before first pull |

---

## 5. Local dev (unchanged)

```bash
cd hearing-tracker
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python app.py
```

Open http://localhost:5001

To mimic Render locally:

```bash
mkdir -p data
export DATA_DIR="$(pwd)/data"
export FLASK_SECRET_KEY=dev
gunicorn app:app --bind 127.0.0.1:5001 --workers 1
```

(`RENDER` is not set locally, so RSS auto-pull only runs via `python app.py`, not gunicorn, unless you `export RENDER=true`.)

---

## 6. Updates

Push to `main` on GitHub → Render rebuilds and redeploys. Data on the disk is preserved.

**Note:** With a persistent disk, deploys have a few seconds of downtime (Render stops the old instance before starting the new one).

---

## 7. Troubleshooting

- **Empty site / no hearings** — Disk not mounted or `DATA_DIR` wrong; confirm Starter plan + disk in service **Disks** tab.
- **Lost data after deploy** — Service on Free tier (ephemeral filesystem); upgrade to Starter + disk.
- **Duplicate RSS imports** — Keep `--workers 1` in `startCommand` (already set in `render.yaml`).
- **Build fails** — Check `PYTHON_VERSION` matches a [supported Render version](https://render.com/docs/python-version).

---

## Manual setup (no Blueprint)

If you prefer the UI instead of `render.yaml`:

1. **New → Web Service** → connect repo
2. **Root Directory**: leave blank (repo root = `hearing-tracker`)
3. **Build**: `pip install -r requirements.txt`
4. **Start**: `gunicorn app:app --bind 0.0.0.0:$PORT --workers 1 --timeout 120`
5. **Disks** → Add disk, mount `/var/data`, 1 GB
6. **Env**: `DATA_DIR=/var/data`, generate `FLASK_SECRET_KEY`
