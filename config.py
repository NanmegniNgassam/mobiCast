"""MobiCast - application configuration.

All values are read from environment variables so the same image can run
in development and production without code changes.
"""

import os

# Flask/Dash secret key - must be changed in production.
SECRET_KEY: str = os.environ.get(
    "SECRET_KEY", "dev-secret-key-please-change-in-production"
)

# Absolute path to the SQLite database file.
DATABASE_PATH: str = os.environ.get("DATABASE_PATH", "/app/db/mobicast.db")

# Root directory for all analysis data (uploads, results, defaults).
DATA_DIR: str = os.environ.get("DATA_DIR", "/app/data")

# Enable Dash debug mode and verbose logging when truthy.
DEBUG: bool = os.environ.get("DEBUG", "false").lower() == "true"

# --- Derived paths (built from DATA_DIR, not overridable individually) ---

# Directory containing bundled reference files shipped with the image.
DEFAULTS_DIR: str = os.path.join(DATA_DIR, "defaults")

# Default OECD scholarship reference file (used when the user does not upload one).
DEFAULT_OECD_PATH: str = os.path.join(DEFAULTS_DIR, "oecd_scholarships.csv")

# Default Erasmus+ mobility matrix files (used when the user does not upload them).
DEFAULT_ERASMUS_PATHS: list[str] = [
    os.path.join(DEFAULTS_DIR, "erasmus_mobility.xlsx"),
]

# Temporary upload directory - cleared after each analysis is persisted.
TMP_DIR: str = os.path.join(DATA_DIR, "tmp")

# Directory where completed analyses are stored.
ANALYSES_DIR: str = os.path.join(DATA_DIR, "analyses")
