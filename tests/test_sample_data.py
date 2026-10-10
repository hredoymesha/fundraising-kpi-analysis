"""The synthetic data in data/sample/ and its documented errors (injected_errors.csv) against the engine."""
import csv
from pathlib import Path

import pytest

from f2f_kpi import run_from_path

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "data" / "sample"
DATASET_OF = {"shifts.csv": "activity", "location_weekly.csv": "location_weekly"}
# rules that only warn under config/sample.yaml: the row stays in the clean data
WARN_ONLY = {"inconsistent_region_label", "achieved_pph_mismatch"}


def read(name):
    with (SAMPLE / name).open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


@pytest.fixture(scope="module")
def result():
    return run_from_path(ROOT / "config" / "sample.yaml")


@pytest.fixture(scope="module")
def manifest():
    return read("injected_errors.csv")


def expected_row(entry):
    lines = [int(x) for x in entry["csv_line"].split("|")]
    return lines[-1]  # for the duplicate, the issue belongs on the later copy


# ---- the sample data matches its description -----------------------------------------------------

def test_sample_data_shape():
    shifts, fundraisers, locations = read("shifts.csv"), read("fundraisers.csv"), read("locations.csv")
    assert len({r["iso_week"] for r in shifts}) == 12
    assert len({r["region"] for r in locations}) == 5
    assert len(locations) == 30
    assert len(fundraisers) == 40 and all(f["fundraiser_id"].startswith("F") for f in fundraisers)


# ---- every documented error is found, and nothing else is -----------------------------------------

def test_every_documented_error_is_reported_with_the_right_rule_and_row(result, manifest):
    found = {(i.dataset, i.row, i.rule) for i in result.issues.itertuples()}
    for entry in manifest:
        key = (DATASET_OF[entry["file"]], expected_row(entry), entry["rule"])
        assert key in found, f"not detected: {entry['rule']} at {entry['file']} line {expected_row(entry)}"


def test_no_issues_beyond_the_documented_ones(result, manifest):
    found = {(i.dataset, i.row, i.rule) for i in result.issues.itertuples()}
    documented = {(DATASET_OF[m["file"]], expected_row(m), m["rule"]) for m in manifest}
    assert found == documented
    assert len(result.issues) == len(manifest) == 14


@pytest.mark.parametrize("rule", [
    "conversations_gt_doors", "pledges_gt_conversations", "negative_hours", "zero_hours_with_activity",
    "missing_required_value", "implausible_hours", "unparseable_date", "non_numeric_value",
    "inconsistent_region_label", "unknown_fundraiser_id", "implausible_value_per_pledge", "date_out_of_range",
    "exact_duplicate_row", "achieved_pph_mismatch",
])
def test_each_rule_has_its_own_documented_case(rule, result, manifest):
    assert rule in {m["rule"] for m in manifest}
    assert rule in set(result.issues["rule"])


def test_issues_carry_context_a_person_can_act_on(result):
    row = result.issues[result.issues["rule"] == "non_numeric_value"].iloc[0]
    assert row["column"] == "pledges" and row["value"] == "n/a" and "not a number" in row["message"]
    assert row["dataset"] == "activity" and row["severity"] == "error"


# ---- error rows are excluded; warning rows are kept and corrected -----------------------------------

def test_error_rows_are_dropped_and_warning_rows_kept(result, manifest):
    shifts = read("shifts.csv")
    assert len(shifts) == 1557
    dropped = [m for m in manifest if m["file"] == "shifts.csv" and m["rule"] not in WARN_ONLY]
    assert len(dropped) == 12
    assert len(result.activity) == 1557 - 12
    kept_ids = set(result.activity["shift_id"])
    for m in manifest:
        if m["file"] == "shifts.csv" and m["rule"] in WARN_ONLY:
            assert m["key"] in kept_ids
        if m["file"] == "shifts.csv" and m["rule"] not in WARN_ONLY and m["rule"] != "exact_duplicate_row":
            assert m["key"] not in kept_ids


def test_duplicate_row_is_kept_once(result):
    assert (result.activity["shift_id"] == "S00246").sum() == 1


def test_inconsistent_region_spelling_is_normalised(result):
    assert sorted(result.by_region["region"]) == ["East Residential", "Metro Center", "North Transit",
                                                  "South Campus", "West District"]


def test_achieved_pph_mismatch_is_recomputed_from_counts(result):
    row = result.location_weekly.query("period == '2024-W02' and location_id == 'L19'").iloc[0]
    assert row["pledges"] == 54 and row["hours"] == 39.0
    assert row["achieved_pph"] == pytest.approx(54 / 39)  # 1.3846, not the planted 2.88


# ---- KPIs on the cleaned sample match an independent calculation ------------------------------------

def test_region_kpis_match_independent_csv_calculation(result, manifest):
    bad_keys = {m["key"] for m in manifest if m["file"] == "shifts.csv" and m["rule"] not in WARN_ONLY}
    seen, totals = set(), {}
    for r in read("shifts.csv"):
        if r["shift_id"] in bad_keys and r["shift_id"] != "S00246":
            continue
        if r["shift_id"] == "S00246":  # keep the first copy only
            if "S00246" in seen:
                continue
            seen.add("S00246")
        region = " ".join(r["region"].split()).title()
        t = totals.setdefault(region, dict(d=0, c=0, p=0, v=0, h=0.0))
        t["d"] += int(r["doors_knocked"]); t["c"] += int(r["conversations"]); t["p"] += int(r["pledges"])
        t["v"] += int(r["total_monthly_value_eur"]); t["h"] += float(r["active_hours"])
    got = result.by_region.set_index("region")
    assert set(got.index) == set(totals)
    for region, t in totals.items():
        assert got.loc[region, "pledges"] == t["p"]
        assert got.loc[region, "conversation_rate"] == pytest.approx(t["c"] / t["d"])
        assert got.loc[region, "pledge_rate"] == pytest.approx(t["p"] / t["c"])
        assert got.loc[region, "pledges_per_hour"] == pytest.approx(t["p"] / t["h"])
        assert got.loc[region, "avg_monthly_donation_eur"] == pytest.approx(t["v"] / t["p"])


def test_location_kpis_cover_all_30_locations_and_agree_between_sources(result):
    a, w = result.by_location.set_index("location_id"), result.by_location_weekly.set_index("location_id")
    assert len(a) == len(w) == 30
    assert not a["target_attainment"].isna().any()
    # The weekly file was rolled up from the error-free shifts, so it differs from the cleaned shifts only where
    # error rows were dropped (or kept) - a handful of rows out of ~50 per location. Measured max gap: 0.015.
    diff = (a["achieved_pph"] - w["achieved_pph"]).abs()
    assert diff.max() < 0.05


def test_every_location_gets_a_classification(result):
    assert set(result.by_location["planning_priority"]) <= {
        "Scale or repeat", "Keep and monitor", "Review before repeating", "Insufficient data"}
    assert result.by_location["planning_priority"].notna().all()
