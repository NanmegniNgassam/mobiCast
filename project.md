# MobiCast - Agent AI Prompts
## Step-by-step implementation sequence

---

## Global context block

> Paste this at the top of every prompt if the agent has no session memory.

```
You are building MobiCast, a Python web application (Dash + Plotly) for the Studelecta
commercial team. The app runs locally via Docker. It allows users to run analyses of
African student mobility flows to Europe, visualize results, and access analysis history.
Persistence is handled by SQLite. Existing code lives in the project folder.
Each prompt corresponds to a single distinct commit.

CONVENTIONS (non-negotiable):
- All code, variable names, function names, class names, dict keys, database table
  and column names, and comments must be in English.
- UI labels, button text, and user-facing strings remain in French (end users are French-speaking).
- Follow PEP 8. Use snake_case for variables and functions, PascalCase for classes.
- No print() statements in production code. Use Python logging instead.
- All functions must have a docstring.
```

---

## PROMPT 01 - Project scaffolding

```
Create the full project structure for MobiCast, a Dash application.

Expected structure:
mobicast/
├── app.py                  # Dash entry point
├── config.py               # Environment variables and constants
├── docker-compose.yml
├── Dockerfile
├── requirements.txt
├── assets/
│   └── style.css           # Empty CSS file, to be filled later
├── components/             # Reusable Dash components (empty folder with __init__.py)
├── pages/                  # Application views (empty folder with __init__.py)
├── pipeline/               # Data business logic (empty folder with __init__.py)
├── data/
│   └── defaults/           # Bundled reference files (empty folder with .gitkeep)
└── db/
    └── database.py         # SQLite connection module (empty for now)

Constraints:
- app.py initializes a Dash app with use_pages=True and suppressed exceptions in production
- config.py reads SECRET_KEY, DATABASE_PATH and DATA_DIR from environment variables
  with sensible defaults for local development
- Dockerfile uses python:3.11-slim, installs dependencies and exposes port 8050
- docker-compose.yml mounts two volumes: one for /app/data (analysis persistence)
  and one for /app/db (SQLite persistence)
- requirements.txt includes: dash, plotly, pandas, scikit-learn, flask-login, werkzeug,
  gunicorn, openpyxl
- No business logic in this commit, only structure and configuration
- All comments in app.py and config.py must be in English
```

---

## PROMPT 02 - SQLite schema and data access layer

```
Implement the SQLite schema and data access layer in db/database.py.

Schema to create (auto-initialized on startup if tables do not exist):

Table users:
- id INTEGER PRIMARY KEY AUTOINCREMENT
- username TEXT UNIQUE NOT NULL
- password_hash TEXT NOT NULL
- created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP

Table analyses:
- id INTEGER PRIMARY KEY AUTOINCREMENT
- name TEXT NOT NULL
- user_id INTEGER REFERENCES users(id)
- created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
- row_count INTEGER
- status TEXT DEFAULT 'running'   -- 'running', 'done', 'error'
- sources_folder TEXT             -- path to /data/analyses/{id}/

Table source_files:
- id INTEGER PRIMARY KEY AUTOINCREMENT
- analysis_id INTEGER REFERENCES analyses(id)
- source_type TEXT NOT NULL       -- 'unesco', 'oecd', 'erasmus', 'default_oecd', 'default_erasmus'
- file_name TEXT NOT NULL
- file_path TEXT NOT NULL

Functions to expose in database.py:
- get_connection() -> sqlite3.Connection : returns a connection with row_factory = sqlite3.Row
- init_db() -> None : creates tables if they do not exist, inserts a default admin user
  (username: admin, password: admin) if the users table is empty
- Basic CRUD helpers for each table (get_by_id, insert, update_status)

Constraints:
- init_db() is called in app.py on startup
- Database path is read from config.py
- Use bound parameters (no f-strings) for all queries
- All comments and docstrings in English
```

---

## PROMPT 03 - Authentication and session management

```
Implement authentication for the MobiCast Dash application.

Files to create or modify:
- pages/login.py         : login view
- components/auth.py     : authentication logic and route protection
- app.py                 : global protection integration

Login page (pages/login.py):
- Username and password fields
- "Se connecter" button
- Error message on invalid credentials
- Real-time clock display updated every second (dcc.Interval)
- On successful login: redirect to /analyses/new
- URL: /login

Route protection (components/auth.py):
- Use flask-login for session management
- All pages except /login require authentication
- A global callback in app.py intercepts every URL change and redirects
  to /login if the user is not authenticated
- Store in session: user_id, username, login_time

Global layout (app.py):
- Top navigation bar visible on all authenticated pages:
  application name on the left, username + login time + logout button on the right
- Navbar is hidden on the /login page
- Use dcc.Location and dcc.Store for navigation and state management

Style: clean and functional. No bright colors. Light background, sharp typography.
All code, variable names, and comments in English. UI strings remain in French.
```

---

## PROMPT 04 - Cleaning pipeline extraction

```
Extract the cleaning logic from the notebook into a reusable Python module.

File to create: pipeline/cleaning.py

This module must faithfully reproduce the logic from nettoyage_du_dataset.ipynb
and adapt it for programmatic use.

Main function to expose:
clean_and_merge(
    unesco_path: str,
    oecd_path: str | None,
    erasmus_paths: list[str] | None
) -> tuple[pd.DataFrame, dict]

- If oecd_path is None, use config.DEFAULT_OECD_PATH
- If erasmus_paths is None or empty list, use config.DEFAULT_ERASMUS_PATHS
- The returned dict contains cleaning statistics:
  {
    "row_count": int,
    "duplicates_removed": int,
    "values_imputed": int,
    "origin_countries": list,
    "destination_countries": list,
    "years_covered": list
  }

Automatic column detection for each source:
- UNESCO: look for columns containing 'geounit' (case-insensitive) for country,
  'year' for year, 'value' for the numeric value, filter on indicatorId == 26420
- OECD: look for 'donor' for destination, 'recipient' for origin,
  'time_period' or 'year' for year, 'obs_value' or 'value' for amount
- Erasmus+: existing notebook behavior (fuzzy match on 'coordinat'+'country',
  'participat'+'countr', 'year')

Raise an explicit ColumnDetectionError if mandatory columns are not found,
with the source name and expected columns in the message.

Constraints:
- No print() statements, only return values and exceptions
- No side effects (no file writes inside this function)
- Business logic (interpolation, geographic filtering, ISO codes) must be
  identical to the notebook
- All variable names, comments, and docstrings in English
```

---

## PROMPT 05 - Analysis and prediction pipeline extraction

```
Extract the analysis and prediction logic from the notebook into a reusable Python module.

File to create: pipeline/analysis.py

Main function to expose:
run_analysis(df: pd.DataFrame) -> dict

The returned dict has the following structure:
{
  "predictions": [
    {
      "country_code": "FRA",
      "country_name": "France",
      "historical_years": [2017, 2018, ...],
      "historical_values": [5650.0, 4761.0, ...],
      "forecast_years": [2024, 2025, 2026, 2027, 2028],
      "forecast_values": [8100.0, ...],
      "r2": 0.87,
      "mae": 312.4,
      "coefficient": 410.2,
      "intercept": -820000.1
    },
    ...
  ],
  "correlations": {
    "FRA": {
      "matrix": [[1.0, 0.72, ...], ...],
      "columns": ["Year", "Scholarship_Amount_MUSD", "African_Students_Count"]
    },
    ...
  },
  "rankings": {
    "2024": [{"country_code": "FRA", "country_name": "France", "students": 8100}, ...],
    "2025": [...],
    ...
  },
  "available_origin_countries": [{"code": "CMR", "name": "Cameroun"}, ...],
  "available_destination_countries": [{"code": "FRA", "name": "France"}, ...]
}

Constraints:
- Faithfully reproduce the logic from analyse_et_prediction.ipynb
- One distinct LinearRegression model per destination country
- Forecast years: 2024 to 2028
- No matplotlib or seaborn, only raw computed data
- No print() statements, no side effects
- All variable names, comments, and docstrings in English
```

---

## PROMPT 06 - New analysis view: form and file upload

```
Create the new analysis launch view.

File to create: pages/new_analysis.py
URL: /analyses/new

Interface to build:

Section 1 - Analysis information:
- Text field "Nom de l'analyse" (required, placeholder: ex. "Q2 2026 - Mise à jour UNESCO")

Section 2 - Data sources:
- UNESCO slot (required): dcc.Upload component labeled "Fichier UNESCO (data.csv)"
  with a "Obligatoire" badge
- OECD slot (optional): dcc.Upload labeled "Fichier OCDE (bourses)"
  with note "Optionnel - fichier de référence utilisé si non fourni"
- Erasmus+ slot (conditional):
    - Checkbox "Mettre à jour la matrice Erasmus+" unchecked by default
    - When checked, show a warning banner:
      "Ce fichier définit les paires de pays utilisées par le modèle. Une mise à jour
       incorrecte peut affecter les résultats. Fournissez uniquement un export officiel
       KA1 du portail Erasmus+. Ce fichier sera utilisé uniquement pour cette analyse
       et ne remplacera pas le fichier de référence."
    - Then show the Erasmus+ dcc.Upload component

"Valider les fichiers" button:
- Active only when name is filled AND UNESCO file is uploaded
- Triggers file saving to /data/tmp/{session_id}/ and redirects to
  the validation step (next prompt)

Constraints:
- Files uploaded via dcc.Upload arrive as base64-encoded strings in Dash,
  decode and save them temporarily to /data/tmp/{session_id}/
- Use dcc.Store to persist temporary file paths between steps
- Client-side validation: button stays disabled until required fields are filled
- All variable names, callback IDs, and comments in English
- UI labels and user-facing strings in French
```

---

## PROMPT 07 - New analysis view: visual validation step

```
Create the visual validation step before launching the analysis.

File to modify: pages/new_analysis.py
(add a second step controlled by a dcc.Store named "current-step")

This step is shown after file validation (prompt 06).

Interface to build:

For each provided file (UNESCO required, OECD and Erasmus+ if provided):
- Source title (e.g., "Source UNESCO")
- Preview table of the first 5 rows (dash_table.DataTable)
- List of detected columns with their identified role:
  e.g., "geoUnit -> Pays de destination | year -> Année | value -> Volume étudiants"
- If automatic column detection fails: show a dcc.Dropdown listing all columns
  in the file so the user can map manually
- Green badge "Détection réussie" or orange badge "Vérification requise"

"Lancer l'analyse" button:
- Active only when all required columns are mapped (auto or manually)
- Triggers the full pipeline (cleaning + analysis) via a dcc.Interval
  and shows a progress bar with the current step label

Progress steps to display:
1. "Lecture et validation des fichiers..."
2. "Nettoyage et fusion des sources..."
3. "Entraînement des modèles par pays..."
4. "Génération des classements et projections..."
5. "Sauvegarde de l'analyse..."

On completion:
- Save the analysis to the database (tables analyses + source_files)
- Copy source files from /data/tmp/ to /data/analyses/{id}/
- Save the result dict from run_analysis() as JSON to /data/analyses/{id}/results.json
- Delete /data/tmp/{session_id}/
- Automatically redirect to /analyses/{id}

Constraints:
- All variable names, callback IDs, and comments in English
- UI labels and user-facing strings in French
```

---

## PROMPT 08 - Results view: correlations

```
Create the first block of the results view: the correlation heatmap.

File to create: pages/results.py
URL: /analyses/{id}

This file will contain all three result blocks (correlations, predictions, rankings).
This prompt implements the correlations block only. The other two will be added
in the following prompts.

Page layout:
- Header: analysis name, date, author, number of rows processed
- Tabs (dcc.Tabs): "Corrélations" | "Prédictions" | "Classements"
- Source files section: list of files used with their type
  (e.g., "UNESCO fourni / OCDE par défaut"), each downloadable

Correlations block:
- Filter by destination country (dcc.Dropdown, multi-select, all selected by default)
- For each selected destination country: one Plotly heatmap (px.imshow)
  using columns Year, Scholarship_Amount_MUSD, African_Students_Count
- Heatmaps displayed in a responsive grid (2 columns when multiple countries)
- Correlation values shown inside cells
- Each heatmap title: full country name

Constraints:
- Load analysis data from SQLite using the id from the URL
- Analysis results (dict produced by pipeline/analysis.py) are stored
  as JSON in /data/analyses/{id}/results.json
- Read from this JSON file to feed the charts
- If the id does not exist in the database: show a simple 404 page
- All variable names, callback IDs, and comments in English
- UI labels in French
```

---

## PROMPT 09 - Results view: predictions

```
Add the predictions block to the results view (pages/results.py).

Predictions block (tab 2):

Filters:
- Destination country filter (dcc.Dropdown, multi-select)
- African origin country filter (dcc.Dropdown, multi-select)

Main chart (px.line):
- One line per selected destination country
- Historical data as solid line, forecasts as dashed line
- Vertical separator line at year 2024 with label "Prédictions"
- Interactive hover showing: year, country, value, and whether it is
  historical data or a forecast

When an origin country filter is active:
- Add a note below the chart stating that the origin country filter
  applies to historical data only (forecasts are at destination country level)

Model reliability table:
- One row per selected destination country
- Columns: Pays | R² (%) | Marge d'erreur (étudiants) | Interprétation
- Interpretation: "Fiable" if R² > 0.75, "Acceptable" between 0.5 and 0.75,
  "Faible" below
- Color the Interprétation cell by level (green / orange / red)

Constraints:
- Feed from results.json as in prompt 08
- No page reload on filter change, use Dash callbacks only
- All variable names, callback IDs, and comments in English
```

---

## PROMPT 10 - Results view: rankings

```
Add the rankings block to the results view (pages/results.py).

Rankings block (tab 3):

Year selector:
- dcc.Slider or horizontal dcc.RadioItems covering 2024 to 2028
- Forecast years visually distinct from historical ones

Ranking table for the selected year:
- Columns: Rang | Pays de destination | Étudiants africains estimés | Évolution vs N-1
- Special formatting for top 3 ranks
- Evolution displayed with a colored arrow (green for increase, red for decrease)
- Relative progress bar in the "Étudiants" column to visualize gaps between countries

Global indicator:
- Total estimated for the selected year (sum across all countries)
- Total variation vs the previous year

Constraints:
- Feed from results.json
- Rankings update instantly on year change via a Dash callback, no reload
- All variable names, callback IDs, and comments in English
- UI labels in French
```

---

## PROMPT 11 - Analysis history view

```
Create the analysis history view.

File to create: pages/history.py
URL: /analyses

Interface:
- Title "Historique des analyses"
- "Nouvelle analyse" button top-right, redirects to /analyses/new

Past analyses table:
- Columns: Nom | Date | Auteur | Lignes traitées | Sources utilisées | Statut | Actions
- "Sources utilisées": compact list of source types
  (e.g., "UNESCO fourni + OCDE défaut")
- "Statut": colored badge (green "Terminée", orange "En cours", red "Erreur")
- "Actions": "Voir les résultats" button redirecting to /analyses/{id}

Default sort: descending date (most recent analysis first)

If no analyses exist yet: empty state message with
"Lancer votre première analyse" button

Constraints:
- Data loaded from SQLite (tables analyses + users + source_files)
- The "Sources utilisées" column is built by aggregating source_type values
  from the source_files table for each analysis
- Pagination if more than 20 analyses (dash_table.DataTable with page_size=20)
- All variable names, callback IDs, and comments in English
- UI labels in French
```

---

## PROMPT 12 - Results export

```
Add export functionality to the results view (pages/results.py).

Export section (at the bottom of the results page, below the tabs):

Available exports:
- "Exporter les prédictions (CSV)": table of all forecasts 2024-2028
  for all countries, with columns Année, Pays, Étudiants estimés, R², MAE
- "Exporter les classements (CSV)": rankings table across all years
- "Exporter le graphique prédictions (PNG)": capture of the active chart
  in the Predictions tab
- "Exporter les heatmaps (PNG)": capture of the active heatmaps
  in the Correlations tab

Implementation:
- CSV exports: use dcc.Download with a callback that generates the CSV
  in memory (io.StringIO) from results.json
- PNG exports: use plotly.io.to_image (requires kaleido in requirements.txt)
  with dcc.Download

Constraints:
- CSV exports include a header row with the analysis name and date
- Generated file names follow the pattern:
  mobicast_{analysis_name}_{export_type}_{date}.csv
  (replace spaces with underscores, force lowercase)
- Add kaleido to requirements.txt and Dockerfile
- All variable names, callback IDs, and comments in English
```

---

## PROMPT 13 - Docker finalization and local production setup

```
Finalize Docker configuration for a stable local production deployment.

Changes to apply:

Dockerfile:
- Use python:3.11-slim as base
- Copy reference files (OECD and Erasmus+) into /app/data/defaults/
  during the build (they must be present in data/defaults/ in the project folder)
- Launch the application with gunicorn (not the Dash development server):
  gunicorn --workers 2 --bind 0.0.0.0:8050 app:server
- Create /app/data/analyses/ and /app/db/ directories in the Dockerfile
  so Docker volumes mount correctly

docker-compose.yml:
- Single service "mobicast"
- Named volumes: mobicast_data -> /app/data, mobicast_db -> /app/db
- SECRET_KEY environment variable with an example value in the file
- Port 8050:8050
- restart: unless-stopped

config.py:
- Verify all required constants are read from environment variables
  with clear fallbacks
- Add DEFAULT_OECD_PATH and DEFAULT_ERASMUS_PATHS pointing to /app/data/defaults/

README.md to create with:
- Prerequisites (Docker and Docker Compose)
- Startup instructions in 3 commands: git clone, place reference files
  in data/defaults/, docker compose up
- Default credentials (admin / admin) and instructions to change them
- Brief description of the 3 expected data sources and where to download them
  (UNESCO portal, OECD portal, Erasmus+ portal)

All comments in English.
```

---

## Recommended execution order

```
01 -> 02 -> 03 -> 04 -> 05 -> 06 -> 07 -> 08 -> 09 -> 10 -> 11 -> 12 -> 13
```

Each prompt assumes all previous ones are committed and working.
Prompts 04 and 05 (pipeline) can be run in parallel with prompts 06/07 (UI)
if two agent sessions are available, but must be merged before prompt 08.
