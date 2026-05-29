"""MobiCast - analysis results page (URL: /analyses/<analysis_id>).

Contains three result tabs: Corrélations, Prédictions, Classements.
Export section: CSV and PNG downloads for all result types.
"""

import io
import json
import logging
import os
from datetime import date, datetime

import dash
import plotly.express as px
import plotly.graph_objects as go
import plotly.io as pio
from dash import Input, Output, State, callback, dcc, html
from plotly.subplots import make_subplots

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

# Fixed color sequence for consistent chart rendering across interactions.
_CHART_COLORS: list[str] = [
    "#4361ee", "#e63946", "#2dc653", "#ff9f1c", "#7209b7",
    "#3a86ff", "#fb5607", "#06d6a0", "#8338ec", "#ff006e",
]


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


def _interpretation(r2: float) -> tuple[str, str]:
    """Return (label, badge_css_class) for a model R² score.

    Args:
        r2: R² value in [0, 1].

    Returns:
        Tuple of French label and CSS badge modifier class.
    """
    if r2 > 0.75:
        return "Fiable", "badge--green"
    if r2 >= 0.5:
        return "Acceptable", "badge--orange"
    return "Faible", "badge--red"


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


def _make_predictions_figure(
    predictions: list[dict],
    selected_codes: list[str],
) -> go.Figure:
    """Create and return the Plotly Figure for the predictions line chart.

    Extracted from _build_predictions_chart so the same logic can be used
    both for dcc.Graph rendering and for PNG export via plotly.io.to_image.

    Args:
        predictions:    List of prediction dicts from results.json.
        selected_codes: ISO-3 codes of the destination countries to render.

    Returns:
        go.Figure with historical (solid) and forecast (dashed) traces.
    """
    fig = go.Figure()

    filtered = sorted(
        [p for p in predictions if p["country_code"] in selected_codes],
        key=lambda p: p["country_code"],
    )

    for i, pred in enumerate(filtered):
        color  = _CHART_COLORS[i % len(_CHART_COLORS)]
        name   = pred["country_name"]
        hist_x = pred["historical_years"]
        hist_y = pred["historical_values"]
        fc_x   = pred["forecast_years"]
        fc_y   = pred["forecast_values"]

        fig.add_trace(go.Scatter(
            x=hist_x,
            y=hist_y,
            name=name,
            line=dict(color=color, width=2),
            mode="lines+markers",
            marker=dict(size=5),
            legendgroup=name,
            hovertemplate=(
                "<b>%{x}</b><br>"
                + name
                + "<br><b>%{y:.0f}</b> étudiants"
                + "<br><i>Historique</i><extra></extra>"
            ),
        ))

        bridge_x = ([hist_x[-1]] if hist_x else []) + list(fc_x)
        bridge_y = ([hist_y[-1]] if hist_y else []) + list(fc_y)
        fig.add_trace(go.Scatter(
            x=bridge_x,
            y=bridge_y,
            name=name,
            line=dict(color=color, width=2, dash="dash"),
            mode="lines+markers",
            marker=dict(size=5),
            legendgroup=name,
            showlegend=False,
            hovertemplate=(
                "<b>%{x}</b><br>"
                + name
                + "<br><b>%{y:.0f}</b> étudiants"
                + "<br><i>Prédiction</i><extra></extra>"
            ),
        ))

    if filtered and filtered[0]["forecast_years"]:
        sep_x = filtered[0]["forecast_years"][0] - 0.5
        fig.add_vline(
            x=sep_x,
            line_dash="dot",
            line_color="#9ca3af",
            line_width=1,
            annotation_text="Prédictions →",
            annotation_position="top right",
            annotation_font_color="#6b7280",
            annotation_font_size=11,
        )

    fig.update_layout(
        margin={"l": 60, "r": 20, "t": 40, "b": 50},
        font={"size": 12, "family": "-apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif"},
        plot_bgcolor="#ffffff",
        paper_bgcolor="#ffffff",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
        xaxis=dict(showgrid=True, gridcolor="#f3f4f6", title="Année"),
        yaxis=dict(showgrid=True, gridcolor="#f3f4f6", title="Étudiants africains"),
        hovermode="x unified",
    )

    return fig


def _build_predictions_chart(
    predictions: list[dict],
    selected_codes: list[str],
) -> dcc.Graph:
    """Wrap _make_predictions_figure in a dcc.Graph for display in the UI.

    Args:
        predictions:    List of prediction dicts from results.json.
        selected_codes: ISO-3 codes of the destination countries to render.

    Returns:
        dcc.Graph component.
    """
    return dcc.Graph(
        figure=_make_predictions_figure(predictions, selected_codes),
        config={"displayModeBar": False},
        style={"height": "420px"},
    )


def _make_heatmaps_figure(
    correlations: dict,
    selected_codes: list[str],
    code_to_name: dict[str, str],
) -> go.Figure:
    """Create a combined Plotly figure with all selected heatmaps as subplots.

    Used for PNG export of the correlations tab.

    Args:
        correlations:  Dict mapping ISO-3 code → {'matrix': ..., 'columns': ...}.
        selected_codes: Ordered list of codes to include.
        code_to_name:  Mapping of ISO-3 code → display name.

    Returns:
        go.Figure with one Heatmap trace per subplot.
    """
    codes = [c for c in selected_codes if c in correlations]
    if not codes:
        return go.Figure()

    n_cols = min(2, len(codes))
    n_rows = (len(codes) + n_cols - 1) // n_cols

    fig = make_subplots(
        rows=n_rows,
        cols=n_cols,
        subplot_titles=[code_to_name.get(c, c) for c in codes],
        horizontal_spacing=0.12,
        vertical_spacing=0.18,
    )

    for idx, code in enumerate(codes):
        row = idx // n_cols + 1
        col = idx % n_cols + 1
        matrix = correlations[code]["matrix"]
        raw_cols = correlations[code]["columns"]
        display_cols = [_CORR_COL_LABELS.get(c, c) for c in raw_cols]

        fig.add_trace(
            go.Heatmap(
                z=matrix,
                x=display_cols,
                y=display_cols,
                colorscale="RdBu",
                zmin=-1,
                zmax=1,
                text=[[f"{v:.2f}" for v in row_vals] for row_vals in matrix],
                texttemplate="%{text}",
                showscale=False,
            ),
            row=row,
            col=col,
        )

    fig.update_layout(
        height=max(320 * n_rows, 400),
        paper_bgcolor="#ffffff",
        plot_bgcolor="#ffffff",
        font={
            "size": 11,
            "family": "-apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif",
        },
        margin={"l": 100, "r": 20, "t": 60, "b": 20},
    )

    return fig


def _build_reliability_table(
    predictions: list[dict],
    selected_codes: list[str],
) -> html.Div:
    """Build the model reliability table for selected destination countries.

    One row per country with R², MAE, and a colour-coded interpretation badge.

    Args:
        predictions:    List of prediction dicts from results.json.
        selected_codes: ISO-3 codes of the countries to include.

    Returns:
        html.Div containing a styled HTML table wrapped in a card, or an
        empty Div when no matching predictions are found.
    """
    filtered = sorted(
        [p for p in predictions if p["country_code"] in selected_codes],
        key=lambda p: p["country_name"],
    )
    if not filtered:
        return html.Div()

    rows = []
    for pred in filtered:
        r2  = float(pred.get("r2")  or 0)
        mae = float(pred.get("mae") or 0)
        label, css_class = _interpretation(r2)

        rows.append(html.Tr([
            html.Td(pred["country_name"], className="rt-cell"),
            html.Td(f"{r2 * 100:.1f} %", className="rt-cell rt-cell--num"),
            html.Td(
                f"{mae:,.0f}".replace(",", " "),
                className="rt-cell rt-cell--num",
            ),
            html.Td(
                html.Span(label, className=f"badge {css_class}"),
                className="rt-cell",
            ),
        ]))

    return html.Div(
        className="card",
        style={"marginTop": "20px"},
        children=[
            html.H2("Fiabilité des modèles", className="section-title"),
            html.Table(
                className="reliability-table",
                children=[
                    html.Thead(html.Tr([
                        html.Th("Pays", className="rt-header"),
                        html.Th("R²", className="rt-header rt-header--num"),
                        html.Th("Marge d'erreur (étudiants)", className="rt-header rt-header--num"),
                        html.Th("Interprétation", className="rt-header"),
                    ])),
                    html.Tbody(rows),
                ],
            ),
        ],
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


def _build_predictions_tab(
    results: dict | None,
    dest_options: list[dict],
    all_dest_codes: list[str],
    origin_options: list[dict],
) -> html.Div:
    """Return the content of the Prédictions tab.

    Args:
        results:         Full results dict loaded from results.json, or None.
        dest_options:    {label, value} dicts for the destination country dropdown.
        all_dest_codes:  All destination codes with prediction data (default selection).
        origin_options:  {label, value} dicts for the African origin country dropdown.
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
                className="predictions-filters",
                children=[
                    html.Div(
                        className="filter-group",
                        children=[
                            html.Label(
                                "Pays de destination",
                                htmlFor="dest-filter-predictions",
                                className="form-label",
                            ),
                            dcc.Dropdown(
                                id="dest-filter-predictions",
                                options=dest_options,
                                value=all_dest_codes,
                                multi=True,
                                placeholder="Sélectionner des pays…",
                                className="filter-dropdown",
                            ),
                        ],
                    ),
                    html.Div(
                        className="filter-group",
                        children=[
                            html.Label(
                                "Pays d'origine africain",
                                htmlFor="origin-filter-predictions",
                                className="form-label",
                            ),
                            dcc.Dropdown(
                                id="origin-filter-predictions",
                                options=origin_options,
                                value=[],
                                multi=True,
                                placeholder="Tous les pays d'origine…",
                                className="filter-dropdown",
                            ),
                        ],
                    ),
                ],
            ),
            html.Div(id="predictions-chart-container"),
            html.Div(id="predictions-origin-note"),
            html.Div(id="predictions-table-container"),
        ],
    )


def _build_rankings_tab(
    results: dict | None,
    years: list[int],
) -> html.Div:
    """Return the content of the Classements tab.

    Args:
        results: Full results dict loaded from results.json, or None.
        years:   Sorted list of forecast years present in the rankings data.
    """
    if not results or not years:
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
                className="rankings-year-selector",
                children=[
                    html.Label("Année de prévision", className="form-label"),
                    dcc.RadioItems(
                        id="year-selector-rankings",
                        options=[{"label": str(y), "value": str(y)} for y in years],
                        value=str(years[0]),
                        inline=True,
                        className="year-radio",
                        inputStyle={"marginRight": "5px"},
                        labelStyle={"marginRight": "12px", "cursor": "pointer"},
                    ),
                ],
            ),
            html.Div(id="rankings-global-indicator"),
            html.Div(id="rankings-table-container"),
        ],
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

    # ── Correlations tab data ────────────────────────────────────────────────
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

    # ── Predictions tab data ─────────────────────────────────────────────────
    pred_dest_options: list[dict] = []
    all_pred_codes: list[str] = []
    origin_options: list[dict] = []
    if results:
        pred_dest_options = [
            {"label": p["country_name"], "value": p["country_code"]}
            for p in results.get("predictions", [])
        ]
        all_pred_codes = [p["country_code"] for p in results.get("predictions", [])]
        origin_options = [
            {"label": c["name"], "value": c["code"]}
            for c in results.get("available_origin_countries", [])
        ]

    # ── Rankings tab data ────────────────────────────────────────────────────
    ranking_years: list[int] = []
    if results:
        ranking_years = sorted([int(y) for y in results.get("rankings", {}).keys()])

    # ── Status badge ─────────────────────────────────────────────────────────
    status_label, status_class = _STATUS_MAP.get(
        analysis["status"], (analysis["status"], "badge--blue")
    )

    # Row count display.
    row_count_display = "-"
    if analysis["row_count"] is not None:
        row_count_display = f"{analysis['row_count']:,}".replace(",", " ")

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
            # Store analysis name + date for use in export file names.
            dcc.Store(
                id="analysis-meta-store",
                data={"name": analysis["name"], "created_at": analysis["created_at"]},
            ),

            # dcc.Download sinks — one per export type.
            dcc.Download(id="download-predictions-csv"),
            dcc.Download(id="download-rankings-csv"),
            dcc.Download(id="download-predictions-png"),
            dcc.Download(id="download-heatmaps-png"),

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
                        children=_build_predictions_tab(
                            results, pred_dest_options, all_pred_codes, origin_options
                        ),
                    ),
                    dcc.Tab(
                        label="Classements",
                        value="classements",
                        className="results-tab",
                        selected_className="results-tab--selected",
                        children=_build_rankings_tab(results, ranking_years),
                    ),
                ],
            ),

            # ── Export section ───────────────────────────────────────────
            html.Div(
                className="card export-section",
                children=[
                    html.H2("Exporter les résultats", className="section-title"),
                    html.Div(
                        className="export-btn-group",
                        children=[
                            html.Div(className="export-item", children=[
                                html.P("Prédictions", className="export-item-label"),
                                html.Button(
                                    "↓ CSV",
                                    id="btn-export-predictions-csv",
                                    n_clicks=0,
                                    className="btn-secondary export-btn",
                                    disabled=(results is None),
                                ),
                                html.Button(
                                    "↓ PNG",
                                    id="btn-export-predictions-png",
                                    n_clicks=0,
                                    className="btn-secondary export-btn",
                                    disabled=(results is None),
                                ),
                            ]),
                            html.Div(className="export-item", children=[
                                html.P("Classements", className="export-item-label"),
                                html.Button(
                                    "↓ CSV",
                                    id="btn-export-rankings-csv",
                                    n_clicks=0,
                                    className="btn-secondary export-btn",
                                    disabled=(results is None),
                                ),
                            ]),
                            html.Div(className="export-item", children=[
                                html.P("Heatmaps corrélations", className="export-item-label"),
                                html.Button(
                                    "↓ PNG",
                                    id="btn-export-heatmaps-png",
                                    n_clicks=0,
                                    className="btn-secondary export-btn",
                                    disabled=(results is None),
                                ),
                            ]),
                        ],
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


@callback(
    Output("predictions-chart-container", "children"),
    Output("predictions-origin-note", "children"),
    Output("predictions-table-container", "children"),
    Input("dest-filter-predictions", "value"),
    Input("origin-filter-predictions", "value"),
    State("results-store", "data"),
)
def update_predictions(
    selected_dest: list | None,
    selected_origin: list | None,
    results: dict | None,
) -> tuple:
    """Render the predictions line chart and model reliability table.

    The origin country filter is informational: predictions are always at the
    destination country level (no per-origin breakdown in results.json).
    When an origin is selected a note is shown below the chart to clarify this.

    Args:
        selected_dest:   ISO-3 codes of selected destination countries.
        selected_origin: ISO-3 codes of selected African origin countries.
        results:         Full results dict from dcc.Store (may be None).

    Returns:
        Tuple of (chart_children, origin_note_children, table_children).
    """
    if not results or not selected_dest:
        empty = html.P("Aucun pays sélectionné.", className="tab-empty-text")
        return empty, None, None

    predictions = results.get("predictions", [])

    chart = _build_predictions_chart(predictions, selected_dest)

    origin_note = None
    if selected_origin:
        origin_note = html.P(
            "Le filtre par pays d'origine s'applique aux données historiques uniquement. "
            "Les prédictions sont calculées au niveau du pays de destination.",
            className="origin-filter-note",
        )

    table = _build_reliability_table(predictions, selected_dest)

    return chart, origin_note, table


@callback(
    Output("rankings-global-indicator", "children"),
    Output("rankings-table-container", "children"),
    Input("year-selector-rankings", "value"),
    State("results-store", "data"),
)
def update_rankings(
    selected_year: str | None,
    results: dict | None,
) -> tuple:
    """Render the global indicator and ranking table for the selected forecast year.

    Evolution values compare each country's student count to the previous
    forecast year.  For the first available year there is no predecessor in
    the rankings dict, so evolution is shown as '—'.

    Args:
        selected_year: String year key chosen in the RadioItems selector.
        results:       Full results dict from dcc.Store (may be None).

    Returns:
        Tuple of (global_indicator_children, table_children).
    """
    if not results or not selected_year:
        return None, html.P("Aucune donnée disponible.", className="tab-empty-text")

    all_rankings = results.get("rankings", {})
    current = all_rankings.get(selected_year, [])
    if not current:
        return None, html.P("Aucune donnée pour cette année.", className="tab-empty-text")

    # Previous forecast year for evolution comparison.
    prev = all_rankings.get(str(int(selected_year) - 1), [])
    prev_by_code: dict[str, float] = {r["country_code"]: r["students"] for r in prev}

    # ── Global indicator ─────────────────────────────────────────────────────
    total = sum(r["students"] for r in current)
    prev_total = sum(r["students"] for r in prev) if prev else None

    if prev_total is not None:
        delta_total = total - prev_total
        if delta_total > 0:
            evol_text = f"↑ {delta_total:,.0f}".replace(",", " ")
            evol_cls = "evolution--up"
        elif delta_total < 0:
            evol_text = f"↓ {abs(delta_total):,.0f}".replace(",", " ")
            evol_cls = "evolution--down"
        else:
            evol_text = "→ 0"
            evol_cls = "evolution--flat"
    else:
        evol_text = "—"
        evol_cls = "evolution--flat"

    global_indicator = html.Div(
        className="rankings-global card",
        children=[
            html.Div(className="rankings-global-item", children=[
                html.Span("Total estimé", className="results-meta-label"),
                html.Span(
                    f"{total:,.0f}".replace(",", " "),
                    className="rankings-global-value",
                ),
            ]),
            html.Div(className="rankings-global-item", children=[
                html.Span("Évolution vs N-1", className="results-meta-label"),
                html.Span(evol_text, className=f"rankings-global-evolution {evol_cls}"),
            ]),
        ],
    )

    # ── Ranking table ────────────────────────────────────────────────────────
    # current is already sorted descending by students (analysis.py guarantee).
    max_students = current[0]["students"] if current else 1

    rows = []
    for rank, row in enumerate(current, start=1):
        code     = row["country_code"]
        students = row["students"]

        # Rank cell — top 3 get a coloured badge.
        if rank <= 3:
            rank_cell = html.Td(
                html.Span(str(rank), className=f"rank-badge rank-badge--{rank}"),
                className="rt-cell rt-cell--num",
            )
        else:
            rank_cell = html.Td(str(rank), className="rt-cell rt-cell--num")

        # Students cell with relative progress bar.
        bar_pct = f"{students / max_students * 100:.1f}%"
        students_cell = html.Td(
            className="rt-cell rt-cell--students",
            children=html.Div(
                className="students-bar-container",
                children=[
                    html.Div(className="students-bar-fill", style={"width": bar_pct}),
                    html.Span(
                        f"{students:,.0f}".replace(",", " "),
                        className="students-value",
                    ),
                ],
            ),
        )

        # Evolution cell vs previous forecast year.
        prev_students = prev_by_code.get(code)
        if prev_students is None:
            evol_cell = html.Td("—", className="rt-cell rt-cell--num")
        else:
            delta = students - prev_students
            if delta > 0:
                evol_content = html.Span(
                    f"↑ {delta:,.0f}".replace(",", " "),
                    className="evolution-badge evolution--up",
                )
            elif delta < 0:
                evol_content = html.Span(
                    f"↓ {abs(delta):,.0f}".replace(",", " "),
                    className="evolution-badge evolution--down",
                )
            else:
                evol_content = html.Span("→ 0", className="evolution-badge evolution--flat")
            evol_cell = html.Td(evol_content, className="rt-cell")

        rows.append(html.Tr(
            className="rankings-row--top3" if rank <= 3 else "",
            children=[rank_cell, html.Td(row["country_name"], className="rt-cell"),
                      students_cell, evol_cell],
        ))

    table = html.Div(
        className="card",
        style={"marginTop": "16px"},
        children=html.Table(
            className="reliability-table",
            children=[
                html.Thead(html.Tr([
                    html.Th("Rang", className="rt-header rt-header--num"),
                    html.Th("Pays de destination", className="rt-header"),
                    html.Th("Étudiants africains estimés", className="rt-header"),
                    html.Th("Évolution vs N-1", className="rt-header"),
                ])),
                html.Tbody(rows),
            ],
        ),
    )

    return global_indicator, table


# ---------------------------------------------------------------------------
# Export callbacks
# ---------------------------------------------------------------------------


def _safe_filename(analysis_name: str, export_type: str, ext: str) -> str:
    """Build a safe export filename from analysis name, type and today's date.

    Args:
        analysis_name: Human-readable analysis name from the database.
        export_type:   Short label used in the filename (e.g. 'predictions').
        ext:           File extension without leading dot (e.g. 'csv').

    Returns:
        Filename string following the pattern mobicast_{name}_{type}_{date}.{ext}.
    """
    safe_name = analysis_name.lower().replace(" ", "_")
    today = date.today().strftime("%Y%m%d")
    return f"mobicast_{safe_name}_{export_type}_{today}.{ext}"


@callback(
    Output("download-predictions-csv", "data"),
    Input("btn-export-predictions-csv", "n_clicks"),
    State("results-store", "data"),
    State("analysis-meta-store", "data"),
    prevent_initial_call=True,
)
def export_predictions_csv(
    n_clicks: int,
    results: dict | None,
    meta: dict | None,
) -> dict | None:
    """Generate and trigger download of the predictions CSV.

    Includes all destination countries and all forecast years.

    Args:
        n_clicks: Button click count (triggers the callback).
        results:  Full results dict from dcc.Store.
        meta:     Analysis name and date from dcc.Store.

    Returns:
        dcc.send_string payload or dash.no_update when data is unavailable.
    """
    if not results or not n_clicks:
        return dash.no_update

    analysis_name = (meta or {}).get("name", "analyse")
    created_at    = (meta or {}).get("created_at", "")[:10]

    buf = io.StringIO()
    buf.write(f"# MobiCast - Prédictions\n")
    buf.write(f"# Analyse : {analysis_name}\n")
    buf.write(f"# Date    : {created_at}\n")
    buf.write("Année,Pays,Code ISO,Étudiants estimés,R²,MAE\n")

    for pred in results.get("predictions", []):
        r2  = pred.get("r2")  or 0.0
        mae = pred.get("mae") or 0.0
        for yr, val in zip(pred["forecast_years"], pred["forecast_values"]):
            buf.write(
                f"{yr},{pred['country_name']},{pred['country_code']},"
                f"{val:.0f},{r2:.4f},{mae:.1f}\n"
            )

    return dcc.send_string(
        buf.getvalue(),
        filename=_safe_filename(analysis_name, "predictions", "csv"),
        type="text/csv",
    )


@callback(
    Output("download-rankings-csv", "data"),
    Input("btn-export-rankings-csv", "n_clicks"),
    State("results-store", "data"),
    State("analysis-meta-store", "data"),
    prevent_initial_call=True,
)
def export_rankings_csv(
    n_clicks: int,
    results: dict | None,
    meta: dict | None,
) -> dict | None:
    """Generate and trigger download of the rankings CSV.

    Includes all forecast years and all destination countries.

    Args:
        n_clicks: Button click count.
        results:  Full results dict from dcc.Store.
        meta:     Analysis name and date from dcc.Store.

    Returns:
        dcc.send_string payload or dash.no_update.
    """
    if not results or not n_clicks:
        return dash.no_update

    analysis_name = (meta or {}).get("name", "analyse")
    created_at    = (meta or {}).get("created_at", "")[:10]
    all_rankings  = results.get("rankings", {})

    buf = io.StringIO()
    buf.write(f"# MobiCast - Classements\n")
    buf.write(f"# Analyse : {analysis_name}\n")
    buf.write(f"# Date    : {created_at}\n")
    buf.write("Année,Rang,Pays,Code ISO,Étudiants estimés\n")

    for year in sorted(all_rankings.keys(), key=int):
        for rank, row in enumerate(all_rankings[year], start=1):
            buf.write(
                f"{year},{rank},{row['country_name']},"
                f"{row['country_code']},{row['students']:.0f}\n"
            )

    return dcc.send_string(
        buf.getvalue(),
        filename=_safe_filename(analysis_name, "classements", "csv"),
        type="text/csv",
    )


@callback(
    Output("download-predictions-png", "data"),
    Input("btn-export-predictions-png", "n_clicks"),
    State("results-store", "data"),
    State("dest-filter-predictions", "value"),
    State("analysis-meta-store", "data"),
    prevent_initial_call=True,
)
def export_predictions_png(
    n_clicks: int,
    results: dict | None,
    selected_dest: list | None,
    meta: dict | None,
) -> dict | None:
    """Generate and trigger download of the predictions chart as PNG.

    Regenerates the chart from the current filter selection using kaleido.

    Args:
        n_clicks:      Button click count.
        results:       Full results dict from dcc.Store.
        selected_dest: Currently selected destination country codes.
        meta:          Analysis name and date from dcc.Store.

    Returns:
        dcc.send_bytes payload or dash.no_update.
    """
    if not results or not n_clicks:
        return dash.no_update

    analysis_name = (meta or {}).get("name", "analyse")
    predictions   = results.get("predictions", [])
    codes         = selected_dest or [p["country_code"] for p in predictions]

    fig = _make_predictions_figure(predictions, codes)
    img_bytes = pio.to_image(fig, format="png", width=1200, height=600, scale=2)

    return dcc.send_bytes(
        img_bytes,
        filename=_safe_filename(analysis_name, "predictions", "png"),
    )


@callback(
    Output("download-heatmaps-png", "data"),
    Input("btn-export-heatmaps-png", "n_clicks"),
    State("results-store", "data"),
    State("country-filter-correlations", "value"),
    State("analysis-meta-store", "data"),
    prevent_initial_call=True,
)
def export_heatmaps_png(
    n_clicks: int,
    results: dict | None,
    selected_codes: list | None,
    meta: dict | None,
) -> dict | None:
    """Generate and trigger download of the correlation heatmaps as a PNG grid.

    Regenerates the combined subplot figure from the current filter selection.

    Args:
        n_clicks:       Button click count.
        results:        Full results dict from dcc.Store.
        selected_codes: Currently selected country codes in the correlations tab.
        meta:           Analysis name and date from dcc.Store.

    Returns:
        dcc.send_bytes payload or dash.no_update.
    """
    if not results or not n_clicks:
        return dash.no_update

    analysis_name = (meta or {}).get("name", "analyse")
    correlations  = results.get("correlations", {})
    code_to_name  = {
        c["code"]: c["name"]
        for c in results.get("available_destination_countries", [])
    }
    codes = selected_codes or sorted(correlations.keys())

    fig = _make_heatmaps_figure(correlations, codes, code_to_name)
    img_bytes = pio.to_image(fig, format="png", width=1200, height=fig.layout.height or 600, scale=2)

    return dcc.send_bytes(
        img_bytes,
        filename=_safe_filename(analysis_name, "heatmaps", "png"),
    )
