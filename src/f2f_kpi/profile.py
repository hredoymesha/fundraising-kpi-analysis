"""Look at a new export and suggest which column is which. A person confirms the result - nothing is applied silently."""
from __future__ import annotations

import difflib
import re
import unicodedata
from dataclasses import dataclass

from .schema import DATASETS

# Headers teams commonly use for each field. Matching ignores case, accents and punctuation.
SYNONYMS: dict[str, list[str]] = {
    "date": ["date", "day", "shift date", "work date", "datum"],
    "region": ["region", "area", "territory", "zone", "district", "team area", "gebiet"],
    "pledges": ["pledges", "sign ups", "signups", "signed up", "new donors", "donors", "commitments", "supporters",
                "sales", "zusagen"],
    "active_hours": ["active hours", "hours", "hrs", "hours worked", "working hours", "time on street", "stunden"],
    "doors_knocked": ["doors knocked", "doors", "contacts", "approaches", "people approached", "knocks", "approached"],
    "conversations": ["conversations", "convos", "talks", "chats", "engaged", "gespraeche"],
    "total_monthly_value_eur": ["total monthly value eur", "monthly value", "monthly value eur", "monthly amount",
                                "monthly eur", "total monthly", "value", "amount", "euro"],
    "shift_id": ["shift id", "shift", "record id", "row id"],
    "location_id": ["location id", "location", "venue id", "site id", "stand id", "location code"],
    "fundraiser_id": ["fundraiser id", "fundraiser", "agent", "agent id", "canvasser", "rep", "staff id", "employee id"],
    "activity_type": ["activity type", "activity", "channel", "method", "type of activity"],
    "target_pph": ["target pph", "target", "target pledges per hour", "goal pph", "pph target"],
    "location_label": ["location label", "location name", "venue", "venue name", "site", "site name", "stand"],
    "location_type": ["location type", "venue type", "site type", "kind"],
    "period": ["period", "week", "iso week", "month", "reporting period"],
    "achieved_pph": ["achieved pph", "actual pph", "pph", "pledges per hour"],
    "avg_monthly_donation_eur": ["avg monthly donation eur", "average monthly donation", "avg donation", "avg monthly eur"],
    "monthly_pledge_share": ["monthly pledge share", "monthly share"],
    "regular_giving_share": ["regular giving share", "regular share"],
    "avg_supporter_age": ["avg supporter age", "average age", "avg age"],
}
THRESHOLD = 0.72


@dataclass(frozen=True)
class Suggestion:
    column: str  # header as it appears in the file
    field: str  # canonical field name
    score: float

    @property
    def confidence(self) -> str:
        return "exact" if self.score >= 0.95 else "likely" if self.score >= 0.8 else "check this one"


def _norm(text: str) -> str:
    text = unicodedata.normalize("NFKD", str(text)).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def _score(header: str, field: str) -> float:
    h = _norm(header)
    names = {_norm(field)} | {_norm(s) for s in SYNONYMS.get(field, [])}
    if h in names:
        return 1.0
    return max(difflib.SequenceMatcher(None, h, n).ratio() for n in names)


def suggest_mapping(columns: list[str], dataset: str = "activity") -> tuple[list[Suggestion], list[str], list[str]]:
    """Return (suggestions, required fields nobody matched, columns left unused). Each column and field is used once."""
    fields = [f.name for f in DATASETS[dataset]]
    pairs = sorted(((_score(c, f), c, f) for c in columns for f in fields), key=lambda t: (-t[0], t[1], t[2]))
    used_cols: set[str] = set()
    used_fields: set[str] = set()
    picked: list[Suggestion] = []
    for score, col, fld in pairs:
        if score < THRESHOLD or col in used_cols or fld in used_fields:
            continue
        picked.append(Suggestion(col, fld, round(score, 2)))
        used_cols.add(col)
        used_fields.add(fld)
    order = {f: i for i, f in enumerate(fields)}
    picked.sort(key=lambda s: order[s.field])
    missing = [f.name for f in DATASETS[dataset] if f.required and f.name not in used_fields]
    return picked, missing, [c for c in columns if c not in used_cols]


def columns_yaml(suggestions: list[Suggestion], dataset: str = "activity", indent: int = 2) -> str:
    """The `columns:` block for a config file. Only fields whose header differs from the canonical name are listed."""
    pad = " " * indent
    # the loader already matches a header that equals the field name apart from case and outer spaces
    lines = [f"{pad * 2}{s.field}: {_quote(s.column)}" for s in suggestions
             if s.column.strip().casefold() != s.field.casefold()]
    if not lines:
        return "columns: {}"
    return f"columns:\n{pad}{dataset}:\n" + "\n".join(lines)


def _quote(text: str) -> str:
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def describe(columns: list[str], sample_rows: list[dict[str, str]], dataset: str = "activity") -> str:
    """The text `f2f-kpi profile` prints."""
    suggestions, missing, unused = suggest_mapping(columns, dataset)
    out = [f"Found {len(columns)} column(s). Best guess for the '{dataset}' data:", ""]
    width = max([len(s.column) for s in suggestions] + [6])
    for s in suggestions:
        example = next((r.get(s.column, "") for r in sample_rows if r.get(s.column, "") != ""), "")
        out.append(f"  {s.column:<{width}}  ->  {s.field:<26} {s.confidence:<14} e.g. {example}")
    if missing:
        out += ["", "Required fields with no matching column yet: " + ", ".join(missing),
                "Add them under `columns:` in your config once you know which header they are."]
    if unused:
        out += ["", "Columns not used: " + ", ".join(unused)]
    out += ["", "Paste this into your config (and check the 'check this one' lines first):", "",
            columns_yaml(suggestions, dataset)]
    return "\n".join(out)
