"""MobiCast - analysis results page (URL: /analyses/<analysis_id>).

Contains three result tabs: Corrélations, Prédictions, Classements.
Prompt 08: Correlations tab implemented.
Prompt 09: Predictions tab (stub → to be replaced).
Prompt 10: Rankings tab    (stub → to be replaced).
"""

import json
import logging
import os
from datetime import datetime

import dash
import plotly.express as px
from dash import Input, Output, State, callback, dcc, html

from config import ANALYSES_DIR
from db.database import (
    get_analysis_by_id,
    get_source_files_by_analysis_id,
    get_user_by_id,
)

logger = logging.getLogger(__name__)

dash.register_page(__name__, path_template="/analyses/<analysis_id>")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_SOURCE_TYPE_LABELS: dict[str, str] = {
    "unesco":          "UNESCO - fourni",
    "oecd":            "OCDE - fourni",
    "erasmus":         "Erasmus+ - fourni",
    "default_oecd":    "OCDE - référence par défaut",
    "default_erasmus": "Erasmus+ - référence par défaut",
}

_STATUS_MAP: dict[str, tuple[str, str]] = {
    "done":    ("Terminée", "badge--green"),
    "running": ("En cours", "badge--orange"),
    "error":   ("Erreur",   "badge--red"),
}

_CORR_COL_LABELS: dict[str, str] = {
    "Year":                    "Année",
    "Scholarship_Amount_MUSD": "Bourses (MUSD)",
    "African_Students_Count":  "Étudiants africains",
}


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _not_found_page() -> html.Div:
    """Return a simple 404 layout."""
    return html.Div(
        className="not-found-page",
        children=[
            html.Div(className="not-found-inner", children=[
                html.H1("404", className="not-found-title"),
                html.P("Cette analyse n'existe pas.", className="not-found-text"),
                html.A("← Retour à l'historique", href="/analyses",
                       className="not-found-link"),
            ]),
        ],
    )


def _format_date(ts: str) -> str:
    """Parse a SQLite CURRENT_TIMESTAMP and return a formatted French date string."""
    _months = [
        "janvier", "février", "mars", "avril", "mai", "juin",
        "juillet", "août", "septembre", "octobre", "novembre", "décembre",
    ]
    try:
        dt = datetime.strptime(ts[:19], "%Y-%m-%d %H:%M:%S")
        return f"{dt.day} {_months[dt.month - 1]} {dt.year} à {dt.strftime('%H:%M')}"
    except Exception:
        return ts


def _build_heatmap(code: str, name: str, corr_data: dict) -> dcc.Graph:
    """Build a Plotly correlation heatmap for one destination country.

    Args:
        code:      ISO-3 country code (unused in the figure, kept for logging).
        name:      Human-readable country name used as the figure title.
        corr_data: Dict with keys 'matrix' (list[list[float]]) and
                   'columns' (list[str]).

    Returns:
        A dcc.Graph containing a Plotly imshow heatmap with correlation values.
    """
    matrix = corr_data["matrix"]
    raw_cols = corr_data["columns"]
    display_cols = [_CORR_COL_LABELS.get(c, c) for c in raw_cols]

    fig = px.imshow(
        matrix,
        x=display_cols,
        y=display_cols,
        color_continuous_scale="RdBu",
        zmin=-1,
        zmax=1,
        text_auto=".2f",
        title=name,
    )
    fig.update_layout(
        margin={"l": 110, "r": 20, "t": 60, "b": 80},
        font={"size": 12, "family": "-apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif"},
        title_font_size=14,
        title_font_color="#1a1a2e",
        coloraxis_showscale=False,
        plot_bgcolor="#ffffff",
        paper_bgcolor="#ffffff",
    )
    fig.update_traces(textfont_size=13, textfont_color="#1a1a2e")

    return dcc.Graph(
        figure=fig,
        config={"displayModeBar": False},
        style={"height": "320px"},
    )


# ---------------------------------------------------------------------------
# Tab builders
# ---------------------------------------------------------------------------


def _build_correlations_tab(
    results: dict | None,
    country_options: list[dict],
    all_codes: list[str],
) -> html.Div:
    """Return the content of the Corrélations tab.

    Args:
        results:         Full results dict loaded from results.json, or None.
        country_options: List of {label, value} dicts for the filter dropdown.
        all_codes:       All country codes that have correlation data (default selection).
    """
    if not results:
        return html.Div(
            className="tab-empty-state",
            children=html.P(
                "Les résultats ne sont pas disponibles pour cette analyse.",
                className="tab-empty-text",
            ),
        )

    return html.Div(
        className="tab-content",
        children=[
            html.Div(
                className="filter-bar",
                children=[
                    html.Label(
                        "Pays de destination",
                        htmlFor="country-filter-correlations",
                        className="form-label",
                    ),
                    dcc.Dropdown(
                        id="country-filter-correlations",
                        options=country_options,
                        value=all_codes,
                        multi=True,
                        placeholder="Sélectionner des pays…",
                        className="filter-dropdown",
                    ),
                ],
            ),
            html.Div(id="correlations-grid"),
        ],
    )


def _build_predictions_tab_stub() -> html.Div:
    """Return a placeholder for the Prédictions tab (prompt 09)."""
    return html.Div(
        className="tab-empty-state",
        children=html.P(
            "Onglet Prédictions - disponible dans la prochaine version.",
            className="tab-empty-text",
        ),
    )


def _build_rankings_tab_stub() -> html.Div:
    """Return a placeholder for the Classements tab (prompt 10)."""
    return html.Div(
        className="tab-empty-state",
        children=html.P(
            "Onglet Classements - disponible dans la prochaine version.",
            className="tab-empty-text",
        ),
    )


# ---------------------------------------------------------------------------
# Layout
# ---------------------------------------------------------------------------


def layout(analysis_id=None, **_kwargs) -> html.Div:
    """Build and return the full results page for the given analysis.

    Loads data from SQLite and from the results.json file written by the
    pipeline.  Returns a 404 page if the analysis does not exist.

    Args:
        analysis_id: Integer analysis primary key extracted from the URL path.
    """
    if analysis_id is None:
        return _not_found_page()

    try:
        analysis_id = int(analysis_id)
    except (ValueError, TypeError):
        return _not_found_page()

    analysis = get_analysis_by_id(analysis_id)
    if analysis is None:
        return _not_found_page()

    # Resolve author display name.
    author = "-"
    if analysis["user_id"]:
        user = get_user_by_id(analysis["user_id"])
        if user:
            full_name = (
                f"{user['first_name'] or ''} {user['last_name'] or ''}".strip()
            )
            author = full_name or user["username"]

    # Load pipeline results from JSON.
    results: dict | None = None
    if analysis["status"] == "done":
        results_path = os.path.join(ANALYSES_DIR, str(analysis_id), "results.json")
        try:
            with open(results_path, encoding="utf-8") as fh:
                results = json.load(fh)
        except FileNotFoundError:
            logger.warning("results.json missing for analysis %d", analysis_id)
        except Exception:
            logger.exception("Cannot load results.json for analysis %d", analysis_id)

    source_files = get_source_files_by_analysis_id(analysis_id)

    # Build country lookups.
    code_to_name: dict[str, str] = {}
    correlation_codes: list[str] = []
    if results:
        code_to_name = {
            c["code"]: c["name"]
            for c in results.get("available_destination_countries", [])
        }
        correlation_codes = sorted(
            results.get("correlations", {}).keys(),
            key=lambda c: code_to_name.get(c, c),
        )

    country_options = [
        {"label": code_to_name.get(code, code), "value": code}
        for code in correlation_codes
    ]

    # Status badge.
    status_label, status_class = _STATUS_MAP.get(
        analysis["status"], (analysis["status"], "badge--blue")
    )

    # Row count display.
    row_count_display = "-"
    if analysis["row_count"] is not None:
        row_count_display = f"{analysis['row_count']:,}".replace(",", " ")

    # Source files list items.
    source_items = [
        html.Li(
            className="source-file-item",
            children=[
                html.Span(
                    _SOURCE_TYPE_LABELS.get(sf["source_type"], sf["source_type"]),
                    className="source-file-type",
                ),
                html.Span(sf["file_name"], className="source-file-name"),
            ],
        )
        for sf in source_files
    ]

    return html.Div(
        children=[
            # Store results for callbacks (avoids re-reading the file per interaction).
            dcc.Store(id="results-store", data=results),

            # ── Analysis header card ─────────────────────────────────────
            html.Div(
                className="card results-header-card",
                children=[
                    html.Div(
                        className="results-header-top",
                        children=[
                            html.H1(analysis["name"], className="page-title"),
                            html.Span(status_label, className=f"badge {status_class}"),
                        ],
                    ),
                    html.Div(
                        className="results-meta",
                        children=[
                            html.Div(className="results-meta-item", children=[
                                html.Span("Date", className="results-meta-label"),
                                html.Span(
                                    _format_date(analysis["created_at"]),
                                    className="results-meta-value",
                                ),
                            ]),
                            html.Div(className="results-meta-item", children=[
                                html.Span("Auteur", className="results-meta-label"),
                                html.Span(author, className="results-meta-value"),
                            ]),
                            html.Div(className="results-meta-item", children=[
                                html.Span(
                                    "Lignes traitées",
                                    className="results-meta-label",
                                ),
                                html.Span(
                                    row_count_display,
                                    className="results-meta-value",
                                ),
                            ]),
                        ],
                    ),
                ],
            ),

            # ── Source files card ────────────────────────────────────────
            html.Div(
                className="card",
                children=[
                    html.H2("Sources utilisées", className="section-title"),
                    html.Ul(
                        className="source-files-list",
                        children=source_items or [
                            html.Li(
                                "Aucun fichier source enregistré.",
                                className="source-slot-note",
                            )
                        ],
                    ),
                ],
            ),

            # ── Result tabs ──────────────────────────────────────────────
            dcc.Tabs(
                id="results-tabs",
                value="correlations",
                className="results-tabs",
                children=[
                    dcc.Tab(
                        label="Corrélations",
                        value="correlations",
                        className="results-tab",
                        selected_className="results-tab--selected",
                        children=_build_correlations_tab(
                            results, country_options, correlation_codes
                        ),
                    ),
                    dcc.Tab(
                        label="Prédictions",
                        value="predictions",
                        className="results-tab",
                        selected_className="results-tab--selected",
                        children=_build_predictions_tab_stub(),
                    ),
                    dcc.Tab(
                        label="Classements",
                        value="classements",
                        className="results-tab",
                        selected_className="results-tab--selected",
                        children=_build_rankings_tab_stub(),
                    ),
                ],
            ),
        ]
    )


# ---------------------------------------------------------------------------
# Callbacks
# ---------------------------------------------------------------------------


@callback(
    Output("correlations-grid", "children"),
    Input("country-filter-correlations", "value"),
    State("results-store", "data"),
)
def update_correlations_grid(
    selected_codes: list | None,
    results: dict | None,
) -> list:
    """Render one correlation heatmap per selected destination country.

    Args:
        selected_codes: ISO-3 codes chosen in the filter dropdown.
        results:        Full results dict from dcc.Store (may be None).

    Returns:
        List of children for the correlations-grid Div.
    """
    if not results or not selected_codes:
        return [
            html.P("Aucun pays sélectionné.", className="tab-empty-text")
        ]

    correlations = results.get("correlations", {})
    code_to_name = {
        c["code"]: c["name"]
        for c in results.get("available_destination_countries", [])
    }

    wrappers = []
    for code in selected_codes:
        if code not in correlations:
            continue
        name = code_to_name.get(code, code)
        graph = _build_heatmap(code, name, correlations[code])
        wrappers.append(html.Div(className="heatmap-wrapper", children=[graph]))

    if not wrappers:
        return [
            html.P(
                "Aucune donnée de corrélation pour les pays sélectionnés.",
                className="tab-empty-text",
            )
        ]

    return [html.Div(className="heatmaps-grid", children=wrappers)]
