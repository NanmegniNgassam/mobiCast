"""MobiCast — new analysis page (URL: /analyses/new).

Step 1: analysis name + file upload form.
Step 2: visual column validation + pipeline launch.

The two steps share the same page and are toggled via
dcc.Store(id="current-step").
"""

import base64
import json
import logging
import os
import shutil
import threading
import uuid
from pathlib import Path

import dash
import pandas as pd
from dash import ALL, Input, Output, State, callback, dash_table, dcc, html
from flask_login import current_user

from config import ANALYSES_DIR, DEFAULT_ERASMUS_PATHS, DEFAULT_OECD_PATH, TMP_DIR
from db.database import insert_analysis, insert_source_file, update_analysis_status
from pipeline.analysis import run_analysis
from pipeline.cleaning import clean_and_merge, detect_columns

logger = logging.getLogger(__name__)

dash.register_page(__name__, path="/analyses/new")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_PROGRESS_STEPS = 5

_SOURCE_LABELS: dict[str, str] = {
    "unesco": "Source UNESCO",
    "oecd": "Source OCDE",
    "erasmus": "Source Erasmus+",
}

_ROLE_LABELS: dict[str, str] = {
    "country": "Pays d'origine",
    "year": "Année",
    "student_count": "Volume étudiants",
    "destination": "Pays de destination",
    "scholarship_amount": "Montant bourses (MUSD)",
    "coordinator_country": "Pays coordinateur",
    "participant_country": "Pays participant",
}

# Roles that are optional (missing detection does not block the launch button).
_OPTIONAL_ROLES: frozenset[str] = frozenset({"year"})


# ---------------------------------------------------------------------------
# Step-1 helpers (unchanged from prompt 06)
# ---------------------------------------------------------------------------


def _upload_zone(component_id: str, accept: str, multiple: bool = False) -> dcc.Upload:
    """Return a styled dcc.Upload drag-and-drop zone.

    Args:
        component_id: Dash component ID.
        accept:       Accepted MIME types / extensions string.
        multiple:     Whether multiple files are allowed.
    """
    return dcc.Upload(
        id=component_id,
        accept=accept,
        multiple=multiple,
        className="upload-zone",
        children=html.Div(
            [
                html.Span("📂", className="upload-icon"),
                html.Span(
                    "Glisser-déposer ou cliquer pour sélectionner",
                    className="upload-label",
                ),
            ]
        ),
    )


def _source_slot(
    title: str,
    badge_text: str,
    badge_class: str,
    upload_component: dcc.Upload,
    filename_id: str,
    note: str | None = None,
) -> html.Div:
    """Return a complete source file slot (title + badge + note + upload + filename)."""
    children = [
        html.Div(
            className="source-slot-header",
            children=[
                html.Span(title, className="source-slot-title"),
                html.Span(badge_text, className=f"badge {badge_class}"),
            ],
        ),
    ]
    if note:
        children.append(html.P(note, className="source-slot-note"))
    children.append(upload_component)
    children.append(html.Div(id=filename_id, className="filename-display"))
    return html.Div(className="source-slot", children=children)


def _save_upload(contents: str, filename: str, session_id: str) -> str:
    """Decode a base64 Dash upload payload and persist it to the tmp directory.

    Args:
        contents:   Raw dcc.Upload contents string ("data:<mime>;base64,<data>").
        filename:   Original file name submitted by the browser.
        session_id: Unique identifier for this upload session.

    Returns:
        Absolute path of the saved file.
    """
    dest_dir = os.path.join(TMP_DIR, session_id)
    os.makedirs(dest_dir, exist_ok=True)

    _header, data = contents.split(",", 1)
    decoded = base64.b64decode(data)

    file_path = os.path.join(dest_dir, filename)
    with open(file_path, "wb") as fh:
        fh.write(decoded)

    logger.debug("Saved upload '%s' to %s", filename, file_path)
    return file_path


# ---------------------------------------------------------------------------
# Step-2 helpers — validation cards
# ---------------------------------------------------------------------------


def _read_file_preview(file_path: str) -> pd.DataFrame:
    """Read up to 100 rows from a CSV or Excel file for validation purposes.

    Args:
        file_path: Absolute path to the file.

    Returns:
        DataFrame with at most 100 rows.
    """
    ext = Path(file_path).suffix.lower()
    if ext in (".xlsx", ".xls"):
        return pd.read_excel(file_path, engine="openpyxl", nrows=100)
    return pd.read_csv(file_path, low_memory=False, nrows=100)


def _build_source_card(source_type: str, file_path: str) -> tuple[html.Div, bool]:
    """Build a validation card showing file preview and column detection status.

    Args:
        source_type: One of 'unesco', 'oecd', 'erasmus'.
        file_path:   Absolute path to the uploaded file.

    Returns:
        A (card_div, has_mandatory_failures) tuple where the boolean is True
        when at least one mandatory column could not be auto-detected.
    """
    filename = Path(file_path).name
    title = _SOURCE_LABELS.get(source_type, source_type.upper())

    try:
        df = _read_file_preview(file_path)
        preview_data = df.head(5).astype(str).to_dict("records")
        preview_cols = [{"name": str(c), "id": str(c)} for c in df.columns]
        mapping = detect_columns(df, source_type)
    except Exception as exc:
        logger.exception("Cannot load file for validation: %s", file_path)
        card = html.Div(
            className="card",
            children=[
                html.Div(className="validation-card-header", children=[
                    html.Span(f"{title} — {filename}", className="validation-source-title"),
                    html.Span("Erreur de lecture", className="badge badge--red"),
                ]),
                html.P(
                    f"Impossible de lire le fichier : {exc}",
                    className="form-error",
                    style={"marginTop": "8px"},
                ),
            ],
        )
        return card, True

    all_cols = [str(c) for c in df.columns]
    mapping_items: list = []
    has_mandatory_failures = False

    for role, col_name in mapping.items():
        role_label = _ROLE_LABELS.get(role, role)
        is_optional = role in _OPTIONAL_ROLES

        if col_name:
            mapping_items.append(
                html.Div(
                    className="column-mapping-item column-mapping-ok",
                    children=[
                        html.Span(role_label, className="column-mapping-role"),
                        html.Span(" → ", className="column-mapping-arrow"),
                        html.Code(col_name, className="column-mapping-col"),
                    ],
                )
            )
        else:
            if not is_optional:
                has_mandatory_failures = True
            mapping_items.append(
                html.Div(
                    className="column-mapping-item column-mapping-fail",
                    children=[
                        html.Span(
                            f"{role_label}{' (optionnel)' if is_optional else ''}",
                            className="column-mapping-role",
                        ),
                        html.Span(" → ", className="column-mapping-arrow"),
                        dcc.Dropdown(
                            id={"type": "col-override", "source": source_type, "role": role},
                            options=[{"label": c, "value": c} for c in all_cols],
                            placeholder=f"Sélectionner '{role_label}'…",
                            clearable=False,
                            className="column-mapping-dropdown",
                        ),
                    ],
                )
            )

    badge = (
        html.Span("Vérification requise", className="badge badge--orange")
        if has_mandatory_failures
        else html.Span("Détection réussie", className="badge badge--green")
    )

    card = html.Div(
        className="card",
        children=[
            html.Div(className="validation-card-header", children=[
                html.Span(f"{title} — {filename}", className="validation-source-title"),
                badge,
            ]),
            html.Details(
                className="preview-details",
                children=[
                    html.Summary("Aperçu (5 premières lignes)"),
                    dash_table.DataTable(
                        data=preview_data,
                        columns=preview_cols,
                        style_table={
                            "overflowX": "auto",
                            "maxHeight": "200px",
                            "overflowY": "auto",
                        },
                        style_cell={
                            "fontSize": "12px",
                            "padding": "4px 8px",
                            "whiteSpace": "nowrap",
                        },
                        style_header={"fontWeight": "600", "fontSize": "12px"},
                        page_action="none",
                    ),
                ],
            ),
            html.Div(className="column-mapping-list", children=mapping_items),
        ],
    )
    return card, has_mandatory_failures


# ---------------------------------------------------------------------------
# Pipeline progress helpers
# ---------------------------------------------------------------------------


def _progress_path(session_id: str) -> str:
    """Return the path to the per-session progress JSON file."""
    return os.path.join(TMP_DIR, session_id, "progress.json")


def _write_progress(
    session_id: str,
    step: int,
    label: str,
    *,
    done: bool = False,
    error: str | None = None,
    analysis_id: int | None = None,
) -> None:
    """Write pipeline progress to a JSON file readable by any gunicorn worker.

    Args:
        session_id:  Per-visit UUID.
        step:        Current step number (1-based).
        label:       Human-readable step description shown in the UI.
        done:        True when the pipeline has finished (success or error).
        error:       Error message string, or None on success.
        analysis_id: Database primary key of the created analysis (set on success).
    """
    path = _progress_path(session_id)
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(
                {
                    "step": step,
                    "total": _PROGRESS_STEPS,
                    "label": label,
                    "done": done,
                    "error": error,
                    "analysis_id": analysis_id,
                },
                fh,
            )
    except Exception:
        logger.exception("Cannot write progress file for session %s", session_id)


def _read_progress(session_id: str) -> dict | None:
    """Read the per-session progress JSON file; return None if absent."""
    path = _progress_path(session_id)
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except FileNotFoundError:
        return None
    except Exception:
        logger.exception("Cannot read progress file for session %s", session_id)
        return None


# ---------------------------------------------------------------------------
# Background pipeline thread
# ---------------------------------------------------------------------------


def _run_pipeline_thread(
    session_id: str,
    name: str,
    user_id: int,
    unesco_path: str,
    oecd_path: str | None,
    erasmus_paths: list[str],
) -> None:
    """Execute the full analysis pipeline and persist results.

    Writes step-by-step progress to a JSON file so the Dash Interval callback
    can display real-time status regardless of which gunicorn worker handles
    the polling request.

    Args:
        session_id:    Per-visit UUID used to locate tmp files.
        name:          Human-readable analysis label.
        user_id:       Authenticated user's primary key.
        unesco_path:   Path to the uploaded UNESCO CSV.
        oecd_path:     Path to the uploaded OECD file, or None to use the default.
        erasmus_paths: Paths to uploaded Erasmus+ files (empty list uses defaults).
    """
    analysis_id: int | None = None

    try:
        _write_progress(session_id, 1, "Lecture et validation des fichiers…")

        _write_progress(session_id, 2, "Nettoyage et fusion des sources…")
        df, stats = clean_and_merge(
            unesco_path,
            oecd_path=oecd_path,
            erasmus_paths=erasmus_paths if erasmus_paths else None,
        )

        _write_progress(session_id, 3, "Entraînement des modèles par pays…")
        results = run_analysis(df)

        _write_progress(session_id, 4, "Génération des classements et projections…")

        _write_progress(session_id, 5, "Sauvegarde de l'analyse…")

        analysis_id = insert_analysis(name, user_id)
        analysis_dir = os.path.join(ANALYSES_DIR, str(analysis_id))
        os.makedirs(analysis_dir, exist_ok=True)

        # Copy UNESCO file.
        dest = os.path.join(analysis_dir, os.path.basename(unesco_path))
        shutil.copy2(unesco_path, dest)
        insert_source_file(analysis_id, "unesco", os.path.basename(unesco_path), dest)

        # Copy OECD file or record default reference.
        if oecd_path:
            dest = os.path.join(analysis_dir, os.path.basename(oecd_path))
            shutil.copy2(oecd_path, dest)
            insert_source_file(analysis_id, "oecd", os.path.basename(oecd_path), dest)
        else:
            insert_source_file(
                analysis_id, "default_oecd",
                os.path.basename(DEFAULT_OECD_PATH), DEFAULT_OECD_PATH,
            )

        # Copy Erasmus+ files or record default references.
        if erasmus_paths:
            for ep in erasmus_paths:
                dest = os.path.join(analysis_dir, os.path.basename(ep))
                shutil.copy2(ep, dest)
                insert_source_file(analysis_id, "erasmus", os.path.basename(ep), dest)
        else:
            for dp in DEFAULT_ERASMUS_PATHS:
                insert_source_file(
                    analysis_id, "default_erasmus", os.path.basename(dp), dp,
                )

        # Persist pipeline results as JSON.
        results_path = os.path.join(analysis_dir, "results.json")
        with open(results_path, "w", encoding="utf-8") as fh:
            json.dump(results, fh, ensure_ascii=False, indent=2)

        update_analysis_status(
            analysis_id,
            status="done",
            row_count=stats["row_count"],
            sources_folder=analysis_dir,
        )

        logger.info("Pipeline completed successfully: analysis_id=%d", analysis_id)

        # Signal completion before deleting the tmp directory.
        _write_progress(
            session_id, 5, "Analyse terminée.",
            done=True, analysis_id=analysis_id,
        )

        # Remove the tmp session directory after a short delay so the next
        # interval tick can still read the completion status.
        def _deferred_cleanup() -> None:
            """Delete the session tmp directory."""
            tmp_dir = os.path.join(TMP_DIR, session_id)
            shutil.rmtree(tmp_dir, ignore_errors=True)
            logger.debug("Removed tmp dir: %s", tmp_dir)

        threading.Timer(3.0, _deferred_cleanup).start()

    except Exception as exc:
        logger.exception("Pipeline failed for session %s", session_id)
        if analysis_id is not None:
            try:
                update_analysis_status(analysis_id, status="error")
            except Exception:
                logger.exception("Cannot update analysis status to error")
        _write_progress(session_id, 0, "", done=True, error=str(exc))


# ---------------------------------------------------------------------------
# Layout
# ---------------------------------------------------------------------------


def layout() -> html.Div:
    """Build and return the new analysis page layout.

    Generates a fresh session_id UUID on each visit so concurrent users
    or repeated visits do not share upload state.
    """
    session_id = uuid.uuid4().hex

    return html.Div(
        children=[
            # Per-visit stores.
            dcc.Store(id="current-step", data=1),
            dcc.Store(id="upload-state", data={}),
            dcc.Store(id="new-analysis-session", data=session_id),
            dcc.Store(id="pipeline-state-store", data={"running": False}),
            # Interval for polling pipeline progress (disabled until pipeline starts).
            dcc.Interval(
                id="pipeline-interval",
                interval=800,
                n_intervals=0,
                disabled=True,
            ),

            # ── STEP 1 ──────────────────────────────────────────────────
            html.Div(
                id="step-1-container",
                children=[
                    html.Div(
                        className="page-header",
                        children=[html.H1("Nouvelle analyse", className="page-title")],
                    ),

                    # Section 1 — analysis name
                    html.Div(
                        className="card",
                        children=[
                            html.H2("1. Informations", className="section-title"),
                            html.Label(
                                "Nom de l'analyse",
                                htmlFor="analysis-name",
                                className="form-label",
                            ),
                            dcc.Input(
                                id="analysis-name",
                                type="text",
                                placeholder='ex. "Q2 2026 - Mise à jour UNESCO"',
                                className="form-input",
                                debounce=False,
                                n_submit=0,
                            ),
                        ],
                    ),

                    # Section 2 — data sources
                    html.Div(
                        className="card",
                        children=[
                            html.H2("2. Sources de données", className="section-title"),

                            _source_slot(
                                title="Fichier UNESCO (data.csv)",
                                badge_text="Obligatoire",
                                badge_class="badge--red",
                                upload_component=_upload_zone(
                                    "upload-unesco", ".csv,text/csv"
                                ),
                                filename_id="unesco-filename",
                            ),

                            html.Hr(className="source-divider"),

                            _source_slot(
                                title="Fichier OCDE (bourses)",
                                badge_text="Optionnel",
                                badge_class="badge--blue",
                                upload_component=_upload_zone(
                                    "upload-oecd", ".csv,.xlsx,text/csv"
                                ),
                                filename_id="oecd-filename",
                                note="Fichier de référence utilisé si non fourni.",
                            ),

                            html.Hr(className="source-divider"),

                            html.Div(
                                className="source-slot",
                                children=[
                                    dcc.Checklist(
                                        id="erasmus-toggle",
                                        options=[{
                                            "label": "  Mettre à jour la matrice Erasmus+",
                                            "value": "yes",
                                        }],
                                        value=[],
                                        className="erasmus-checkbox",
                                    ),
                                    html.Div(
                                        id="erasmus-upload-section",
                                        style={"display": "none"},
                                        children=[
                                            html.Div(
                                                className="warning-banner",
                                                children=[
                                                    html.Strong("⚠ Attention — "),
                                                    "Ce fichier définit les paires de pays "
                                                    "utilisées par le modèle. Une mise à jour "
                                                    "incorrecte peut affecter les résultats. "
                                                    "Fournissez uniquement un export officiel "
                                                    "KA1 du portail Erasmus+. Ce fichier sera "
                                                    "utilisé uniquement pour cette analyse et "
                                                    "ne remplacera pas le fichier de référence.",
                                                ],
                                            ),
                                            _upload_zone(
                                                "upload-erasmus", ".xlsx,.csv", multiple=True
                                            ),
                                            html.Div(
                                                id="erasmus-filename",
                                                className="filename-display",
                                            ),
                                        ],
                                    ),
                                ],
                            ),
                        ],
                    ),

                    html.Div(
                        className="action-row",
                        children=[
                            html.Div(id="validate-error", className="form-error"),
                            html.Button(
                                "Valider les fichiers →",
                                id="validate-files-btn",
                                n_clicks=0,
                                disabled=True,
                                className="btn-primary",
                            ),
                        ],
                    ),
                ],
            ),

            # ── STEP 2 ──────────────────────────────────────────────────
            html.Div(
                id="step-2-container",
                style={"display": "none"},
                children=[
                    html.Div(
                        className="page-header",
                        children=[
                            html.H1("Validation des données", className="page-title"),
                        ],
                    ),
                    # Dynamic validation cards populated by render_validation_cards.
                    html.Div(id="validation-cards-container"),
                    # Fixed action row — IDs must be stable for callbacks.
                    html.Div(
                        className="action-row",
                        style={"marginTop": "8px"},
                        children=[
                            html.Div(id="launch-error", className="form-error"),
                            html.Button(
                                "Lancer l'analyse",
                                id="launch-analysis-btn",
                                n_clicks=0,
                                disabled=True,
                                className="btn-primary",
                            ),
                        ],
                    ),
                    # Progress section — revealed when the pipeline starts.
                    html.Div(
                        id="progress-section",
                        className="progress-section",
                        style={"display": "none"},
                        children=[
                            html.Div(
                                id="progress-label",
                                className="progress-label",
                                children="Initialisation…",
                            ),
                            html.Div(
                                className="progress-bar-container",
                                children=[
                                    html.Div(
                                        id="progress-bar-fill",
                                        className="progress-bar-fill",
                                        style={"width": "0%"},
                                    )
                                ],
                            ),
                            html.Div(
                                className="progress-steps-list",
                                children=[
                                    html.Span(f"{i}. {lbl}", className="progress-step-item")
                                    for i, lbl in enumerate([
                                        "Lecture et validation des fichiers",
                                        "Nettoyage et fusion des sources",
                                        "Entraînement des modèles",
                                        "Classements et projections",
                                        "Sauvegarde",
                                    ], start=1)
                                ],
                            ),
                        ],
                    ),
                ],
            ),
        ]
    )


# ---------------------------------------------------------------------------
# Callbacks — step 1 (unchanged from prompt 06)
# ---------------------------------------------------------------------------


@callback(
    Output("erasmus-upload-section", "style"),
    Input("erasmus-toggle", "value"),
)
def toggle_erasmus_upload(value: list) -> dict:
    """Show or hide the Erasmus+ upload section based on the checkbox state."""
    return {} if value else {"display": "none"}


@callback(
    Output("validate-files-btn", "disabled"),
    Input("analysis-name", "value"),
    Input("upload-unesco", "contents"),
)
def update_validate_button(name: str | None, unesco_contents: str | None) -> bool:
    """Keep the validate button disabled until name + UNESCO file are both provided."""
    return not (name and name.strip() and unesco_contents)


@callback(
    Output("unesco-filename", "children"),
    Input("upload-unesco", "filename"),
)
def show_unesco_filename(filename: str | None) -> str:
    """Display the name of the uploaded UNESCO file."""
    return f"✓  {filename}" if filename else ""


@callback(
    Output("oecd-filename", "children"),
    Input("upload-oecd", "filename"),
)
def show_oecd_filename(filename: str | None) -> str:
    """Display the name of the uploaded OECD file."""
    return f"✓  {filename}" if filename else ""


@callback(
    Output("erasmus-filename", "children"),
    Input("upload-erasmus", "filename"),
)
def show_erasmus_filename(filename) -> str:
    """Display the name(s) of the uploaded Erasmus+ file(s)."""
    if not filename:
        return ""
    if isinstance(filename, list):
        return "  ·  ".join(f"✓  {f}" for f in filename)
    return f"✓  {filename}"


@callback(
    Output("upload-state", "data"),
    Output("current-step", "data"),
    Output("validate-error", "children"),
    Input("validate-files-btn", "n_clicks"),
    State("analysis-name", "value"),
    State("upload-unesco", "contents"),
    State("upload-unesco", "filename"),
    State("upload-oecd", "contents"),
    State("upload-oecd", "filename"),
    State("upload-erasmus", "contents"),
    State("upload-erasmus", "filename"),
    State("new-analysis-session", "data"),
    prevent_initial_call=True,
)
def handle_file_validate(
    _n_clicks,
    name,
    unesco_contents,
    unesco_filename,
    oecd_contents,
    oecd_filename,
    erasmus_contents,
    erasmus_filenames,
    session_id,
):
    """Decode and persist uploaded files, then advance to the validation step.

    Saves each file to /data/tmp/{session_id}/ and stores the resulting paths
    in the upload-state Store so the validation step can read them.
    """
    if not name or not name.strip():
        return dash.no_update, dash.no_update, "Veuillez saisir un nom d'analyse."
    if not unesco_contents:
        return dash.no_update, dash.no_update, "Le fichier UNESCO est obligatoire."

    try:
        unesco_path = _save_upload(unesco_contents, unesco_filename, session_id)

        oecd_path = None
        if oecd_contents and oecd_filename:
            oecd_path = _save_upload(oecd_contents, oecd_filename, session_id)

        erasmus_paths = []
        if erasmus_contents:
            contents_list = (
                erasmus_contents
                if isinstance(erasmus_contents, list)
                else [erasmus_contents]
            )
            names_list = (
                erasmus_filenames
                if isinstance(erasmus_filenames, list)
                else [erasmus_filenames]
            )
            for contents, fname in zip(contents_list, names_list):
                erasmus_paths.append(_save_upload(contents, fname, session_id))

        state = {
            "name":          name.strip(),
            "session_id":    session_id,
            "unesco_path":   unesco_path,
            "oecd_path":     oecd_path,
            "erasmus_paths": erasmus_paths,
        }

        logger.info(
            "Files validated for analysis '%s' (session %s)",
            name.strip(), session_id,
        )
        return state, 2, ""

    except Exception:
        logger.exception("File validation failed for session %s", session_id)
        return dash.no_update, dash.no_update, (
            "Erreur lors de la lecture des fichiers. "
            "Vérifiez les formats et réessayez."
        )


@callback(
    Output("step-1-container", "style"),
    Output("step-2-container", "style"),
    Input("current-step", "data"),
)
def route_steps(step: int) -> tuple[dict, dict]:
    """Show the active step container and hide the other."""
    if step == 1:
        return {}, {"display": "none"}
    return {"display": "none"}, {}


# ---------------------------------------------------------------------------
# Callbacks — step 2
# ---------------------------------------------------------------------------


@callback(
    Output("validation-cards-container", "children"),
    Output("launch-analysis-btn", "disabled"),
    Input("upload-state", "data"),
    prevent_initial_call=True,
)
def render_validation_cards(upload_state: dict) -> tuple[list, bool]:
    """Build validation cards for each uploaded source file.

    Called when the user advances from step 1 to step 2.  Reads each file,
    runs column detection, and returns one card per source plus the initial
    disabled state for the launch button.
    """
    if not upload_state or not upload_state.get("unesco_path"):
        return [], True

    cards = []
    has_any_failures = False

    unesco_path = upload_state["unesco_path"]
    card, failures = _build_source_card("unesco", unesco_path)
    cards.append(card)
    has_any_failures = has_any_failures or failures

    oecd_path = upload_state.get("oecd_path")
    if oecd_path:
        card, failures = _build_source_card("oecd", oecd_path)
        cards.append(card)
        has_any_failures = has_any_failures or failures
    else:
        cards.append(
            html.Div(
                className="card",
                children=[
                    html.Div(className="validation-card-header", children=[
                        html.Span("Source OCDE", className="validation-source-title"),
                        html.Span("Fichier par défaut", className="badge badge--blue"),
                    ]),
                    html.P(
                        "Le fichier de référence OCDE intégré sera utilisé.",
                        className="source-slot-note",
                        style={"marginTop": "4px"},
                    ),
                ],
            )
        )

    for ep in upload_state.get("erasmus_paths", []):
        card, failures = _build_source_card("erasmus", ep)
        cards.append(card)
        has_any_failures = has_any_failures or failures

    return cards, has_any_failures


@callback(
    Output("launch-analysis-btn", "disabled", allow_duplicate=True),
    Input({"type": "col-override", "source": ALL, "role": ALL}, "value"),
    prevent_initial_call=True,
)
def update_launch_btn_on_override(col_values: list) -> bool | type(dash.no_update):
    """Enable the launch button only when all manual column overrides are filled.

    Fires when any column-override Dropdown changes value.  Returns no_update
    when there are no override dropdowns (all columns auto-detected).
    """
    if not col_values:
        return dash.no_update
    return any(v is None for v in col_values)


@callback(
    Output("pipeline-interval", "disabled"),
    Output("progress-section", "style"),
    Output("pipeline-state-store", "data"),
    Output("launch-error", "children"),
    Input("launch-analysis-btn", "n_clicks"),
    State("upload-state", "data"),
    State("new-analysis-session", "data"),
    prevent_initial_call=True,
)
def launch_analysis(
    n_clicks: int,
    upload_state: dict,
    session_id: str,
) -> tuple:
    """Start the pipeline background thread and enable the progress interval.

    The pipeline runs in a daemon thread so it does not block the Dash server.
    Progress is written to a JSON file that the poll_pipeline_progress callback
    reads every 800 ms.
    """
    if not n_clicks or not upload_state:
        return dash.no_update, dash.no_update, dash.no_update, ""

    user_id = current_user.id
    name = upload_state.get("name", "Analyse sans nom")
    unesco_path = upload_state.get("unesco_path", "")
    oecd_path = upload_state.get("oecd_path")
    erasmus_paths = upload_state.get("erasmus_paths", [])

    thread = threading.Thread(
        target=_run_pipeline_thread,
        args=(session_id, name, user_id, unesco_path, oecd_path, erasmus_paths),
        daemon=True,
        name=f"pipeline-{session_id[:8]}",
    )
    thread.start()
    logger.info("Pipeline thread started for session %s", session_id)

    return (
        False,             # enable interval
        {},                # show progress section
        {"running": True}, # update store
        "",                # clear error
    )


@callback(
    Output("progress-bar-fill", "style"),
    Output("progress-label", "children"),
    Output("pipeline-interval", "disabled", allow_duplicate=True),
    Output("redirect", "href", allow_duplicate=True),
    Input("pipeline-interval", "n_intervals"),
    State("new-analysis-session", "data"),
    State("pipeline-state-store", "data"),
    prevent_initial_call=True,
)
def poll_pipeline_progress(
    _n_intervals: int,
    session_id: str,
    pipeline_state: dict,
) -> tuple:
    """Read the progress file and update the UI; redirect to results on completion.

    Fires every 800 ms while the pipeline-interval is enabled.  Disables itself
    when the pipeline finishes (success or error).
    """
    if not pipeline_state or not pipeline_state.get("running"):
        return dash.no_update, dash.no_update, True, dash.no_update

    progress = _read_progress(session_id)

    if progress is None:
        return {"width": "0%"}, "Initialisation…", False, dash.no_update

    step = progress.get("step", 0)
    total = progress.get("total", _PROGRESS_STEPS)
    label = progress.get("label", "")
    done = progress.get("done", False)
    error = progress.get("error")
    analysis_id = progress.get("analysis_id")

    pct = int(step / total * 100) if total else 0

    if error:
        return (
            {"width": f"{pct}%", "background": "#dc2626"},
            f"Erreur : {error}",
            True,
            dash.no_update,
        )

    if done and analysis_id:
        return {"width": "100%"}, "Analyse terminée !", True, f"/analyses/{analysis_id}"

    return {"width": f"{pct}%"}, label, False, dash.no_update
