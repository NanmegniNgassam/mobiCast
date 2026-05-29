"""MobiCast — authentication helpers.

Provides the Flask-Login integration: LoginManager setup, User model,
credential verification and session management utilities.
"""

import logging
from datetime import datetime

from flask import session as flask_session
from flask_login import LoginManager, UserMixin, current_user, login_user, logout_user
from werkzeug.security import check_password_hash

from db.database import get_user_by_id, get_user_by_username

logger = logging.getLogger(__name__)

login_manager = LoginManager()

# Pages accessible without authentication.
PUBLIC_PATHS = {"/login"}


class User(UserMixin):
    """Represents an authenticated MobiCast user.

    Wraps the SQLite users row and satisfies the Flask-Login UserMixin contract.
    """

    def __init__(
        self,
        user_id: int,
        username: str,
        login_time: str,
        first_name: str = "",
        last_name: str = "",
    ) -> None:
        """Initialise a User instance.

        Args:
            user_id:    Database primary key.
            username:   Login name (used as fallback display name).
            login_time: Formatted time string recorded at login (e.g. "14:32").
            first_name: Given name, may be empty.
            last_name:  Family name, may be empty.
        """
        self.id = user_id
        self.username = username
        self.login_time = login_time
        self.first_name = first_name or ""
        self.last_name = last_name or ""

    @property
    def display_name(self) -> str:
        """Return the full name if available, otherwise the username."""
        full = f"{self.first_name} {self.last_name}".strip()
        return full if full else self.username

    def get_id(self) -> str:
        """Return the user's id as a string (flask-login contract)."""
        return str(self.id)


@login_manager.user_loader
def load_user(user_id: str) -> "User | None":
    """Reload a User object from the database on each authenticated request.

    Flask-Login calls this on every request to reconstruct the current user.
    The login_time is retrieved from the Flask session (set at login).
    """
    row = get_user_by_id(int(user_id))
    if row is None:
        return None
    login_time = flask_session.get("login_time", "")
    r = dict(row)
    return User(
        r["id"],
        r["username"],
        login_time,
        r.get("first_name"),
        r.get("last_name"),
    )


def init_login_manager(server) -> None:
    """Attach the LoginManager to the Flask server instance.

    Args:
        server: The Flask application instance exposed by Dash.
    """
    login_manager.init_app(server)
    logger.debug("LoginManager attached to Flask server")


def authenticate_user(username: str, password: str) -> "User | None":
    """Verify credentials and open a Flask-Login session on success.

    Args:
        username: Plain-text login name submitted by the user.
        password: Plain-text password to verify against the stored hash.

    Returns:
        A logged-in User instance on success, or None on failure.
    """
    row = get_user_by_username(username)
    if row is None:
        logger.warning("Login attempt for unknown username: %s", username)
        return None
    if not check_password_hash(row["password_hash"], password):
        logger.warning("Invalid password for user: %s", username)
        return None

    login_time = datetime.now().strftime("%H:%M")
    r = dict(row)
    user = User(
        r["id"],
        r["username"],
        login_time,
        r.get("first_name"),
        r.get("last_name"),
    )
    login_user(user, remember=False)
    flask_session["login_time"] = login_time
    logger.info("User '%s' authenticated successfully", username)
    return user


def sign_out() -> None:
    """Log out the current user and clear session data."""
    username = getattr(current_user, "username", "unknown")
    flask_session.pop("login_time", None)
    logout_user()
    logger.info("User '%s' signed out", username)


def is_authenticated() -> bool:
    """Return True if the current request belongs to an authenticated user."""
    return current_user.is_authenticated
