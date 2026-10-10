"""f2f_kpi: a reusable engine for face-to-face fundraising KPIs. Pure Python / pandas; no UI dependencies."""
__version__ = "0.1.0"

from .config import Config, ConfigError, config_from_dict, load_config
from .engine import Result, analyse, filter_options, run, run_from_path, with_filters
from .kpis import (avg_monthly_donation, compute_activity_kpis, compute_dimension_kpis, compute_location_kpis,
                   conversation_rate, pledge_rate, pledges_per_hour, target_attainment)
from .trends import compute_trends

__all__ = [
    "__version__", "write_report", "report_bytes", "analyse", "with_filters", "filter_options",
    "Config", "ConfigError", "Result", "config_from_dict", "load_config", "run", "run_from_path",
    "compute_activity_kpis", "compute_dimension_kpis", "compute_location_kpis", "compute_trends",
    "conversation_rate", "pledge_rate", "pledges_per_hour", "target_attainment", "avg_monthly_donation",
]
from .report import report_bytes, write_report  # noqa: E402  (after __version__, which the report imports)
