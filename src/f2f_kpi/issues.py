"""Validation issues: one record per problem, with enough context to fix the source file."""
from __future__ import annotations

from dataclasses import dataclass, asdict

import pandas as pd

ERROR, WARNING, IGNORE = "error", "warning", "ignore"

# rule id -> (default severity, what it means).
# "error" rows are excluded from KPI calculations; "warning" rows are kept (and corrected where noted).
RULES: dict[str, tuple[str, str]] = {
    "missing_column": (ERROR, "A required column could not be found in the file."),
    "missing_required_value": (ERROR, "A required value is blank."),
    "non_numeric_value": (ERROR, "A numeric field contains text that is not a number."),
    "unparseable_date": (ERROR, "The date could not be read."),
    "negative_value": (ERROR, "A count or amount is negative."),
    "negative_hours": (ERROR, "Hours are negative."),
    "zero_hours_with_activity": (ERROR, "Hours are zero although pledges were recorded."),
    "conversations_gt_doors": (ERROR, "More conversations than doors knocked."),
    "pledges_gt_conversations": (ERROR, "More pledges than conversations."),
    "duplicate_location_id": (ERROR, "Location ID appears again with different details; only its first row is used."),
    "exact_duplicate_row": (ERROR, "Row repeats an earlier row exactly; only the first copy is kept."),
    "achieved_pph_mismatch": (WARNING, "Supplied achieved_pph differs from pledges / hours; the recomputed value is used."),
    "implausible_hours": (WARNING, "Hours exceed the configured maximum per row."),
    "implausible_value_per_pledge": (WARNING, "Monthly value per pledge exceeds the configured maximum."),
    "date_out_of_range": (WARNING, "Date is far outside the period covered by the rest of the file."),
    "inconsistent_region_label": (WARNING, "Same region spelled differently (case or spaces); normalised to the common spelling."),
    "unknown_fundraiser_id": (WARNING, "Fundraiser ID is not in the fundraiser list."),
    "unknown_location_id": (WARNING, "Location ID is not in the location list."),
}

COLUMNS = ["dataset", "row", "column", "rule", "severity", "value", "message"]


@dataclass(frozen=True)
class Issue:
    dataset: str
    row: int | None  # line number in the source file (header = header_row); None for file-level issues
    column: str | None
    rule: str
    severity: str
    value: str | None
    message: str


class IssueLog:
    """Collects issues, applying severity overrides from the config (including 'ignore')."""

    def __init__(self, overrides: dict[str, str] | None = None):
        self._overrides = overrides or {}
        self.items: list[Issue] = []

    def severity(self, rule: str) -> str:
        return self._overrides.get(rule, RULES[rule][0])

    def add(self, dataset: str, rule: str, message: str, *, row: int | None = None,
            column: str | None = None, value: object = None) -> None:
        sev = self.severity(rule)
        if sev == IGNORE:
            return
        text = None if value is None or (isinstance(value, float) and pd.isna(value)) else str(value)
        self.items.append(Issue(dataset, row, column, rule, sev, text, message))

    def to_frame(self) -> pd.DataFrame:
        if not self.items:
            return pd.DataFrame(columns=COLUMNS)
        return pd.DataFrame([asdict(i) for i in self.items], columns=COLUMNS)

    def error_rows(self, dataset: str) -> set[int]:
        return {i.row for i in self.items if i.dataset == dataset and i.severity == ERROR and i.row is not None}
