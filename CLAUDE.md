# MobiCast — Project Context for Claude Code

## What is MobiCast?

A **Dash + Plotly** web application for Studelecta's commercial team.  
Runs locally via **Docker** (single container, port 8050).  
Purpose: run analyses of African student mobility flows to Europe, visualise
results (correlations, predictions, rankings), and access analysis history.  
Persistence: **SQLite** (no external DB server).

---

## Non-negotiable conventions

| Rule | Detail |
|------|--------|
| **Language** | All code, variable names, function names, class names, dict keys, DB table/column names, and comments → **English** |
| **UI strings** | All labels, button text, user-facing strings → **French** |
| **Style** | PEP 8 · `snake_case` variables/functions · `PascalCase` classes |
| **Logging** | No `print()` — use Python `logging` exclusively |
| **Docstrings** | Every function must have one |

---

## Tech stack

- Python 3.11
- Dash 2.x + Plotly 5.x
- pandas, scikit-learn (LinearRegression, one model per destination country)
- flask-login + werkzeug (auth)
- SQLite via stdlib `sqlite3`
- gunicorn (2 workers, production server)
- Docker / docker-compose (single service)

---

## Project structure

```
mobiCast/
├── app.py                  # Dash entry point; exposes app:server for gunicorn
├── config.py               # All env vars + derived paths
├── CLAUDE.md               # ← this file
├── project.md              # Full 13-prompt implementation plan
├── Dockerfile              # python:3.11-slim, gunicorn, port 8050
├── docker-compose.yml      # Named volumes: mobicast_data→/app/data, mobicast_db→/app/db
├── requirements.txt
├── assets/
│   └── style.css           # Global CSS (login, navbar, cards, form, upload, badges)
├── components/
│   └── auth.py             # LoginManager, User(UserMixin), authenticate_user, sign_out
├── pages/
│   ├── login.py            # /login — username/password form, auth callback
│   └── new_analysis.py     # /analyses/new — step 1: form+upload  step 2: TODO (prompt 07)
├── pipeline/
│   ├── cleaning.py         # clean_and_merge(), ColumnDetectionError, detect_columns()
│   └── analysis.py         # run_analysis() → predictions/correlations/rankings dict
├── data/
│   └── defaults/           # Bundled OECD + Erasmus reference files (.gitkeep)
└── db/
    └── database.py         # SQLite DAL (schema + CRUD helpers)
```

---

## config.py — key constants

| Constant | Env var | Default |
|----------|---------|---------|
| `SECRET_KEY` | `SECRET_KEY` | `dev-secret-key-…` |
| `DATABASE_PATH` | `DATABASE_PATH` | `/app/db/mobicast.db` |
| `DATA_DIR` | `DATA_DIR` | `/app/data` |
| `DEBUG` | `DEBUG` | `false` |
| `DEFAULTS_DIR` | — | `DATA_DIR/defaults` |
| `DEFAULT_OECD_PATH` | — | `DEFAULTS_DIR/oecd_scholarships.csv` |
| `DEFAULT_ERASMUS_PATHS` | — | `[DEFAULTS_DIR/erasmus_mobility.xlsx]` |
| `TMP_DIR` | — | `DATA_DIR/tmp` |
| `ANALYSES_DIR` | — | `DATA_DIR/analyses` |

---

## db/database.py — schema

```sql
users        (id, username UNIQUE, password_hash, first_name, last_name, created_at)
analyses     (id, name, user_id→users, created_at, row_count,
              status DEFAULT 'running', sources_folder)
source_files (id, analysis_id→analyses, source_type, file_name, file_path)
```

`source_type` values: `'unesco'` | `'oecd'` | `'erasmus'` | `'default_oecd'` | `'default_erasmus'`  
Analysis `status` values: `'running'` | `'done'` | `'error'`

**Exposed functions:**  
`get_connection()`, `init_db()` (calls `_apply_migrations` for forward-only column adds),  
`get_user_by_id`, `get_user_by_username`, `insert_user(username, password_hash, first_name, last_name)`,  
`get_analysis_by_id`, `get_all_analyses`, `insert_analysis`, `update_analysis_status`,  
`get_source_files_by_analysis_id`, `insert_source_file`

`init_db()` uses `INSERT OR IGNORE` for the default admin seed to avoid a race
condition when gunicorn boots multiple workers simultaneously.

---

## components/auth.py — authentication

- `LoginManager` from flask-login, attached to the Flask server via `init_login_manager(server)`
- `User(UserMixin)` wraps the SQLite row; `login_time` stored in `flask.session`; exposes `display_name` property (full name or username fallback)
- `PUBLIC_PATHS = {"/login"}` — routes that do not require authentication
- `authenticate_user(username, password) → User | None` — verifies hash, calls `login_user`
- `sign_out()` — calls `logout_user`, clears `flask.session["login_time"]`

---

## app.py — root layout and callbacks

**Layout components (always in DOM):**

| ID | Purpose |
|----|---------|
| `url` | `dcc.Location(refresh=False)` — current pathname |
| `redirect` | `dcc.Location(refresh=True)` — triggers full-page reload when `href` is set |
| `session-store` | `dcc.Store(storage_type="session")` — client-side session cache |
| `navbar` | `html.Nav` — toggled via CSS class `navbar--hidden` |
| `navbar-user-info` | `html.Span` — displays `"{username} · connecté à {HH:MM}"` |
| `logout-button` | `html.Button` — always in DOM (required for callback registration) |

**Callbacks:**

| Callback | Trigger | Output |
|----------|---------|--------|
| `protect_routes` | `url.pathname` | `redirect.href` → `/login` if unauthenticated; `/analyses/new` if pathname=`/` |
| `update_navbar` | `url.pathname` | `navbar.className` + `navbar-user-info.children` |
| `handle_logout` | `logout-button.n_clicks` | `redirect.href` → `/login` (allow_duplicate=True) |

`suppress_callback_exceptions=True` is set app-wide (required for dynamic components
in multi-page apps and for `allow_duplicate` outputs).

---

## pages/login.py

- URL: `/login`
- Simple form: username + password, no clock (removed — no real utility)
- Login callback outputs to **`redirect`** (root layout component) with `allow_duplicate=True`
- On success → `href = "/analyses/new"` (full page reload via `refresh=True`)
- On failure → error message in `#login-error`
- Enter key supported via `n_submit` on both inputs

---

## pages/new_analysis.py

- URL: `/analyses/new`
- `layout` is a **function** (not a variable) — generates a fresh `session_id = uuid4().hex` on each visit
- **Step 1** (PROMPT 06 — done): analysis name + file upload form
  - `dcc.Store(id="current-step")` controls which step is visible
  - `dcc.Store(id="upload-state")` holds saved file paths passed to step 2
  - `dcc.Store(id="new-analysis-session")` holds the per-visit UUID
  - UNESCO upload required; OECD optional; Erasmus+ conditional on a checkbox
  - "Valider les fichiers →" button disabled until name + UNESCO file provided
  - On click: base64-decodes files, saves to `TMP_DIR/{session_id}/`, advances `current-step` to 2
- **Step 2** (PROMPT 07 — done): visual column validation + pipeline progress bar

---

## pipeline/cleaning.py

**Public API:**
- `clean_and_merge(unesco_path, oecd_path=None, erasmus_paths=None) → (df, stats)`
  - Returns `df` with columns: `year, destination_code, destination_name, origin_code, origin_name, student_count, scholarship_musd`
  - Returns `stats` dict: `{row_count, duplicates_removed, values_imputed, origin_countries, destination_countries, years_covered}`
- `detect_columns(df, source_type) → dict` — used by the UI validation step to preview column mapping before launching
- `ColumnDetectionError` — raised when a mandatory column can't be auto-detected; message names the source + patterns tried

**Column detection patterns:**
- UNESCO: `geounit` → origin country; `year` → year; `value` → student count; filters `indicatorId == 26420`
- OECD: `donor` → destination; `time_period`/`year` → year; `obs_value`/`value` → scholarship amount
- Erasmus+: `coordinat` → coordinator country (destination); `participat` → participant country (origin)

**Merge strategy:** If UNESCO has a host/destination column, use it directly. Otherwise expand via Erasmus+ pairs and distribute counts proportionally.

**Constants exported:** `AFRICAN_ISO3`, `EUROPEAN_ISO3`, `ISO3_TO_NAME` (used by analysis.py)

---

## pipeline/analysis.py

**Public API:**
- `run_analysis(df) → dict` — takes output of `clean_and_merge()`, returns full result dict
- `FORECAST_YEARS = [2024, 2025, 2026, 2027, 2028]`
- `CORRELATION_COLUMNS = ["Year", "Scholarship_Amount_MUSD", "African_Students_Count"]`

**Result dict structure:**
```python
{
  "predictions": [{
    "country_code", "country_name",
    "historical_years", "historical_values",
    "forecast_years", "forecast_values",   # values clipped to >= 0
    "r2", "mae", "coefficient", "intercept"
  }, ...],                                 # sorted by last forecast value desc
  "correlations": {
    "FRA": {"matrix": [[...]], "columns": [...]}
  },
  "rankings": {
    "2024": [{"country_code", "country_name", "students"}, ...],  # sorted desc
    ...
  },
  "available_origin_countries":      [{"code", "name"}, ...],
  "available_destination_countries": [{"code", "name"}, ...]
}
```

Model: one `LinearRegression(Year → African_Students_Count)` per destination. Single coefficient → single feature.

---

## Docker

```bash
# First run
docker compose up --build

# Default credentials
username: admin
password: admin
```

Volumes are **named** (`mobicast_data`, `mobicast_db`) so data survives `docker compose down`.  
Use `docker compose down -v` to also wipe volumes (resets DB and analysis data).

---

## Implementation roadmap

| # | Prompt | Status | File(s) |
|---|--------|--------|---------|
| 01 | Project scaffolding | ✅ done | `app.py`, `config.py`, `Dockerfile`, `docker-compose.yml`, `requirements.txt`, skeleton dirs |
| 02 | SQLite schema + DAL | ✅ done | `db/database.py` |
| 03 | Auth + login page + navbar | ✅ done | `components/auth.py`, `pages/login.py`, `app.py`, `assets/style.css` |
| 04 | Cleaning pipeline | ✅ done | `pipeline/cleaning.py` |
| 05 | Analysis + prediction pipeline | ✅ done | `pipeline/analysis.py` |
| 06 | New analysis view — form + upload | ✅ done | `pages/new_analysis.py` (replace placeholder) |
| 07 | New analysis view — validation + progress | ✅ done | `pages/new_analysis.py` (extend) |
| 08 | Results view — correlations tab | ⬜ todo | `pages/results.py` |
| 09 | Results view — predictions tab | ⬜ todo | `pages/results.py` (extend) |
| 10 | Results view — rankings tab | ⬜ todo | `pages/results.py` (extend) |
| 11 | History view | ⬜ todo | `pages/history.py` |
| 12 | Export (CSV + PNG) | ⬜ todo | `pages/results.py` (extend), `requirements.txt` (add kaleido) |
| 13 | Docker finalization + README | ⬜ todo | `Dockerfile`, `docker-compose.yml`, `config.py`, `README.md` |

The full prompt text for each step lives in `project.md` at the project root.

---

## Key design patterns to continue

- **One callback per concern** — route guard, navbar, logout are separate callbacks
- **`redirect` Location in root layout** — all redirects (login success, logout, guard)
  go through this single component; use `allow_duplicate=True` on non-primary callbacks
- **CSS utility classes** — `card`, `page-header`, `page-title`, `btn-primary`,
  `btn-secondary`, `badge badge--{green|orange|red|blue}` are defined in `style.css`
- **`analyses/{id}/results.json`** — completed pipeline results are stored as JSON
  under `ANALYSES_DIR/{id}/results.json`; result pages read from this file, not the DB
- **No f-strings in SQL** — always use bound parameters `(?, ?, …)`
