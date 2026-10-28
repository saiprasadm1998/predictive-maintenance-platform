"""prognostics.

Trend fitting, time-to-threshold forecasts, urgency and scheduled forecasts.

Public interface of the module (ARC-001 §4.1). Other modules may import only
what this file exports, never the module's internal files.
"""

from pmp.prognostics.domain import (
    BOOTSTRAP,
    MIN_POINTS,
    Fit,
    Forecast,
    ForecastError,
    Method,
    Urgency,
    UrgencyBands,
    fit_trend,
    forecast,
)
from pmp.prognostics.service import (
    DEFAULT_WINDOW_DAYS,
    MAX_WINDOW_DAYS,
    ForecastRequest,
    ForecastView,
    Target,
    ThresholdKind,
    describe,
    get_forecast,
    latest_for_alerts,
    list_forecasts,
    run_forecast,
)

__all__ = [
    "BOOTSTRAP",
    "DEFAULT_WINDOW_DAYS",
    "MAX_WINDOW_DAYS",
    "MIN_POINTS",
    "Fit",
    "Forecast",
    "ForecastError",
    "ForecastRequest",
    "ForecastView",
    "Method",
    "Target",
    "ThresholdKind",
    "Urgency",
    "UrgencyBands",
    "describe",
    "fit_trend",
    "forecast",
    "get_forecast",
    "latest_for_alerts",
    "list_forecasts",
    "run_forecast",
]
