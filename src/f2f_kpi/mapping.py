"""Rename a team's column headers to the canonical field names."""
from __future__ import annotations

import pandas as pd

from .config import Config
from .io import ROW
from .issues import IssueLog
from .profile import suggest_mapping
from .schema import DATASETS


def apply_mapping(raw: pd.DataFrame, dataset: str, config: Config, log: IssueLog) -> pd.DataFrame:
    """Return a frame with canonical column names (+ ROW). Missing optional columns are simply absent;
    missing required columns are logged as 'missing_column' errors."""
    by_key = {str(c).strip().casefold(): c for c in raw.columns}
    shown = [c for c in raw.columns if c != ROW]
    likely = {s.field: s.column for s in suggest_mapping(shown, dataset)[0]}
    user_map = config.columns.get(dataset, {})
    out = pd.DataFrame({ROW: raw[ROW]})
    for f in DATASETS[dataset]:
        candidates = user_map.get(f.name, [f.name])
        source = next((by_key[c.strip().casefold()] for c in candidates if c.strip().casefold() in by_key), None)
        if source is None:
            if f.required:
                looked = ", ".join(candidates) if candidates else "nothing, it is switched off"
                message = (f"No column found for the required field '{f.name}' (looked for: {looked}). "
                           f"The file has: {', '.join(shown)}.")
                if f.name in likely:
                    message += (f" '{likely[f.name]}' looks like a match: name it under "
                                f"columns.{dataset}.{f.name} in your config.")
                log.add(dataset, "missing_column", message, column=f.name)
            continue
        out[f.name] = raw[source].astype(str).str.strip()
    for column, mapping in config.value_maps.get(dataset, {}).items():
        if column in out:
            out[column] = out[column].replace(mapping)
    return out
