import math

import pytest

from f2f_kpi import ConfigError, config_from_dict
from f2f_kpi.classify import classify_value
from f2f_kpi.config import ClassificationConfig, Tier

INPUTS = {"activity": "x.csv"}


def label(att, hours=100, ltype=None, cfg=None):
    return classify_value(att, hours, ltype, cfg or ClassificationConfig())[0]


def test_default_tiers_match_original_project_thresholds():
    assert label(1.20) == "Scale or repeat"
    assert label(0.80) == "Keep and monitor"
    assert label(0.50) == "Review before repeating"


@pytest.mark.parametrize("att,expected", [
    (1.0, "Scale or repeat"),            # boundary is inclusive
    (0.9999, "Keep and monitor"),
    (0.75, "Keep and monitor"),          # boundary is inclusive
    (0.7499, "Review before repeating"),
    (0.0, "Review before repeating"),
])
def test_tier_boundaries(att, expected):
    assert label(att) == expected


def test_float_noise_at_a_boundary_does_not_demote():
    att = 0.3 / 0.4  # 0.7499999999999999 in floating point
    assert att < 0.75
    assert label(att) == "Keep and monitor"


def test_too_few_hours_is_insufficient_data():
    cfg = ClassificationConfig(min_hours=20)
    assert classify_value(1.5, 19.5, None, cfg)[0] == "Insufficient data"
    assert classify_value(1.5, 20, None, cfg)[0] == "Scale or repeat"


def test_missing_target_is_insufficient_data():
    assert label(math.nan) == "Insufficient data"


def test_custom_tiers_and_labels_from_config():
    cfg = config_from_dict({"inputs": INPUTS, "classification": {
        "min_hours": 10,
        "tiers": [{"label": "Gold", "min": 1.2}, {"label": "Silver", "min": 0.9}, {"label": "Bronze", "min": 0}]}})
    assert label(1.2, cfg=cfg.classification) == "Gold"
    assert label(1.0, cfg=cfg.classification) == "Silver"
    assert label(0.1, cfg=cfg.classification) == "Bronze"


def test_tiers_are_sorted_even_if_given_out_of_order():
    cfg = config_from_dict({"inputs": INPUTS, "classification": {
        "tiers": [{"label": "Low", "min": 0}, {"label": "High", "min": 1.0}]}})
    assert label(1.5, cfg=cfg.classification) == "High"


def test_tiers_by_location_type():
    cfg = ClassificationConfig(tiers_by_type={"Fair": [Tier("Great", 1.5), Tier("Fine", 0.0)]})
    assert label(1.2, ltype="Fair", cfg=cfg) == "Fine"            # fairs have a stricter bar
    assert label(1.2, ltype="Stand", cfg=cfg) == "Scale or repeat"  # other types use the default tiers


def test_note_explains_the_label():
    _, note = classify_value(0.82, 140, None, ClassificationConfig())
    assert "82%" in note and "140" in note


def test_lowest_tier_must_catch_everything():
    with pytest.raises(ConfigError, match="lowest tier"):
        config_from_dict({"inputs": INPUTS, "classification": {"tiers": [{"label": "Only", "min": 0.5}]}})
