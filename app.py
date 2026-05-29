"""MobiCast - Dash application entry point."""

import logging

import dash
from dash import Input, Output, callback, dcc, html
from flask_login import current_user

from components.auth import init_login_manager, sign_out
from config import DEBUG, SECRET_KEY
from db.database import init_db

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.DEBUG if DEBUG else logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Database - initialise on startup (idempotent)
# ---------------------------------------------------------------------------

init_db()

# ---------------------------------------------------------------------------
# Dash application
# ---------------------------------------------------------------------------

# suppress_callback_exceptions must be True because many callbacks reference
# components rendered dynamically by other callbacks (navbar, page containers).
app = dash.Dash(
    __name__,
    use_pages=True,
    suppress_callback_exceptions=True,
)

server = app.server
server.secret_key = SECRET_KEY
init_login_manager(server)

# ---------------------------------------------------------------------------
# Root layout
# ---------------------------------------------------------------------------
# The navbar is always present in the DOM so that the logout-button callback
# never references a missing component.  Its visibility is controlled by CSS
# via the "hidden" class toggled in the update_navbar callback.
# ---------------------------------------------------------------------------

app.layout = html.Div(
    className="app-root",
    children=[
        # URL tracker (no page reload on pathname change)
        dcc.Location(id="url", refresh=False),
        # Redirect target - refresh=True triggers a full page reload when href is set
        dcc.Location(id="redirect", refresh=True),
        # Client-side session store (user info for display, not for auth decisions)
        dcc.Store(id="session-store", storage_type="session"),

        # Top navigation bar
        html.Nav(
            id="navbar",
            className="navbar navbar--hidden",
            children=[
                html.A("MobiCast", href="/analyses", className="navbar-brand"),
                html.Div(
                    className="navbar-right",
                    children=[
                        html.Span(id="navbar-user-info", className="navbar-user"),
                        html.Button(
                            "Se déconnecter",
                            id="logout-button",
                            n_clicks=0,
                            className="navbar-logout",
                        ),
                    ],
                ),
            ],
        ),

        # Page content injected here by Dash's multi-page router
        html.Main(id="page-content", children=[dash.page_container]),
    ],
)

# ---------------------------------------------------------------------------
# Callbacks
# ---------------------------------------------------------------------------


@callback(
    Output("redirect", "href"),
    Input("url", "pathname"),
    prevent_initial_call=False,
)
def protect_routes(pathname):
    """Redirect unauthenticated requests to /login.

    Fires on every URL change.  Returns dash.no_update when no redirect
    is needed so the current page is not unnecessarily reloaded.
    """
    if pathname == "/login":
        return dash.no_update
    if not current_user.is_authenticated:
        logger.debug("Unauthenticated access to %s - redirecting to /login", pathname)
        return "/login"
    if pathname == "/":
        return "/analyses/new"
    return dash.no_update


@callback(
    Output("navbar", "className"),
    Output("navbar-user-info", "children"),
    Input("url", "pathname"),
)
def update_navbar(pathname):
    """Show the navbar on authenticated pages; hide it on /login.

    Returns the CSS class and the user info text for the nav bar.
    """
    if pathname == "/login" or not current_user.is_authenticated:
        return "navbar navbar--hidden", ""
    info = f"{current_user.display_name}  ·  connecté à {current_user.login_time}"
    return "navbar", info


@callback(
    Output("redirect", "href", allow_duplicate=True),
    Input("logout-button", "n_clicks"),
    prevent_initial_call=True,
)
def handle_logout(n_clicks):
    """Sign out the current user and redirect to /login."""
    if n_clicks:
        sign_out()
        return "/login"
    return dash.no_update


if __name__ == "__main__":
    logger.info("Starting MobiCast in development mode")
    app.run(debug=DEBUG, host="0.0.0.0", port=8050)
