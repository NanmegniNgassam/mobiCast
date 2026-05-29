"""MobiCast — login page (URL: /login)."""

import dash
from dash import Input, Output, State, callback, dcc, html

from components.auth import authenticate_user

dash.register_page(__name__, path="/login")

layout = html.Div(
    className="login-page",
    children=[
        html.Div(
            className="login-card",
            children=[
                html.Div(
                    className="login-header",
                    children=[
                        html.Div("📡", className="login-logo"),
                        html.H1("MobiCast", className="login-title"),
                        html.P(
                            "Analyse de la mobilité étudiante africaine vers l'Europe",
                            className="login-subtitle",
                        ),
                    ],
                ),
                html.Div(
                    className="login-form",
                    children=[
                        dcc.Input(
                            id="login-username",
                            type="text",
                            placeholder="Nom d'utilisateur",
                            autoFocus=True,
                            n_submit=0,
                            className="login-input",
                            debounce=False,
                        ),
                        dcc.Input(
                            id="login-password",
                            type="password",
                            placeholder="Mot de passe",
                            n_submit=0,
                            className="login-input",
                            debounce=False,
                        ),
                        html.Button(
                            "Se connecter",
                            id="login-submit",
                            n_clicks=0,
                            className="login-button",
                        ),
                        html.Div(
                            id="login-error",
                            className="login-error",
                            role="alert",
                        ),
                    ],
                ),
            ],
        ),
    ],
)


@callback(
    Output("redirect", "href", allow_duplicate=True),
    Output("login-error", "children"),
    Input("login-submit", "n_clicks"),
    Input("login-username", "n_submit"),
    Input("login-password", "n_submit"),
    State("login-username", "value"),
    State("login-password", "value"),
    prevent_initial_call=True,
)
def handle_login(_clicks, _u_submit, _p_submit, username, password):
    """Attempt authentication and redirect to the main page on success.

    Triggered by the submit button or pressing Enter in either input field.
    Outputs to the root-layout redirect Location so the page fully reloads.
    """
    if not username or not password:
        return dash.no_update, "Veuillez remplir tous les champs."
    user = authenticate_user(username, password)
    if user is None:
        return dash.no_update, "Identifiant ou mot de passe incorrect."
    return "/analyses/new", ""
