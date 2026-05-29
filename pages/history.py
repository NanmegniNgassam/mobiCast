"""MobiCast - analysis history view (URL: /analyses)."""

import logging
from datetime import datetime

import dash
from dash import dcc, html

from db.database import get_all_analyses, get_source_files_by_analysis_id

logger = logging.getLogger(__name__)

dash.register_page(__name__, path="/analyses")

_STATUS_MAP: dict[str, tuple[str, str]] = {
    "done":    ("Terminée",  "badge--green"),
    "running": ("En cours",  "badge--orange"),
    "error":   ("Erreur",    "badge--red"),
}

_SOURCE_TYPE_SHORT: dict[str, str] = {
    "unesco":          "UNESCO",
    "oecd":            "OCDE fourni",
    "erasmus":         "Erasmus+ fourni",
    "default_oecd":    "OCDE défaut",
    "default_erasmus": "Erasmus+ défaut",
}

_MONTHS: list[str] = [
    "jan.", "fév.", "mars", "avr.", "mai", "juin",
    "juil.", "août", "sep.", "oct.", "nov.", "déc.",
]


def _format_date(ts: str) -> str:
    """Return a short formatted date string from a SQLite CURRENT_TIMESTAMP."""
    try:
        dt = datetime.strptime(ts[:19], "%Y-%m-%d %H:%M:%S")
        return f"{dt.day} {_MONTHS[dt.month - 1]} {dt.year}"
    except Exception:
        return ts


def _sources_label(analysis_id: int) -> str:
    """Build a compact human-readable summary of source types for one analysis."""
    files = get_source_files_by_analysis_id(analysis_id)
    parts: list[str] = []
    seen: set[str] = set()
    for f in files:
        short = _SOURCE_TYPE_SHORT.get(f["source_type"], f["source_type"])
        if short not in seen:
            parts.append(short)
            seen.add(short)
    return " + ".join(parts) if parts else "—"


def layout(**_kwargs) -> html.Div:
    """Build and return the analysis history page layout.

    Loads all analyses from SQLite (sorted by date DESC) and renders them
    as an HTML table.  An empty-state message is shown when no analyses exist.
    """
    analyses = get_all_analyses()

    header = html.Div(
        className="page-header",
        children=[
            html.H1("Historique des analyses", className="page-title"),
            html.A("+ Nouvelle analyse", href="/analyses/new", className="btn-primary"),
        ],
    )

    if not analyses:
        content = html.Div(
            className="card history-empty-state",
            children=[
                html.P("Aucune analyse pour l'instant.", className="history-empty-text"),
                html.A(
                    "Lancer votre première analyse",
                    href="/analyses/new",
                    className="btn-primary",
                    style={"display": "inline-block", "marginTop": "16px"},
                ),
            ],
        )
        return html.Div(children=[header, content])

    rows = []
    for a in analyses:
        status_label, status_css = _STATUS_MAP.get(a["status"], (a["status"], "badge--blue"))
        author = a["author"] if a["author"] else "—"
        row_count_display = (
            f"{a['row_count']:,}".replace(",", " ")
            if a["row_count"] is not None
            else "—"
        )

        action_cell = (
            html.A(
                "Voir les résultats",
                href=f"/analyses/{a['id']}",
                className="btn-secondary history-action-btn",
            )
            if a["status"] == "done"
            else html.Span("—", className="history-cell-muted")
        )

        rows.append(html.Tr([
            html.Td(a["name"], className="rt-cell history-cell--name"),
            html.Td(_format_date(a["created_at"]), className="rt-cell history-cell--date"),
            html.Td(author, className="rt-cell"),
            html.Td(row_count_display, className="rt-cell rt-cell--num"),
            html.Td(_sources_label(a["id"]), className="rt-cell history-cell--sources"),
            html.Td(
                html.Span(status_label, className=f"badge {status_css}"),
                className="rt-cell",
            ),
            html.Td(action_cell, className="rt-cell"),
        ]))

    table = html.Div(
        className="card",
        style={"padding": "0", "overflow": "hidden"},
        children=html.Table(
            className="reliability-table history-table",
            children=[
                html.Thead(html.Tr([
                    html.Th("Nom", className="rt-header"),
                    html.Th("Date", className="rt-header"),
                    html.Th("Auteur", className="rt-header"),
                    html.Th("Lignes traitées", className="rt-header rt-header--num"),
                    html.Th("Sources utilisées", className="rt-header"),
                    html.Th("Statut", className="rt-header"),
                    html.Th("Actions", className="rt-header"),
                ])),
                html.Tbody(rows),
            ],
        ),
    )

    return html.Div(children=[header, table])
