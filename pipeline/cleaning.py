"""MobiCast - data cleaning and merging pipeline.

Loads data from three sources (UNESCO, OECD, Erasmus+), normalises columns,
filters to African origin countries and European destination countries,
merges the sources, interpolates missing values and returns a clean DataFrame.

Expected output columns
-----------------------
year               : int
destination_code   : str  (ISO-3166-1 alpha-3)
destination_name   : str
origin_code        : str  (ISO-3166-1 alpha-3)
origin_name        : str
student_count      : float  (number of African students at that destination)
scholarship_musd   : float  (OECD scholarship amount in MUSD for that destination/year)
"""

import logging
from pathlib import Path

import pandas as pd

from config import DEFAULT_ERASMUS_PATHS, DEFAULT_OECD_PATH

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Geographic reference sets
# ---------------------------------------------------------------------------

AFRICAN_ISO3: frozenset[str] = frozenset({
    "DZA", "AGO", "BEN", "BWA", "BFA", "BDI", "CMR", "CPV", "CAF", "TCD",
    "COM", "COD", "COG", "CIV", "DJI", "EGY", "GNQ", "ERI", "SWZ", "ETH",
    "GAB", "GMB", "GHA", "GIN", "GNB", "KEN", "LSO", "LBR", "LBY", "MDG",
    "MWI", "MLI", "MRT", "MUS", "MAR", "MOZ", "NAM", "NER", "NGA", "RWA",
    "STP", "SEN", "SLE", "SOM", "ZAF", "SSD", "SDN", "TZA", "TGO", "TUN",
    "UGA", "ZMB", "ZWE",
})

EUROPEAN_ISO3: frozenset[str] = frozenset({
    "FRA", "DEU", "GBR", "ITA", "ESP", "PRT", "BEL", "NLD", "AUT", "CHE",
    "SWE", "NOR", "DNK", "FIN", "IRL", "POL", "CZE", "SVK", "HUN", "ROU",
    "BGR", "HRV", "SVN", "LTU", "LVA", "EST", "GRC", "CYP", "MLT", "LUX",
})

# Human-readable names for ISO codes used in the UI.
ISO3_TO_NAME: dict[str, str] = {
    "FRA": "France",         "DEU": "Allemagne",      "GBR": "Royaume-Uni",
    "ITA": "Italie",         "ESP": "Espagne",         "PRT": "Portugal",
    "BEL": "Belgique",       "NLD": "Pays-Bas",        "AUT": "Autriche",
    "CHE": "Suisse",         "SWE": "Suède",           "NOR": "Norvège",
    "DNK": "Danemark",       "FIN": "Finlande",        "IRL": "Irlande",
    "POL": "Pologne",        "CZE": "Rép. tchèque",    "SVK": "Slovaquie",
    "HUN": "Hongrie",        "ROU": "Roumanie",        "BGR": "Bulgarie",
    "HRV": "Croatie",        "SVN": "Slovénie",        "LTU": "Lituanie",
    "LVA": "Lettonie",       "EST": "Estonie",         "GRC": "Grèce",
    "CYP": "Chypre",         "MLT": "Malte",           "LUX": "Luxembourg",
    "DZA": "Algérie",        "AGO": "Angola",          "BEN": "Bénin",
    "BWA": "Botswana",       "BFA": "Burkina Faso",    "BDI": "Burundi",
    "CMR": "Cameroun",       "CPV": "Cap-Vert",        "CAF": "Rép. centrafricaine",
    "TCD": "Tchad",          "COM": "Comores",         "COD": "RD Congo",
    "COG": "Congo",          "CIV": "Côte d'Ivoire",   "DJI": "Djibouti",
    "EGY": "Égypte",         "GNQ": "Guinée équat.",   "ERI": "Érythrée",
    "SWZ": "Eswatini",       "ETH": "Éthiopie",        "GAB": "Gabon",
    "GMB": "Gambie",         "GHA": "Ghana",           "GIN": "Guinée",
    "GNB": "Guinée-Bissau",  "KEN": "Kenya",           "LSO": "Lesotho",
    "LBR": "Libéria",        "LBY": "Libye",           "MDG": "Madagascar",
    "MWI": "Malawi",         "MLI": "Mali",            "MRT": "Mauritanie",
    "MUS": "Maurice",        "MAR": "Maroc",           "MOZ": "Mozambique",
    "NAM": "Namibie",        "NER": "Niger",           "NGA": "Nigéria",
    "RWA": "Rwanda",         "STP": "Sao Tomé",        "SEN": "Sénégal",
    "SLE": "Sierra Leone",   "SOM": "Somalie",         "ZAF": "Afrique du Sud",
    "SSD": "Soudan du Sud",  "SDN": "Soudan",          "TZA": "Tanzanie",
    "TGO": "Togo",           "TUN": "Tunisie",         "UGA": "Ouganda",
    "ZMB": "Zambie",         "ZWE": "Zimbabwe",
}

# Country name strings (in various spellings) → ISO3 for normalisation.
_NAME_TO_ISO3: dict[str, str] = {
    # European
    "france": "FRA", "germany": "DEU", "united kingdom": "GBR",
    "italy": "ITA", "spain": "ESP", "portugal": "PRT",
    "belgium": "BEL", "netherlands": "NLD", "austria": "AUT",
    "switzerland": "CHE", "sweden": "SWE", "norway": "NOR",
    "denmark": "DNK", "finland": "FIN", "ireland": "IRL",
    "poland": "POL", "czech republic": "CZE", "czechia": "CZE",
    "slovakia": "SVK", "hungary": "HUN", "romania": "ROU",
    "bulgaria": "BGR", "croatia": "HRV", "slovenia": "SVN",
    "lithuania": "LTU", "latvia": "LVA", "estonia": "EST",
    "greece": "GRC", "cyprus": "CYP", "malta": "MLT",
    "luxembourg": "LUX",
    # African
    "algeria": "DZA", "angola": "AGO", "benin": "BEN",
    "botswana": "BWA", "burkina faso": "BFA", "burundi": "BDI",
    "cameroon": "CMR", "cameroun": "CMR", "cape verde": "CPV",
    "cabo verde": "CPV", "central african republic": "CAF",
    "chad": "TCD", "comoros": "COM", "congo, dem. rep.": "COD",
    "democratic republic of the congo": "COD", "dr congo": "COD",
    "congo": "COG", "republic of congo": "COG",
    "cote d'ivoire": "CIV", "côte d'ivoire": "CIV", "ivory coast": "CIV",
    "djibouti": "DJI", "egypt": "EGY", "equatorial guinea": "GNQ",
    "eritrea": "ERI", "eswatini": "SWZ", "swaziland": "SWZ",
    "ethiopia": "ETH", "gabon": "GAB", "gambia": "GMB", "ghana": "GHA",
    "guinea": "GIN", "guinea-bissau": "GNB", "kenya": "KEN",
    "lesotho": "LSO", "liberia": "LBR", "libya": "LBY",
    "madagascar": "MDG", "malawi": "MWI", "mali": "MLI",
    "mauritania": "MRT", "mauritius": "MUS", "morocco": "MAR",
    "mozambique": "MOZ", "namibia": "NAM", "niger": "NER",
    "nigeria": "NGA", "rwanda": "RWA",
    "sao tome and principe": "STP", "são tomé e príncipe": "STP",
    "senegal": "SEN", "sénégal": "SEN", "sierra leone": "SLE",
    "somalia": "SOM", "south africa": "ZAF", "south sudan": "SSD",
    "sudan": "SDN", "tanzania": "TZA", "togo": "TGO",
    "tunisia": "TUN", "tunisie": "TUN", "uganda": "UGA",
    "zambia": "ZMB", "zimbabwe": "ZWE",
}


def _name_to_iso3(name: str) -> str:
    """Resolve a country name string to its ISO-3166-1 alpha-3 code.

    Falls back to the first three characters (uppercased) when the name
    is not in the lookup table - this keeps the pipeline running even
    with unexpected spellings, at the cost of incorrect codes for unknowns.
    """
    return _NAME_TO_ISO3.get(str(name).strip().lower(), str(name)[:3].upper())


# ---------------------------------------------------------------------------
# Custom exception
# ---------------------------------------------------------------------------


class ColumnDetectionError(Exception):
    """Raised when a required column cannot be auto-detected in a source file.

    The message contains the source name and the patterns that were tried so
    the caller can present actionable feedback in the UI (see prompt 07).
    """


# ---------------------------------------------------------------------------
# Column detection helpers
# ---------------------------------------------------------------------------


def _detect_column(
    df: pd.DataFrame,
    patterns: list[str],
    source_name: str,
    role: str,
) -> str:
    """Return the first DataFrame column whose name contains any of the patterns.

    The match is case-insensitive and uses substring search.

    Args:
        df:          DataFrame to inspect.
        patterns:    Substrings to search for in column names (tried in order).
        source_name: Source label used in error messages (e.g. "UNESCO").
        role:        Semantic role label used in error messages (e.g. "country").

    Returns:
        The original (un-lowercased) column name of the first match.

    Raises:
        ColumnDetectionError: When no column matches any pattern.
    """
    cols_lower = {c.lower(): c for c in df.columns}
    for pattern in patterns:
        matches = [orig for low, orig in cols_lower.items() if pattern.lower() in low]
        if matches:
            logger.debug(
                "[%s] Detected '%s' column: '%s' (pattern: '%s')",
                source_name, role, matches[0], pattern,
            )
            return matches[0]
    raise ColumnDetectionError(
        f"[{source_name}] Cannot detect the '{role}' column. "
        f"Tried patterns: {patterns}. "
        f"Available columns: {list(df.columns)}"
    )


def _try_detect_column(
    df: pd.DataFrame,
    patterns: list[str],
    source_name: str,
    role: str,
) -> str | None:
    """Like _detect_column but returns None instead of raising on no match."""
    try:
        return _detect_column(df, patterns, source_name, role)
    except ColumnDetectionError:
        return None


def detect_columns(df: pd.DataFrame, source_type: str) -> dict[str, str | None]:
    """Return a mapping of semantic role → detected column name for a given source.

    Used by the UI validation step (prompt 07) to preview column mappings
    before launching the pipeline.

    Args:
        df:          DataFrame loaded from the uploaded file.
        source_type: One of 'unesco', 'oecd', 'erasmus'.

    Returns:
        Dict with keys matching the expected roles for that source type.
        Values are column names (str) or None when detection failed.
    """
    if source_type == "unesco":
        return {
            "country":       _try_detect_column(df, ["geounit"], "UNESCO", "country"),
            "year":          _try_detect_column(df, ["year"], "UNESCO", "year"),
            "student_count": _try_detect_column(df, ["value"], "UNESCO", "student_count"),
        }
    if source_type == "oecd":
        return {
            "destination":        _try_detect_column(df, ["donor"], "OECD", "destination"),
            "year":               _try_detect_column(df, ["time_period", "year"], "OECD", "year"),
            "scholarship_amount": _try_detect_column(
                df, ["obs_value", "value"], "OECD", "scholarship_amount"
            ),
        }
    if source_type == "erasmus":
        return {
            "coordinator_country": _try_detect_column(
                df, ["coordinat"], "Erasmus+", "coordinator_country"
            ),
            "participant_country": _try_detect_column(
                df, ["participat"], "Erasmus+", "participant_country"
            ),
            "year": _try_detect_column(df, ["year", "call"], "Erasmus+", "year"),
        }
    return {}


# ---------------------------------------------------------------------------
# Per-source loaders
# ---------------------------------------------------------------------------


def _read_file(path: str, source_name: str) -> pd.DataFrame:
    """Read a CSV or Excel file into a DataFrame.

    Args:
        path:        Absolute or relative file path.
        source_name: Label used in log messages.

    Returns:
        Raw DataFrame with no transformations applied.
    """
    ext = Path(path).suffix.lower()
    if ext in (".xlsx", ".xls"):
        df = pd.read_excel(path, engine="openpyxl")
    else:
        df = pd.read_csv(path, low_memory=False, on_bad_lines="skip")
    logger.debug("[%s] Loaded %d rows × %d cols from %s", source_name, len(df), len(df.columns), path)
    return df


def _load_unesco(path: str) -> pd.DataFrame:
    """Load and normalise UNESCO internationally mobile students data.

    Filters on indicatorId == 26420. Detects the country (geounit), year
    and value columns automatically.

    The geounit column is treated as the ORIGIN (sending) country; the
    pipeline keeps only rows whose ISO-3 code falls in AFRICAN_ISO3.

    If a secondary country dimension is present (e.g. a host/destination
    column), it is detected and used; otherwise origin counts are treated
    as total outbound figures that will be distributed via Erasmus+ pairs.

    Returns:
        DataFrame with columns: year, origin_code, origin_name, student_count.
        An optional 'destination_code' column is included when a host
        country dimension can be detected.
    """
    df = _read_file(path, "UNESCO")

    # Filter to the international mobility indicator when the column exists.
    indicator_col = _try_detect_column(
        df, ["indicatorid", "indicator_id"], "UNESCO", "indicatorId"
    )
    if indicator_col:
        before = len(df)
        df = df[df[indicator_col] == 26420].copy()
        logger.debug("[UNESCO] %d → %d rows after indicatorId==26420 filter", before, len(df))
    else:
        logger.warning("[UNESCO] No indicatorId column found - using all rows")

    country_col = _detect_column(df, ["geounit"], "UNESCO", "country")
    year_col    = _detect_column(df, ["year"], "UNESCO", "year")
    value_col   = _detect_column(df, ["value"], "UNESCO", "student_count")

    # Optional: look for a host/destination country column.
    host_col = _try_detect_column(
        df, ["host", "destination", "dest", "receiving"], "UNESCO", "host_country"
    )

    keep = [country_col, year_col, value_col]
    if host_col:
        keep.append(host_col)

    df = df[keep].copy()

    df["year"]          = pd.to_numeric(df[year_col], errors="coerce")
    df["student_count"] = pd.to_numeric(df[value_col], errors="coerce")
    df = df.dropna(subset=["year", "student_count"])
    df["year"] = df["year"].astype(int)

    df["origin_code"] = df[country_col].apply(_name_to_iso3)
    df["origin_name"] = df[country_col].apply(
        lambda x: ISO3_TO_NAME.get(_name_to_iso3(x), str(x))
    )

    # Keep only African origin countries.
    df = df[df["origin_code"].isin(AFRICAN_ISO3)].copy()

    result_cols = ["year", "origin_code", "origin_name", "student_count"]

    if host_col:
        df["destination_code"] = df[host_col].apply(_name_to_iso3)
        df = df[df["destination_code"].isin(EUROPEAN_ISO3)]
        result_cols.append("destination_code")

    df = df[result_cols]
    logger.info("[UNESCO] %d rows after African-origin filter", len(df))
    return df


def _load_oecd(path: str) -> pd.DataFrame:
    """Load and normalise OECD scholarship data.

    Detects donor (destination), time_period/year and obs_value/value columns.
    Aggregates to (year, destination) level and keeps European destinations only.

    Returns:
        DataFrame with columns: year, destination_code, destination_name,
        scholarship_musd.
    """
    df = _read_file(path, "OECD")

    dest_col   = _detect_column(df, ["donor"], "OECD", "destination")
    year_col   = _detect_column(df, ["time_period", "year"], "OECD", "year")
    amount_col = _detect_column(df, ["obs_value", "value"], "OECD", "scholarship_amount")

    df = df[[dest_col, year_col, amount_col]].copy()
    df["year"]            = pd.to_numeric(df[year_col], errors="coerce")
    df["scholarship_musd"] = pd.to_numeric(df[amount_col], errors="coerce")
    df = df.dropna(subset=["year", "scholarship_musd"])
    df["year"] = df["year"].astype(int)

    df["destination_code"] = df[dest_col].apply(_name_to_iso3)
    df["destination_name"] = df[dest_col].apply(
        lambda x: ISO3_TO_NAME.get(_name_to_iso3(x), str(x))
    )

    df = df[df["destination_code"].isin(EUROPEAN_ISO3)]

    # Aggregate to (year, destination) - sum in case of multiple aid categories.
    df = df.groupby(
        ["year", "destination_code", "destination_name"], as_index=False
    )["scholarship_musd"].sum()

    logger.info("[OECD] %d (year, destination) rows after European filter", len(df))
    return df


def _load_erasmus(paths: list[str]) -> pd.DataFrame:
    """Load and normalise Erasmus+ KA1 mobility data.

    Detects coordinator country (destination) and participant country (origin)
    columns using fuzzy matching. Returns the set of valid (destination, origin)
    pairs present in the Erasmus+ programme.

    Returns:
        DataFrame with columns: destination_code, origin_code.
        One row per distinct pair (no duplicates, no year dimension).
    """
    frames: list[pd.DataFrame] = []

    for path in paths:
        df = _read_file(path, "Erasmus+")

        dest_col   = _detect_column(df, ["coordinat"], "Erasmus+", "coordinator_country")
        origin_col = _detect_column(df, ["participat"], "Erasmus+", "participant_country")

        sub = df[[dest_col, origin_col]].copy()
        sub["destination_code"] = sub[dest_col].apply(_name_to_iso3)
        sub["origin_code"]      = sub[origin_col].apply(_name_to_iso3)
        frames.append(sub[["destination_code", "origin_code"]])

    if not frames:
        logger.warning("[Erasmus+] No files loaded - Erasmus+ pairs will be empty")
        return pd.DataFrame(columns=["destination_code", "origin_code"])

    pairs = (
        pd.concat(frames, ignore_index=True)
        .drop_duplicates()
        .query("destination_code in @EUROPEAN_ISO3 and origin_code in @AFRICAN_ISO3")
        .reset_index(drop=True)
    )
    logger.info("[Erasmus+] %d unique European-destination × African-origin pairs", len(pairs))
    return pairs


# ---------------------------------------------------------------------------
# Merge and imputation
# ---------------------------------------------------------------------------


def _merge_sources(
    df_unesco: pd.DataFrame,
    df_oecd: pd.DataFrame,
    df_erasmus: pd.DataFrame,
) -> pd.DataFrame:
    """Combine the three normalised source DataFrames into one analytical table.

    Strategy
    --------
    1. If UNESCO already contains a destination_code column (two-dimensional
       data), use it directly and join OECD scholarships on (year, destination).
    2. If UNESCO is one-dimensional (origin only), cross-join with Erasmus+
       pairs to generate the destination dimension, then join OECD.

    In both cases, scholarship amounts are repeated per origin row for the
       same (year, destination) so the correlation and model logic in
       pipeline/analysis.py can group by destination without re-aggregating.
    """
    if "destination_code" in df_unesco.columns:
        # UNESCO data already has destination dimension.
        df = df_unesco.copy()
        dest_names = (
            df_oecd[["destination_code", "destination_name"]]
            .drop_duplicates("destination_code")
        )
        df = df.merge(dest_names, on="destination_code", how="left")
        df["destination_name"] = df["destination_name"].fillna(
            df["destination_code"].map(ISO3_TO_NAME).fillna(df["destination_code"])
        )
    else:
        # One-dimensional UNESCO: expand via Erasmus+ pairs.
        df = df_unesco.merge(df_erasmus, on="origin_code", how="inner")
        dest_names = (
            df_oecd[["destination_code", "destination_name"]]
            .drop_duplicates("destination_code")
        )
        df = df.merge(dest_names, on="destination_code", how="left")
        df["destination_name"] = df["destination_name"].fillna(
            df["destination_code"].map(ISO3_TO_NAME).fillna(df["destination_code"])
        )
        # Distribute student_count equally across Erasmus+ destination partners.
        n_dest = df.groupby(["year", "origin_code"])["destination_code"].transform("nunique")
        df["student_count"] = df["student_count"] / n_dest.clip(lower=1)

    # Attach OECD scholarship amounts (destination/year level).
    df = df.merge(
        df_oecd[["year", "destination_code", "scholarship_musd"]],
        on=["year", "destination_code"],
        how="left",
    )

    # Aggregate to (year, destination, origin) - remove intra-group duplicates.
    df = df.groupby(
        ["year", "destination_code", "destination_name", "origin_code", "origin_name"],
        as_index=False,
    ).agg({"student_count": "sum", "scholarship_musd": "first"})

    return df


def _impute(df: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    """Interpolate missing numeric values within each time-series group.

    Linear interpolation is applied along the year axis within each
    (destination, origin) group for student_count, and within each
    destination group for scholarship_musd.  Remaining NaNs (at the
    edges of sparse series) are filled with 0.

    Returns:
        (imputed_df, count_of_values_imputed)
    """
    df = df.sort_values(["destination_code", "origin_code", "year"]).copy()

    nan_before = int(
        df["student_count"].isna().sum() + df["scholarship_musd"].isna().sum()
    )

    df["student_count"] = (
        df.groupby(["destination_code", "origin_code"])["student_count"]
        .transform(lambda s: s.interpolate(method="linear", limit_direction="both"))
    )
    df["scholarship_musd"] = (
        df.groupby("destination_code")["scholarship_musd"]
        .transform(lambda s: s.interpolate(method="linear", limit_direction="both"))
    )
    df["student_count"]    = df["student_count"].fillna(0)
    df["scholarship_musd"] = df["scholarship_musd"].fillna(0)

    nan_after = int(
        df["student_count"].isna().sum() + df["scholarship_musd"].isna().sum()
    )
    values_imputed = nan_before - nan_after
    return df, values_imputed


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def clean_and_merge(
    unesco_path: str,
    oecd_path: str | None = None,
    erasmus_paths: list[str] | None = None,
) -> tuple[pd.DataFrame, dict]:
    """Load, clean and merge the three mobility data sources.

    Args:
        unesco_path:   Absolute path to the UNESCO CSV file (mandatory).
        oecd_path:     Absolute path to the OECD scholarships file, or None
                       to use the bundled default (config.DEFAULT_OECD_PATH).
        erasmus_paths: List of absolute paths to Erasmus+ XLSX files, or None
                       to use the bundled defaults (config.DEFAULT_ERASMUS_PATHS).

    Returns:
        A tuple ``(df, stats)`` where:

        ``df`` has columns:
            year, destination_code, destination_name,
            origin_code, origin_name, student_count, scholarship_musd

        ``stats`` is a dict::

            {
                "row_count":             int,
                "duplicates_removed":    int,
                "values_imputed":        int,
                "origin_countries":      list[str],   # ISO-3 codes
                "destination_countries": list[str],   # ISO-3 codes
                "years_covered":         list[int],
            }

    Raises:
        ColumnDetectionError: When a mandatory column cannot be auto-detected
            in any source file.  The exception message names the source and
            the patterns that were tried.
    """
    if oecd_path is None:
        oecd_path = DEFAULT_OECD_PATH
    if not erasmus_paths:
        erasmus_paths = DEFAULT_ERASMUS_PATHS

    logger.info("clean_and_merge started (UNESCO=%s, OECD=%s)", unesco_path, oecd_path)

    df_unesco  = _load_unesco(unesco_path)
    df_oecd    = _load_oecd(oecd_path)
    df_erasmus = _load_erasmus(erasmus_paths)

    df = _merge_sources(df_unesco, df_oecd, df_erasmus)

    # De-duplicate before reporting.
    rows_before      = len(df)
    df               = df.drop_duplicates()
    duplicates_removed = rows_before - len(df)

    df, values_imputed = _impute(df)

    stats: dict = {
        "row_count":             len(df),
        "duplicates_removed":    duplicates_removed,
        "values_imputed":        values_imputed,
        "origin_countries":      sorted(df["origin_code"].unique().tolist()),
        "destination_countries": sorted(df["destination_code"].unique().tolist()),
        "years_covered":         sorted(df["year"].unique().tolist()),
    }

    logger.info(
        "clean_and_merge done: %d rows | %d origins | %d destinations | years %s–%s",
        stats["row_count"],
        len(stats["origin_countries"]),
        len(stats["destination_countries"]),
        min(stats["years_covered"]) if stats["years_covered"] else "?",
        max(stats["years_covered"]) if stats["years_covered"] else "?",
    )

    return df, stats
