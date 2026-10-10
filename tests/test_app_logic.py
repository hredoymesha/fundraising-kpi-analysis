"""The web app's non-visual logic: mapping defaults, config building, KPI cards and display tables."""
import pandas as pd
import pytest

from f2f_kpi import ConfigError, analyse, config_from_dict
from f2f_kpi.io import read_bytes

import app_logic as logic

# Hand-calculated: A/L1 doors 100+300, conv 30+60, pledges 6+12, value 90+180, hours 4+8 ; B/L2 200, 40, 4, 80, 5.
# Totals: doors 600, conv 130, pledges 22, value 350, hours 17.  Targets: L1 = 1.0, L2 = 1.0 -> expected 12 + 5 = 17.
ACTIVITY = (b"date,region,location_id,doors_knocked,conversations,pledges,total_monthly_value_eur,active_hours\n"
            b"2024-01-08,A,L1,100,30,6,90,4\n2024-01-09,A,L1,300,60,12,180,8\n2024-01-15,B,L2,200,40,4,80,5\n")
LOCATIONS = b"location_id,location_label,location_type,target_pph\nL1,Alpha,Stand,1.0\nL2,Beta,Fair,1.0\n"


def result_for(activity=ACTIVITY, locations=LOCATIONS, config=None):
    config = config or logic.default_config()
    raw = {"activity": read_bytes(activity, "a.csv")}
    if locations:
        raw["locations"] = read_bytes(locations, "l.csv")
    return config, analyse(config, raw)


# ---- column mapping ---------------------------------------------------------------------------------

def test_initial_mapping_guesses_from_header_names():
    cols = ["Datum", "Gebiet", "Sign-ups", "Hours worked", "Doors", "Convos", "Monthly EUR", "Notes"]
    m = logic.initial_mapping(cols, "activity", logic.default_config())
    assert m["region"] == "Gebiet" and m["pledges"] == "Sign-ups" and m["active_hours"] == "Hours worked"
    assert m["date"] == "Datum" and m["doors_knocked"] == "Doors" and m["conversations"] == "Convos"
    assert m["location_id"] is None and "Notes" not in m.values()


def test_a_header_named_in_the_config_beats_the_guess():
    config = config_from_dict({"columns": {"activity": {"pledges": "Notes"}}}, require_activity=False)
    m = logic.initial_mapping(["Notes", "Sign-ups", "Region", "Hours"], "activity", config)
    assert m["pledges"] == "Notes"  # the config says so, even though 'Sign-ups' looks better
    assert list(m.values()).count("Notes") == 1  # and it is not offered a second time


def test_config_headers_match_ignoring_case_and_spaces():
    config = config_from_dict({"columns": {"activity": {"region": ["Area", "Zone"]}}}, require_activity=False)
    assert logic.initial_mapping([" zone ", "Pledges", "Hours"], "activity", config)["region"] == " zone "


def test_initial_mapping_never_uses_a_header_twice():
    m = logic.initial_mapping(["Hours", "Hours worked", "Region", "Pledges"], "activity", logic.default_config())
    assert logic.reused_headers(m) == []


def test_missing_and_reused_helpers():
    assert logic.missing_required({"region": "R", "pledges": None, "active_hours": ""}, "activity") == ["pledges", "active_hours"]
    assert logic.missing_required({"location_id": "L", "target_pph": "T"}, "locations") == []
    assert logic.reused_headers({"a": "X", "b": "X", "c": "Y", "d": None}) == ["X"]
    assert logic.is_required("activity", "pledges") and not logic.is_required("activity", "date")


def test_every_field_the_app_offers_has_a_label():
    from f2f_kpi.schema import DATASETS
    for dataset in ("activity", "locations"):
        assert {f.name for f in DATASETS[dataset]} == set(logic.FIELD_LABELS[dataset])


# ---- config -----------------------------------------------------------------------------------------

def test_build_config_writes_the_dropdown_choices_without_touching_the_original():
    base = logic.default_config()
    cfg = logic.build_config(base, {"activity": {"region": "Gebiet", "date": None}}, decimal=",", date_format="%d.%m.%Y")
    assert cfg.columns["activity"] == {"region": ["Gebiet"], "date": []}
    assert cfg.formats.decimal == "," and cfg.formats.date == "%d.%m.%Y"
    assert base.columns == {} and base.formats.decimal == "."


def test_a_field_left_unmapped_stays_unmapped_even_if_a_header_has_its_name():
    raw = {"activity": read_bytes(ACTIVITY, "a.csv")}
    cfg = logic.build_config(logic.default_config(), {"activity": {
        "region": "region", "pledges": "pledges", "active_hours": "active_hours", "date": None}})
    result = analyse(cfg, raw)
    assert "date" not in result.activity.columns and result.trends is None


def test_blank_date_format_means_iso_dates():
    cfg = logic.build_config(logic.default_config(), {}, date_format="   ")
    assert cfg.formats.date is None


def test_parse_config_text():
    cfg = logic.parse_config_text("classification:\n  min_hours: 5\nreport:\n  trend_period: month\n")
    assert cfg.classification.min_hours == 5 and cfg.report.trend_period == "month"
    assert logic.parse_config_text("").report.trend_period == "week"  # empty file = defaults


@pytest.mark.parametrize("text,fragment", [
    ("inputs: [unclosed", "not valid YAML"),
    ("- just\n- a list\n", "must be"),
    ("colums: {}", "unknown top-level"),
    ("validation:\n  severity:\n    made_up: error\n", "unknown rule"),
])
def test_bad_settings_files_raise_a_readable_config_error(text, fragment):
    with pytest.raises(ConfigError, match=fragment):
        logic.parse_config_text(text)


# ---- KPI cards --------------------------------------------------------------------------------------

def cards(result):
    return {c.label: c for c in logic.kpi_cards(result)}


def test_five_cards_with_hand_calculated_values():
    _, r = result_for()
    c = cards(r)
    assert list(c) == ["Conversation rate", "Pledge rate", "Pledges per hour", "Average monthly gift", "Target attainment"]
    assert c["Conversation rate"].value == "21.7%"  # 130 / 600
    assert c["Pledge rate"].value == "16.9%"  # 22 / 130
    assert c["Pledges per hour"].value == "1.29"  # 22 / 17
    assert c["Average monthly gift"].value == "€15.91"  # 350 / 22
    assert c["Target attainment"].value == "129%"  # 22 pledges / (1.0*12 + 1.0*5) expected = 1.294
    assert all(card.available for card in c.values())


def test_without_a_location_list_attainment_explains_what_is_missing():
    _, r = result_for(locations=None)
    card = cards(r)["Target attainment"]
    assert not card.available and card.value == "—" and "location list" in card.note
    assert cards(r)["Pledges per hour"].available


def test_cards_for_columns_that_are_not_there_say_which_are_needed():
    _, r = result_for(activity=b"region,pledges,active_hours\nA,5,2\n", locations=None)
    c = cards(r)
    assert c["Pledges per hour"].value == "2.50"
    assert not c["Conversation rate"].available and "doors knocked" in c["Conversation rate"].note
    assert not c["Average monthly gift"].available and "monthly value" in c["Average monthly gift"].note


def test_a_zero_denominator_shows_a_dash_not_zero_percent():
    _, r = result_for(activity=b"region,pledges,active_hours,doors_knocked,conversations\nA,0,3,0,0\n", locations=None)
    card = cards(r)["Conversation rate"]
    assert card.value == "—" and "nothing to divide by" in card.note
    assert cards(r)["Pledges per hour"].value == "0.00"  # 0 / 3 is a real zero


# ---- tables -----------------------------------------------------------------------------------------

def bad_data_result():
    csv = (b"region,pledges,active_hours,conversations,doors_knocked\n"
           b"A,5,2,10,50\n"            # row 2: fine
           b"a,5,2,10,50\n"            # row 3: region spelled differently -> warning
           b"A,5,2,60,50\n"            # row 4: more conversations than doors -> error
           b"A,x,2,10,50\n")           # row 5: text instead of a number -> error
    return result_for(activity=csv, locations=None)[1]


def test_issues_table_lists_errors_first_with_source_rows():
    t = logic.issues_table(bad_data_result().issues)
    assert list(t["Severity"]) == ["error", "error", "warning"]
    assert list(t["Row in file"]) == [4, 5, 3]
    assert list(t["Rule"]) == ["conversations_gt_doors", "non_numeric_value", "inconsistent_region_label"]
    assert set(t.columns) == {"Severity", "File", "Row in file", "Column", "Rule", "Value found", "What is wrong"}
    assert t.loc[1, "Value found"] == "x" and t.loc[0, "File"] == "Activity file"


def test_issues_table_severity_filter_and_empty_case():
    r = bad_data_result()
    assert list(logic.issues_table(r.issues, ["warning"])["Rule"]) == ["inconsistent_region_label"]
    assert logic.issues_table(r.issues, []).empty
    _, clean = result_for()
    assert logic.issues_table(clean.issues).empty


def test_location_ranking_is_best_first_with_percentages():
    _, r = result_for()
    t = logic.location_ranking(r)
    # L1: 18 pledges / 12 h = 1.5 vs target 1.0 -> 150% ; L2: 4 / 5 = 0.8 vs 1.0 -> 80%
    assert list(t["Location"]) == ["Alpha", "Beta"] and list(t["Rank"]) == [1, 2]
    assert list(t["Target attainment (%)"]) == pytest.approx([150.0, 80.0])
    assert t.loc[0, "Pledges"] == 18 and t.loc[1, "Achieved PPH"] == pytest.approx(0.8)


def test_location_tiers_follow_the_config():
    config = config_from_dict({"classification": {"min_hours": 1}}, require_activity=False)
    config, r = result_for(config=config)
    t = logic.location_ranking(r)
    assert list(t["Planning tier"]) == ["Scale or repeat", "Keep and monitor"]  # 150% and 80%
    assert "150%" in t.loc[0, "Why"]
    assert logic.tier_counts(r, config) == [("Scale or repeat", 1), ("Keep and monitor", 1)]


def test_default_min_hours_guard_shows_up_as_insufficient_data():
    config, r = result_for()  # 12 and 5 hours, default minimum is 20
    assert set(logic.location_ranking(r)["Planning tier"]) == {"Insufficient data"}
    assert logic.tier_counts(r, config) == [("Insufficient data", 2)]


def test_no_location_list_means_no_ranking():
    _, r = result_for(locations=None)
    assert logic.location_ranking(r) is None and logic.tier_counts(r, logic.default_config()) == []


def test_describe_filters():
    lo, hi = pd.Timestamp("2024-01-01"), pd.Timestamp("2024-03-31")
    assert logic.describe_filters(["A", "B"], ["A", "B"], lo, hi, lo, hi) == "everything"
    assert logic.describe_filters(["A"], ["A", "B"], lo, hi, lo, hi) == "1 of 2 regions"
    assert logic.describe_filters(["A", "B"], ["A", "B"], pd.Timestamp("2024-02-01"), hi, lo, hi) == "01 Feb 2024 to 31 Mar 2024"
    assert logic.describe_filters(["A"], ["A", "B"], pd.Timestamp("2024-02-01"), hi, lo, hi) == \
        "1 of 2 regions, 01 Feb 2024 to 31 Mar 2024"


# ---- text from the user's files must not turn into Markdown --------------------------------------------

BACKSLASH = chr(92)


def unescaped(text: str, characters: str) -> list[int]:
    return [i for i, c in enumerate(text) if c in characters and (i == 0 or text[i - 1] != BACKSLASH)]


@pytest.mark.parametrize("hostile", [
    "![x](https://evil.example/p.png)",   # an image the browser would fetch
    "[click here](https://evil.example)",  # a link
    ":red[loud]",                          # Streamlit colour syntax
    "<img src=x onerror=1>",
])
def test_markdown_safe_defuses_images_links_and_styles(hostile):
    out = logic.markdown_safe(hostile)
    assert unescaped(out, "![]()<>:") == []
    assert out.replace(BACKSLASH, "") == hostile  # shown to the reader exactly as it was typed


def test_markdown_safe_leaves_ordinary_text_alone_and_keeps_one_line():
    assert logic.markdown_safe("Sign ups 2024") == "Sign ups 2024"
    assert logic.markdown_safe("two\nlines  and   gaps") == "two lines and gaps"
    assert logic.markdown_safe(ValueError("bad value")) == "bad value"
