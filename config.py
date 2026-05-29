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

# Scan defaults dir once; used by both path constants below.
_defaults_files: list[str] = os.listdir(DEFAULTS_DIR) if os.path.isdir(DEFAULTS_DIR) else []

# Default OECD scholarship reference file.
# Matched case-insensitively and without requiring a specific extension so the file
# works whether the host saved it as .csv or .CSV (common Windows artifact).
DEFAULT_OECD_PATH: str = next(
    (
        os.path.join(DEFAULTS_DIR, f)
        for f in _defaults_files
        if f.lower().startswith("oecd_scholarships")
    ),
    os.path.join(DEFAULTS_DIR, "oecd_scholarships.csv"),  # fallback path for error messages
)

# Default Erasmus+ mobility matrix files.
# No extension filter: files downloaded from the Erasmus+ portal have no .csv extension.
DEFAULT_ERASMUS_PATHS: list[str] = sorted(
    [
        os.path.join(DEFAULTS_DIR, f)
        for f in _defaults_files
        if f.startswith("ErasmusPlus_KA1_")
    ]
)

# Temporary upload directory - cleared after each analysis is persisted.
TMP_DIR: str = os.path.join(DATA_DIR, "tmp")

# Directory where completed analyses are stored.
ANALYSES_DIR: str = os.path.join(DATA_DIR, "analyses")
