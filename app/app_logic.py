"""Everything the web app needs that is not drawing. Kept free of Streamlit so it can be tested on its own.

The numbers all come from f2f_kpi. This module only chooses defaults, builds a config from the user's choices,
and formats finished results for display.
"""
from __future__ import annotations

import copy
import math
import re
from dataclasses import dataclass

import pandas as pd
import yaml

from f2f_kpi import Config, ConfigError, Result, config_from_dict
from f2f_kpi.profile import suggest_mapping
from f2f_kpi.schema import DATASETS

NOT_MAPPED = "(not in my file)"
UPLOAD_TYPES = ["csv", "xlsx", "xlsm", "txt", "tsv"]

FIELD_LABELS = {
    "activity": {
        "region": "Region", "pledges": "Pledges (sign-ups)", "active_hours": "Active hours", "date": "Date",
        "doors_knocked": "Doors knocked (or people approached)", "conversations": "Conversations",
        "total_monthly_value_eur": "Total monthly value (EUR)", "shift_id": "Shift ID",
        "location_id": "Location ID", "fundraiser_id": "Fundraiser ID", "activity_type": "Activity type",
    },
    "locations": {
        "location_id": "Location ID", "target_pph": "Target pledges per hour", "location_label": "Location name",
        "region": "Region", "location_type": "Location type",
    },
}
DATASET_NAMES = {"activity": "Activity file", "locations": "Location list"}

DELIMITERS = {"Detect automatically": None, "Comma ( , )": ",", "Semicolon ( ; )": ";", "Tab": "\t", "Pipe ( | )": "|"}
ENCODINGS = {"UTF-8 (most files)": "utf-8-sig", "Windows Western European": "cp1252", "Latin-1": "latin-1"}


_MARKDOWN_SPECIAL = set(chr(92) + "`*_[]()!|~<>$:&")  # list and heading markers only matter at the start of a line


def markdown_safe(text: object) -> str:
    """Text from the user's files, made safe to put inside a Streamlit message. Markdown would otherwise turn a
    header like '![x](https://...)' into an image that the browser fetches, or a link, or a ':red[...]' style."""
    one_line = " ".join(str(text).split())
    return "".join(chr(92) + c if c in _MARKDOWN_SPECIAL else c for c in one_line)


# ---- config -----------------------------------------------------------------------------------------

def default_config() -> Config:
    return config_from_dict({}, require_activity=False)


def parse_config_text(text: str) -> Config:
    """A user-supplied YAML config. File paths inside it are ignored: the app only uses what was uploaded."""
    try:
        raw = yaml.safe_load(text) or {}
    except yaml.YAMLError:
        raise ConfigError("that file is not valid YAML") from None
    if not isinstance(raw, dict):
        raise ConfigError("the top level of the config must be a list of settings (a YAML mapping)")
    return config_from_dict(raw, require_activity=False)


def build_config(base: Config, mappings: dict[str, dict[str, str | None]], *, decimal: str | None = None,
                 date_format: str | None = None) -> Config:
    """A copy of `base` with the dropdown choices written into `columns` and the number/date format applied.
    A field left as 'not in my file' is written as an empty list, so it stays unmapped even if a header happens
    to carry its name."""
    config = copy.deepcopy(base)
    for dataset, mapping in mappings.items():
        config.columns[dataset] = {field: ([header] if header else []) for field, header in mapping.items()}
    if decimal:
        config.formats.decimal = decimal
    if date_format is not None:
        config.formats.date = date_format.strip() or None
    return config


# ---- column mapping ---------------------------------------------------------------------------------

def initial_mapping(columns: list[str], dataset: str, config: Config) -> dict[str, str | None]:
    """Starting point for the dropdowns: headers named in the config first, then the best name-based guesses."""
    by_key = {c.strip().casefold(): c for c in columns}
    mapping: dict[str, str | None] = {f.name: None for f in DATASETS[dataset]}
    used: set[str] = set()
    for field, headers in config.columns.get(dataset, {}).items():
        for header in headers:
            found = by_key.get(header.strip().casefold())
            if found and found not in used:
                mapping[field] = found
                used.add(found)
                break
    suggestions, _, _ = suggest_mapping([c for c in columns if c not in used], dataset)
    for s in suggestions:
        if mapping[s.field] is None:
            mapping[s.field] = s.column
    return mapping


def is_required(dataset: str, field: str) -> bool:
    return any(f.required for f in DATASETS[dataset] if f.name == field)


def missing_required(mapping: dict[str, str | None], dataset: str) -> list[str]:
    return [f.name for f in DATASETS[dataset] if f.required and not mapping.get(f.name)]


def reused_headers(mapping: dict[str, str | None]) -> list[str]:
    """Headers chosen for more than one field."""
    chosen = [h for h in mapping.values() if h]
    return sorted({h for h in chosen if chosen.count(h) > 1})


def label_for(dataset: str, field: str) -> str:
    return FIELD_LABELS.get(dataset, {}).get(field, field)


# ---- KPI cards --------------------------------------------------------------------------------------

@dataclass(frozen=True)
class Card:
    label: str
    value: str  # already formatted for display
    note: str  # why it is missing, or a short explanation
    available: bool


def _number(frame: pd.DataFrame | None, column: str) -> float | None:
    if frame is None or frame.empty or column not in frame.columns:
        return None
    value = frame.iloc[0][column]
    return None if value is None or (isinstance(value, float) and math.isnan(value)) else float(value)


def kpi_cards(result: Result) -> list[Card]:
    """The five headline cards, for whatever slice `result` describes."""
    specs = [
        ("Conversation rate", result.overall, "conversation_rate", lambda v: f"{v:.1%}", "conversations ÷ doors knocked",
         "Needs the conversations and doors knocked columns."),
        ("Pledge rate", result.overall, "pledge_rate", lambda v: f"{v:.1%}", "pledges ÷ conversations",
         "Needs the pledges and conversations columns."),
        ("Pledges per hour", result.overall, "pledges_per_hour", lambda v: f"{v:.2f}", "pledges ÷ active hours",
         "Needs the pledges and active hours columns."),
        ("Average monthly gift", result.overall, "avg_monthly_donation_eur", lambda v: f"€{v:,.2f}",
         "total monthly value ÷ pledges", "Needs the total monthly value column."),
        ("Target attainment", result.location_overall, "target_attainment", lambda v: f"{v:.0%}",
         "achieved PPH ÷ target PPH, across all locations",
         "Needs a location list with a target PPH, and a location ID in the activity file."),
    ]
    cards = []
    for label, frame, column, fmt, explanation, why_missing in specs:
        value = _number(frame, column)
        has_column = frame is not None and column in frame.columns and not frame.empty
        if value is not None:
            cards.append(Card(label, fmt(value), explanation, True))
        elif has_column:
            cards.append(Card(label, "—", "Not defined for this selection (nothing to divide by).", False))
        else:
            cards.append(Card(label, "—", why_missing, False))
    return cards


# ---- tables for display -----------------------------------------------------------------------------

def issues_table(issues: pd.DataFrame, severities: list[str] | None = None) -> pd.DataFrame:
    df = issues if severities is None else issues[issues["severity"].isin(severities)]
    out = pd.DataFrame({
        "Severity": df["severity"], "File": df["dataset"].map(lambda d: DATASET_NAMES.get(d, d)),
        "Row in file": df["row"].astype("Int64"), "Column": df["column"], "Rule": df["rule"],
        "Value found": df["value"], "What is wrong": df["message"],
    })
    order = {"error": 0, "warning": 1}
    return out.sort_values(["Severity", "File", "Row in file"], key=lambda s: s.map(order) if s.name == "Severity" else s,
                           kind="stable").reset_index(drop=True)


def location_ranking(result: Result) -> pd.DataFrame | None:
    """Locations best to worst against target, with the engine's planning tier. None if there is nothing to rank."""
    table = result.by_location
    if table is None or table.empty:
        return None
    name = table["location_label"] if "location_label" in table else table["location_id"]
    out = pd.DataFrame({
        "Rank": range(1, len(table) + 1), "Location": name.fillna(table["location_id"]).to_numpy(),
        "Type": table["location_type"].to_numpy() if "location_type" in table else "",
        "Pledges": table["pledges"].to_numpy(), "Hours": table["hours"].to_numpy(),
        "Target PPH": table["target_pph"].to_numpy(), "Achieved PPH": table["achieved_pph"].to_numpy(),
        "Target attainment (%)": (table["target_attainment"] * 100).to_numpy(),
        "Planning tier": table["planning_priority"].to_numpy(), "Why": table["classification_note"].to_numpy(),
    })
    return out


def tier_counts(result: Result, config: Config) -> list[tuple[str, int]]:
    """How many locations sit in each tier, in the order the config lists them."""
    if result.by_location is None or result.by_location.empty:
        return []
    counts = result.by_location["planning_priority"].value_counts()
    labels = [t.label for t in config.classification.tiers] + [config.classification.insufficient_label]
    return [(label, int(counts[label])) for label in labels if label in counts]


def describe_filters(regions: list[str] | None, all_regions: list[str], start, end, full_start, full_end) -> str:
    parts = []
    if regions is not None and set(regions) != set(all_regions):
        parts.append(f"{len(regions)} of {len(all_regions)} regions")
    if start is not None and (start != full_start or end != full_end):
        parts.append(f"{pd.Timestamp(start):%d %b %Y} to {pd.Timestamp(end):%d %b %Y}")
    return ", ".join(parts) if parts else "everything"
