"""YAML configuration: where the files are, how their columns map, validation limits, classification tiers."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .issues import RULES, ERROR, WARNING, IGNORE
from .schema import DATASETS


class ConfigError(ValueError):
    """The configuration file is wrong (as opposed to the data being wrong)."""


@dataclass
class InputSpec:
    path: Path
    sheet: str | int | None = None  # Excel only; default first sheet
    header_row: int = 1  # 1-based line holding the column headers
    delimiter: str | None = None  # CSV only; None = detect
    encoding: str = "utf-8-sig"


@dataclass
class Formats:
    date: str | None = None  # strptime pattern; None = ISO / pandas inference
    decimal: str = "."  # "," for 1.234,56 style numbers


@dataclass
class ValidationConfig:
    max_hours_per_row: float = 14.0
    max_value_per_pledge: float = 100.0
    expected_date_range: tuple[str, str] | None = None
    date_window_days: int = 180  # without expected_date_range: allowed distance from the median date
    achieved_pph_tolerance: float = 0.01
    severity: dict[str, str] = field(default_factory=dict)  # rule id -> error | warning | ignore


@dataclass
class Tier:
    label: str
    min: float  # inclusive lower bound on the metric


DEFAULT_TIERS = [Tier("Scale or repeat", 1.0), Tier("Keep and monitor", 0.75), Tier("Review before repeating", 0.0)]


@dataclass
class ClassificationConfig:
    tiers: list[Tier] = field(default_factory=lambda: list(DEFAULT_TIERS))
    tiers_by_type: dict[str, list[Tier]] = field(default_factory=dict)  # location_type -> own tiers
    min_hours: float = 20.0  # fewer total hours than this -> insufficient_label
    insufficient_label: str = "Insufficient data"


@dataclass
class ReportConfig:
    dimensions: list[str] | None = None  # columns to break the KPIs down by; None = activity_type and fundraiser_id, where present
    trend_period: str = "week"  # "week" or "month"


BREAKDOWN_FIELDS = ["activity_type", "fundraiser_id", "location_id"]  # columns that make sense as a breakdown


@dataclass
class Config:
    inputs: dict[str, InputSpec]
    columns: dict[str, dict[str, list[str]]] = field(default_factory=dict)  # dataset -> canonical -> accepted headers
    formats: Formats = field(default_factory=Formats)
    value_maps: dict[str, dict[str, dict[str, str]]] = field(default_factory=dict)  # dataset -> column -> {from: to}
    validation: ValidationConfig = field(default_factory=ValidationConfig)
    classification: ClassificationConfig = field(default_factory=ClassificationConfig)
    report: ReportConfig = field(default_factory=ReportConfig)


def _tiers(raw: Any, where: str) -> list[Tier]:
    if not isinstance(raw, list) or not raw:
        raise ConfigError(f"{where}: expected a non-empty list of {{label, min}}")
    try:
        tiers = [Tier(str(t["label"]), float(t["min"])) for t in raw]
    except (KeyError, TypeError, ValueError) as exc:
        raise ConfigError(f"{where}: every tier needs a 'label' and a numeric 'min'") from exc
    tiers.sort(key=lambda t: t.min, reverse=True)
    if tiers[-1].min > 0:
        raise ConfigError(f"{where}: the lowest tier must have min <= 0 so every location gets a label")
    return tiers


def config_from_dict(raw: dict[str, Any], base_dir: Path | str = ".", *, require_activity: bool = True) -> Config:
    base = Path(base_dir)
    known = {"inputs", "columns", "formats", "value_maps", "validation", "classification", "report"}
    if unknown := set(raw) - known:
        raise ConfigError(f"unknown top-level key(s): {sorted(unknown)}")

    inputs: dict[str, InputSpec] = {}
    for name, spec in (raw.get("inputs") or {}).items():
        if name not in DATASETS:
            raise ConfigError(f"inputs: unknown dataset '{name}' (expected one of {sorted(DATASETS)})")
        if isinstance(spec, str):
            spec = {"path": spec}
        if "path" not in spec:
            raise ConfigError(f"inputs.{name}: 'path' is required")
        p = Path(spec["path"])
        inputs[name] = InputSpec(
            path=p if p.is_absolute() else base / p,
            sheet=spec.get("sheet"),
            header_row=int(spec.get("header_row", 1)),
            delimiter=spec.get("delimiter"),
            encoding=spec.get("encoding", "utf-8-sig"),
        )
    if require_activity and "activity" not in inputs:
        raise ConfigError("inputs.activity is required")

    columns: dict[str, dict[str, list[str]]] = {}
    for ds, mapping in (raw.get("columns") or {}).items():
        if ds not in DATASETS:
            raise ConfigError(f"columns: unknown dataset '{ds}'")
        valid = {f.name for f in DATASETS[ds]}
        columns[ds] = {}
        for canon, headers in (mapping or {}).items():
            if canon not in valid:
                raise ConfigError(f"columns.{ds}: '{canon}' is not a known field (known: {sorted(valid)})")
            columns[ds][canon] = [headers] if isinstance(headers, str) else [str(h) for h in headers]

    fmt = raw.get("formats") or {}
    formats = Formats(date=fmt.get("date"), decimal=fmt.get("decimal", "."))
    if formats.decimal not in (".", ","):
        raise ConfigError("formats.decimal must be '.' or ','")

    v = raw.get("validation") or {}
    severity = v.get("severity") or {}
    for rule, level in severity.items():
        if rule not in RULES:
            raise ConfigError(f"validation.severity: unknown rule '{rule}' (known: {sorted(RULES)})")
        if level not in (ERROR, WARNING, IGNORE):
            raise ConfigError(f"validation.severity.{rule}: must be error, warning or ignore")
    rng = v.get("expected_date_range")
    if rng is not None and len(rng) != 2:
        raise ConfigError("validation.expected_date_range must be [start, end]")
    validation = ValidationConfig(
        max_hours_per_row=float(v.get("max_hours_per_row", 14.0)),
        max_value_per_pledge=float(v.get("max_value_per_pledge", 100.0)),
        expected_date_range=(str(rng[0]), str(rng[1])) if rng else None,
        date_window_days=int(v.get("date_window_days", 180)),
        achieved_pph_tolerance=float(v.get("achieved_pph_tolerance", 0.01)),
        severity=dict(severity),
    )

    c = raw.get("classification") or {}
    classification = ClassificationConfig(
        tiers=_tiers(c["tiers"], "classification.tiers") if "tiers" in c else list(DEFAULT_TIERS),
        tiers_by_type={k: _tiers(t, f"classification.tiers_by_type.{k}") for k, t in (c.get("tiers_by_type") or {}).items()},
        min_hours=float(c.get("min_hours", 20.0)),
        insufficient_label=str(c.get("insufficient_label", "Insufficient data")),
    )
    r = raw.get("report") or {}
    dims = r.get("dimensions")
    if dims is not None:
        dims = [dims] if isinstance(dims, str) else list(dims)
        bad = [d for d in dims if d not in BREAKDOWN_FIELDS]
        if bad:
            raise ConfigError(f"report.dimensions: {bad} cannot be used; choose from {BREAKDOWN_FIELDS}")
    period = r.get("trend_period", "week")
    if period not in ("week", "month"):
        raise ConfigError("report.trend_period must be 'week' or 'month'")
    return Config(inputs, columns, formats, raw.get("value_maps") or {}, validation, classification,
                  ReportConfig(dims, period))


def load_config(path: Path | str, *, require_activity: bool = True) -> Config:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"config file not found: {path}")
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise ConfigError(f"{path}: not valid YAML: {exc}") from exc
    if not isinstance(raw, dict):
        raise ConfigError(f"{path}: top level must be a mapping")
    return config_from_dict(raw, path.parent, require_activity=require_activity)
