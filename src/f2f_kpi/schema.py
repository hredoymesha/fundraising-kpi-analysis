"""Canonical field names. Config maps each team's column headers onto these."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Field:
    name: str
    dtype: str  # "str" | "float" | "date"
    required: bool = False


ACTIVITY = [  # one row per shift / day (activity grain)
    Field("region", "str", True),
    Field("pledges", "float", True),
    Field("active_hours", "float", True),
    Field("date", "date"),
    Field("doors_knocked", "float"),
    Field("conversations", "float"),
    Field("total_monthly_value_eur", "float"),
    Field("shift_id", "str"),
    Field("location_id", "str"),
    Field("fundraiser_id", "str"),
    Field("activity_type", "str"),
]

LOCATIONS = [  # location master list with targets
    Field("location_id", "str", True),
    Field("target_pph", "float", True),
    Field("location_label", "str"),
    Field("region", "str"),
    Field("location_type", "str"),
]

LOCATION_WEEKLY = [  # pre-aggregated location x period rows
    Field("period", "str", True),
    Field("location_id", "str", True),
    Field("pledges", "float", True),
    Field("hours", "float", True),
    Field("target_pph", "float", True),
    Field("achieved_pph", "float"),
    Field("location_label", "str"),
    Field("location_type", "str"),
    Field("monthly_pledge_share", "float"),
    Field("regular_giving_share", "float"),
    Field("avg_supporter_age", "float"),
    Field("avg_monthly_donation_eur", "float"),
]

FUNDRAISERS = [
    Field("fundraiser_id", "str", True),
]

DATASETS = {
    "activity": ACTIVITY,
    "locations": LOCATIONS,
    "location_weekly": LOCATION_WEEKLY,
    "fundraisers": FUNDRAISERS,
}
