"""Configurable location classification: tiers on target attainment, with a minimum-hours guard."""
from __future__ import annotations

import math

import pandas as pd

from .config import ClassificationConfig


def classify_value(attainment: float, hours: float, location_type: str | None, cfg: ClassificationConfig) -> tuple[str, str]:
    """Return (label, note). Tiers are inclusive lower bounds, highest first."""
    hours_ok = hours is not None and not (isinstance(hours, float) and math.isnan(hours))
    if not hours_ok or hours < cfg.min_hours:
        shown = f"{hours:g}" if hours_ok else "no"
        return cfg.insufficient_label, f"only {shown} hours (minimum {cfg.min_hours:g})"
    if attainment is None or (isinstance(attainment, float) and math.isnan(attainment)):
        return cfg.insufficient_label, "no target PPH to compare against"
    tiers = cfg.tiers_by_type.get(location_type, cfg.tiers) if location_type else cfg.tiers
    for tier in tiers:  # config loader sorts these highest first
        if round(attainment, 9) >= tier.min:  # rounding avoids 0.7499999999 missing a 0.75 boundary
            return tier.label, f"{attainment:.0%} of target over {hours:g} hours (tier starts at {tier.min:.0%})"
    return tiers[-1].label, f"{attainment:.0%} of target over {hours:g} hours"


def classify_locations(kpis: pd.DataFrame, cfg: ClassificationConfig) -> pd.DataFrame:
    """Add planning_priority and classification_note to a compute_location_kpis result."""
    out = kpis.copy()
    types = out["location_type"] if "location_type" in out else pd.Series([None] * len(out), index=out.index)
    results = [classify_value(a, h, t, cfg) for a, h, t in zip(out["target_attainment"], out["hours"], types)]
    out["planning_priority"] = [r[0] for r in results]
    out["classification_note"] = [r[1] for r in results]
    return out
