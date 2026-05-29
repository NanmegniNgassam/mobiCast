"""MobiCast - analysis and prediction pipeline.

Takes the cleaned DataFrame produced by pipeline.cleaning.clean_and_merge()
and returns a structured result dict consumed by the results view.

One LinearRegression model is trained per destination country using Year as
the sole predictor of African_Students_Count.  Forecast horizon: 2024–2028.
"""

import logging
from typing import Any

import numpy as np
import pandas as pd
from sklearn.linear_model import LinearRegression
from sklearn.metrics import mean_absolute_error, r2_score

from pipeline.cleaning import ISO3_TO_NAME

logger = logging.getLogger(__name__)

# Years for which forecasts are generated.
FORECAST_YEARS: list[int] = list(range(2024, 2029))

# Columns used in the correlation analysis.
CORRELATION_COLUMNS: list[str] = [
    "Year",
    "Scholarship_Amount_MUSD",
    "African_Students_Count",
]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _aggregate_by_destination(df: pd.DataFrame) -> pd.DataFrame:
    """Aggregate the cleaned DataFrame to (Year, destination) level.

    Sums student_count across all origin countries for each (year, destination)
    pair.  Scholarship amounts are already at destination/year level, so the
    first non-null value per group is kept.

    Args:
        df: Output of clean_and_merge() with columns year, destination_code,
            destination_name, origin_code, origin_name, student_count,
            scholarship_musd.

    Returns:
        DataFrame with columns: Year, destination_code, destination_name,
        African_Students_Count, Scholarship_Amount_MUSD.
    """
    agg = (
        df.groupby(["year", "destination_code", "destination_name"], as_index=False)
        .agg(
            African_Students_Count=("student_count", "sum"),
            Scholarship_Amount_MUSD=("scholarship_musd", "first"),
        )
        .rename(columns={"year": "Year"})
        .sort_values(["destination_code", "Year"])
    )
    return agg


def _train_model(
    group: pd.DataFrame,
) -> tuple[LinearRegression, float, float]:
    """Fit a LinearRegression(Year → African_Students_Count) on a single destination.

    Args:
        group: Rows for one destination country, sorted by Year.

    Returns:
        Tuple (fitted_model, r2_score, mean_absolute_error).
    """
    X = group[["Year"]].values
    y = group["African_Students_Count"].values

    model = LinearRegression()
    model.fit(X, y)

    y_pred = model.predict(X)
    r2  = float(r2_score(y, y_pred))
    mae = float(mean_absolute_error(y, y_pred))

    return model, r2, mae


def _build_predictions(df_agg: pd.DataFrame) -> list[dict]:
    """Train one model per destination and collect structured prediction records.

    Args:
        df_agg: Aggregated DataFrame from _aggregate_by_destination().

    Returns:
        List of prediction dicts, one per destination country, sorted by
        the last forecast year value descending.
    """
    predictions: list[dict] = []
    forecast_X = np.array(FORECAST_YEARS, dtype=float).reshape(-1, 1)

    for (dest_code, dest_name), group in df_agg.groupby(
        ["destination_code", "destination_name"]
    ):
        group = group.sort_values("Year")

        if len(group) < 2:
            logger.warning(
                "Skipping destination %s (%s): only %d data point(s)",
                dest_code, dest_name, len(group),
            )
            continue

        model, r2, mae = _train_model(group)

        raw_forecasts = model.predict(forecast_X)
        # Student counts cannot be negative.
        forecast_values = [round(max(0.0, v), 1) for v in raw_forecasts]

        predictions.append({
            "country_code":     dest_code,
            "country_name":     dest_name,
            "historical_years": group["Year"].astype(int).tolist(),
            "historical_values": [
                round(v, 1) for v in group["African_Students_Count"].tolist()
            ],
            "forecast_years":   FORECAST_YEARS,
            "forecast_values":  forecast_values,
            "r2":               round(r2, 4),
            "mae":              round(mae, 2),
            "coefficient":      round(float(model.coef_[0]), 4),
            "intercept":        round(float(model.intercept_), 2),
        })

    predictions.sort(key=lambda p: p["forecast_values"][-1], reverse=True)
    return predictions


def _build_correlations(df_agg: pd.DataFrame) -> dict[str, dict]:
    """Compute a Pearson correlation matrix per destination country.

    Correlates Year, Scholarship_Amount_MUSD and African_Students_Count.

    Args:
        df_agg: Aggregated DataFrame from _aggregate_by_destination().

    Returns:
        Dict mapping destination ISO-3 code → {matrix: list[list[float]],
        columns: list[str]}.
    """
    correlations: dict[str, dict] = {}

    for (dest_code, _), group in df_agg.groupby(
        ["destination_code", "destination_name"]
    ):
        sub = group[CORRELATION_COLUMNS].dropna()

        if len(sub) < 2:
            logger.debug(
                "Skipping correlation for %s: insufficient non-null rows", dest_code
            )
            continue

        # Replace any constant columns with near-zero std to avoid NaN in corr matrix.
        if sub.std().eq(0).any():
            logger.debug(
                "Constant column detected for %s - correlation may be NaN", dest_code
            )

        matrix = sub.corr(method="pearson").round(4).fillna(0).values.tolist()
        correlations[dest_code] = {
            "matrix":  matrix,
            "columns": CORRELATION_COLUMNS,
        }

    return correlations


def _build_rankings(predictions: list[dict]) -> dict[str, list[dict]]:
    """Build country rankings for each forecast year.

    Args:
        predictions: Output of _build_predictions().

    Returns:
        Dict mapping year string (e.g. "2024") → list of
        {country_code, country_name, students}, sorted descending by students.
    """
    rankings: dict[str, list[dict]] = {}

    for idx, year in enumerate(FORECAST_YEARS):
        year_rows = [
            {
                "country_code": p["country_code"],
                "country_name": p["country_name"],
                "students":     int(round(p["forecast_values"][idx])),
            }
            for p in predictions
        ]
        year_rows.sort(key=lambda r: r["students"], reverse=True)
        rankings[str(year)] = year_rows

    return rankings


def _available_countries(
    df: pd.DataFrame, code_col: str, name_col: str
) -> list[dict]:
    """Return a sorted list of {code, name} dicts for a country dimension.

    Args:
        df:       Source DataFrame.
        code_col: Column holding ISO-3 codes.
        name_col: Column holding human-readable names.

    Returns:
        List of dicts sorted by name.
    """
    pairs = (
        df[[code_col, name_col]]
        .drop_duplicates()
        .sort_values(name_col)
    )
    return [
        {
            "code": row[code_col],
            "name": ISO3_TO_NAME.get(row[code_col], row[name_col]),
        }
        for _, row in pairs.iterrows()
    ]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def run_analysis(df: pd.DataFrame) -> dict[str, Any]:
    """Run the full analysis pipeline on the cleaned mobility DataFrame.

    Trains one LinearRegression per destination country (Year as predictor),
    computes Pearson correlations between Year / Scholarship_Amount_MUSD /
    African_Students_Count, generates forecast rankings for 2024–2028, and
    collects the available country lists for UI dropdowns.

    Args:
        df: Cleaned DataFrame from pipeline.cleaning.clean_and_merge().
            Required columns: year, destination_code, destination_name,
            origin_code, origin_name, student_count, scholarship_musd.

    Returns:
        Dict with the following structure::

            {
              "predictions": [
                {
                  "country_code": "FRA",
                  "country_name": "France",
                  "historical_years":  [2017, 2018, ...],
                  "historical_values": [5650.0, 4761.0, ...],
                  "forecast_years":    [2024, 2025, 2026, 2027, 2028],
                  "forecast_values":   [8100.0, ...],
                  "r2":          0.87,
                  "mae":         312.4,
                  "coefficient": 410.2,
                  "intercept":   -820000.1
                },
                ...
              ],
              "correlations": {
                "FRA": {
                  "matrix":  [[1.0, 0.72, ...], ...],
                  "columns": ["Year", "Scholarship_Amount_MUSD",
                               "African_Students_Count"]
                },
                ...
              },
              "rankings": {
                "2024": [
                  {"country_code": "FRA", "country_name": "France",
                   "students": 8100},
                  ...
                ],
                ...
              },
              "available_origin_countries": [
                {"code": "CMR", "name": "Cameroun"}, ...
              ],
              "available_destination_countries": [
                {"code": "FRA", "name": "France"}, ...
              ]
            }
    """
    logger.info("run_analysis started - %d rows in input DataFrame", len(df))

    df_agg = _aggregate_by_destination(df)
    logger.debug(
        "Aggregated to %d (year × destination) rows across %d destinations",
        len(df_agg),
        df_agg["destination_code"].nunique(),
    )

    predictions  = _build_predictions(df_agg)
    correlations = _build_correlations(df_agg)
    rankings     = _build_rankings(predictions)

    result: dict[str, Any] = {
        "predictions":  predictions,
        "correlations": correlations,
        "rankings":     rankings,
        "available_origin_countries": _available_countries(
            df, "origin_code", "origin_name"
        ),
        "available_destination_countries": _available_countries(
            df, "destination_code", "destination_name"
        ),
    }

    logger.info(
        "run_analysis complete - %d models trained, forecasts for years %s",
        len(predictions),
        FORECAST_YEARS,
    )
    return result
