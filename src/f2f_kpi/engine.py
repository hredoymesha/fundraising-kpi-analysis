"""Run the whole pipeline: load -> map -> validate -> KPIs -> classify. No UI or file output here."""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path

import pandas as pd

from .classify import classify_locations
from .config import Config, ConfigError, load_config
from .io import read_table
from .issues import IssueLog
from .kpis import attach_location_targets, compute_activity_kpis, compute_dimension_kpis, compute_location_kpis
from .mapping import apply_mapping
from .trends import compute_trends
from .validate import validate_activity, validate_fundraisers, validate_location_weekly, validate_locations


@dataclass
class Result:
    issues: pd.DataFrame  # every validation issue, all datasets
    activity: pd.DataFrame  # clean rows used for the KPIs
    overall: pd.DataFrame  # one row, whole file
    by_region: pd.DataFrame
    locations: pd.DataFrame | None = None  # clean location master
    by_location: pd.DataFrame | None = None  # from activity rows + master targets, classified
    location_weekly: pd.DataFrame | None = None  # clean pre-aggregated rows
    by_location_weekly: pd.DataFrame | None = None  # from location_weekly, classified
    skipped_kpis: dict[str, str] = field(default_factory=dict)
    rows_read: dict[str, int] = field(default_factory=dict)  # per dataset, before validation
    rows_kept: dict[str, int] = field(default_factory=dict)  # per dataset, after error rows are dropped
    by_dimension: pd.DataFrame | None = None  # KPIs per activity_type / fundraiser_id / ... (see report.dimensions)
    trends: pd.DataFrame | None = None  # per week or month, with period-over-period change
    location_overall: pd.DataFrame | None = None  # one row: attainment across every location that has a target


def _ids(df: pd.DataFrame | None, column: str) -> set[str] | None:
    return None if df is None or column not in df else set(df[column])


# Reference lists are checked first so that activity rows can be compared with them.
DATASET_ORDER = ["fundraisers", "locations", "activity", "location_weekly"]


def _views(config: Config, activity: pd.DataFrame, locations: pd.DataFrame | None,
           weekly: pd.DataFrame | None) -> dict:
    """Every KPI table derived from clean rows. Used for the full data and again for a filtered slice."""
    by_weekly = None
    if weekly is not None:
        by_weekly = classify_locations(compute_location_kpis(weekly, ["location_id"]), config.classification)
    if activity.empty:  # nothing usable (or a filter that matches nothing): zero-row tables, no guessing
        numeric = [c for c in ("doors_knocked", "conversations", "pledges", "total_monthly_value_eur", "active_hours")
                   if c in activity]
        base = activity.reindex(columns=(["region"] if "region" in activity else []) + numeric)
        base[numeric] = base[numeric].astype("float64")
        return dict(overall=compute_activity_kpis(base),
                    by_region=compute_activity_kpis(base, ["region"] if "region" in base else None),
                    by_location=None, location_overall=None, by_dimension=None, trends=None,
                    by_location_weekly=by_weekly)
    by_location = location_overall = None
    if locations is not None and "location_id" in activity:
        with_targets = attach_location_targets(activity, locations)
        by_location = classify_locations(compute_location_kpis(with_targets, ["location_id"]), config.classification)
        location_overall = compute_location_kpis(with_targets, [])
    dims = config.report.dimensions if config.report.dimensions is not None else ["activity_type", "fundraiser_id"]
    by_dimension = compute_dimension_kpis(activity, dims)
    trends = compute_trends(activity, config.report.trend_period)
    return dict(overall=compute_activity_kpis(activity), by_region=compute_activity_kpis(activity, ["region"]),
                by_location=by_location, location_overall=location_overall, by_location_weekly=by_weekly,
                by_dimension=by_dimension if len(by_dimension) else None, trends=trends if len(trends) else None)


def analyse(config: Config, raw: dict[str, pd.DataFrame]) -> Result:
    """Map, validate and summarise tables that are already loaded (see io.read_table and io.read_bytes).
    `raw` maps dataset names ('activity', 'locations', ...) to the raw all-text tables. 'activity' is required."""
    if "activity" not in raw:
        raise ConfigError("no activity data was supplied")
    log = IssueLog(config.validation.severity)
    rows_read: dict[str, int] = {}
    mapped: dict[str, pd.DataFrame] = {}
    for name in DATASET_ORDER:
        if name in raw:
            rows_read[name] = len(raw[name])
            mapped[name] = apply_mapping(raw[name], name, config, log)

    fundraisers = mapped.get("fundraisers")
    fundraisers = None if fundraisers is None else validate_fundraisers(fundraisers, config, log)
    locations = mapped.get("locations")
    locations = None if locations is None else validate_locations(locations, config, log)
    activity = validate_activity(mapped["activity"], config, log,
                                 fundraiser_ids=_ids(fundraisers, "fundraiser_id"),
                                 location_ids=_ids(locations, "location_id"))
    weekly = mapped.get("location_weekly")
    weekly = None if weekly is None else validate_location_weekly(weekly, config, log,
                                                                   location_ids=_ids(locations, "location_id"))

    views = _views(config, activity, locations, weekly)
    kept = {"activity": len(activity), "locations": None if locations is None else len(locations),
            "location_weekly": None if weekly is None else len(weekly),
            "fundraisers": None if fundraisers is None else len(fundraisers)}
    return Result(issues=log.to_frame(), activity=activity, locations=locations, location_weekly=weekly,
                  skipped_kpis=views["overall"].attrs.get("skipped_kpis", {}), rows_read=rows_read,
                  rows_kept={k: v for k, v in kept.items() if v is not None}, **views)


def run(config: Config) -> Result:
    """Read every file named in the config, then analyse."""
    return analyse(config, {name: read_table(spec, config.formats.decimal) for name, spec in config.inputs.items()})


def run_from_path(config_path: Path | str) -> Result:
    return run(load_config(config_path))


# ---- filtering (used by the web app; the report and the CLI always use everything) -----------------------

def filter_options(result: Result) -> dict:
    """What a region / date filter can offer: {'regions': [...], 'date_min': Timestamp|None, 'date_max': Timestamp|None}."""
    act = result.activity
    regions = sorted(act["region"].dropna().unique()) if "region" in act else []
    dates = act["date"].dropna() if "date" in act else pd.Series(dtype="datetime64[ns]")
    return {"regions": regions, "date_min": dates.min() if len(dates) else None,
            "date_max": dates.max() if len(dates) else None}


def filter_activity(activity: pd.DataFrame, regions=None, start=None, end=None) -> pd.DataFrame:
    """Rows in the given regions and between two dates, both ends included. A row with no date drops out of a date filter."""
    keep = pd.Series(True, index=activity.index)
    if regions is not None:
        keep &= activity["region"].isin(list(regions))
    if (start is not None or end is not None) and "date" in activity:
        day = activity["date"].dt.normalize()
        if start is not None:
            keep &= day >= pd.Timestamp(start)
        if end is not None:
            keep &= day <= pd.Timestamp(end)
    return activity[keep].reset_index(drop=True)


def with_filters(result: Result, config: Config, *, regions=None, start=None, end=None) -> Result:
    """The same result with every KPI table recalculated for the chosen regions and dates.
    Validation issues and row counts still describe the whole upload."""
    sub = filter_activity(result.activity, regions, start, end)
    return replace(result, activity=sub, **_views(config, sub, result.locations, result.location_weekly))
