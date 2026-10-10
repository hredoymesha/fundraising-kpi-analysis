"""Command line for the toolkit.

  f2f-kpi report data.csv --config config/default_mapping.yaml     one file in, Excel report out
  f2f-kpi run --config team.yaml                                    same, with every input named in the config
  f2f-kpi validate --config team.yaml                               list data problems, write nothing
  f2f-kpi profile data.csv                                          suggest which column is which
  f2f-kpi init-config [data.csv] -o team.yaml                       start a config file

Exit codes: 0 fine; 1 validate found errors, or report/run had nothing usable left, or --strict met an issue;
2 the config or a file could not be used.
"""
from __future__ import annotations

import argparse
import re
import sys
from importlib import resources
from pathlib import Path

from . import __version__
from .config import Config, ConfigError, InputSpec, config_from_dict, load_config
from .engine import Result, run
from .io import read_table
from .profile import columns_yaml, describe, suggest_mapping
from .report import write_report
from .schema import DATASETS

DEFAULT_OUTPUT = Path("f2f_kpi_report.xlsx")
# lines in the packaged template that init-config swaps out when it is given a data file
TEMPLATE_INPUT_LINE = "  activity: data/activity.csv        # one row per shift or day: pledges, hours, and so on (.csv or .xlsx)"
# the placeholder `columns: {}` plus the commented-out example that follows it
TEMPLATE_COLUMNS_BLOCK = re.compile(r"^columns: \{\}\n(?:  #.*\n)*", re.MULTILINE)


def _template() -> str:
    return resources.files("f2f_kpi").joinpath("templates/config.example.yaml").read_text(encoding="utf-8")


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="f2f-kpi", description="KPI toolkit for face-to-face fundraising data.")
    p.add_argument("--version", action="version", version=f"f2f-kpi {__version__}")
    sub = p.add_subparsers(dest="command", required=True)

    def add_common(sp: argparse.ArgumentParser, config_required: bool) -> None:
        sp.add_argument("--config", "-c", type=Path, required=config_required,
                        help="YAML config file" + ("" if config_required else " (optional; built-in defaults otherwise)"))
        sp.add_argument("--strict", action="store_true",
                         help="count warnings as failures too (exit code 1)")

    rep = sub.add_parser("report", help="build the Excel report from one activity file")
    rep.add_argument("input", type=Path, help="activity export (.csv or .xlsx), one row per shift or day")
    add_common(rep, config_required=False)
    rep.add_argument("--locations", type=Path, help="location list with target PPH, to fill the Locations sheet")
    rep.add_argument("--output", "-o", type=Path, default=DEFAULT_OUTPUT, help=f"report path (default: {DEFAULT_OUTPUT})")

    run_p = sub.add_parser("run", help="build the Excel report using the files named in the config")
    add_common(run_p, config_required=True)
    run_p.add_argument("--output", "-o", type=Path, default=DEFAULT_OUTPUT, help=f"report path (default: {DEFAULT_OUTPUT})")

    val = sub.add_parser("validate", help="check the data and list every problem; writes no report")
    add_common(val, config_required=True)

    prof = sub.add_parser("profile", help="read a file and suggest which column is which")
    prof.add_argument("input", type=Path, help="the export to look at (.csv or .xlsx)")
    prof.add_argument("--dataset", choices=sorted(DATASETS), default="activity", help="what kind of file this is")
    prof.add_argument("--sheet", help="Excel sheet name (default: first sheet)")
    prof.add_argument("--header-row", type=int, default=1, help="line the column names are on (default 1)")
    prof.add_argument("--delimiter", help="CSV separator (default: detected)")

    init = sub.add_parser("init-config", help="write a starter config file")
    init.add_argument("input", type=Path, nargs="?", help="optional export; its columns are matched for you")
    init.add_argument("--output", "-o", type=Path, default=Path("f2f_config.yaml"), help="where to write it")
    init.add_argument("--force", action="store_true", help="overwrite the file if it already exists")
    return p


def _counts(result: Result) -> tuple[int, int]:
    sev = result.issues["severity"]
    return int((sev == "error").sum()), int((sev == "warning").sum())


def _print_issues(result: Result) -> None:
    for i in result.issues.itertuples():
        where = f"{i.dataset} row {int(i.row)}" if i.row == i.row and i.row is not None else i.dataset
        col = f" [{i.column}]" if i.column else ""
        print(f"  {i.severity.upper():7} {where}{col}: {i.rule} - {i.message}")


def _summary(result: Result) -> None:
    for name, read in result.rows_read.items():
        print(f"  {name}: {read} rows read, {result.rows_kept.get(name, 0)} used")
    errors, warnings = _counts(result)
    print(f"  issues: {errors} error(s), rows left out; {warnings} warning(s), rows kept")


def _config_for_report(args: argparse.Namespace) -> Config:
    """Config from --config (or defaults), with the activity file taken from the command line."""
    config = (load_config(args.config, require_activity=False) if args.config
              else config_from_dict({}, require_activity=False))
    base = config.inputs.get("activity")
    config.inputs["activity"] = InputSpec(
        path=args.input, sheet=base.sheet if base else None, header_row=base.header_row if base else 1,
        delimiter=base.delimiter if base else None, encoding=base.encoding if base else "utf-8-sig")
    if args.locations:
        config.inputs["locations"] = InputSpec(path=args.locations)
    return config


def _build(config: Config, args: argparse.Namespace) -> int:
    result = run(config)
    errors, warnings = _counts(result)
    out = write_report(result, config, args.output)
    print(f"Report written to {out}")
    _summary(result)
    if result.activity.empty:
        reason = result.issues["message"].iloc[0] if len(result.issues) else "the file has no data rows"
        print(f"Nothing could be used, so the report has no figures. First problem: {reason}", file=sys.stderr)
        return 1
    if args.strict and (errors or warnings):
        print("Strict mode: the data has issues. The 'Data Issues' sheet lists them.", file=sys.stderr)
        return 1
    return 0


def _validate(config: Config, args: argparse.Namespace) -> int:
    result = run(config)
    errors, warnings = _counts(result)
    _summary(result)
    if len(result.issues):
        print("Issues:")
        _print_issues(result)
    else:
        print("No issues found.")
    return 1 if (errors or (args.strict and warnings)) else 0


def _profile(args: argparse.Namespace) -> int:
    spec = InputSpec(path=args.input, sheet=args.sheet, header_row=args.header_row, delimiter=args.delimiter)
    table = read_table(spec).drop(columns=["_row"])
    columns = list(table.columns)
    print(describe(columns, table.head(5).to_dict("records"), args.dataset))
    return 1 if suggest_mapping(columns, args.dataset)[1] else 0


def _init_config(args: argparse.Namespace) -> int:
    if args.output.exists() and not args.force:
        print(f"error: {args.output} already exists (use --force to replace it)", file=sys.stderr)
        return 2
    text = _template()
    if args.input:
        table = read_table(InputSpec(path=args.input))
        suggestions, missing, _ = suggest_mapping([c for c in table.columns if c != "_row"])
        if TEMPLATE_INPUT_LINE not in text or not TEMPLATE_COLUMNS_BLOCK.search(text):
            raise RuntimeError("the packaged config template changed shape; init-config needs updating")
        # the path is written relative to the new config, since that is how the loader reads it
        rel = Path(args.input).resolve()
        try:
            rel = rel.relative_to(args.output.resolve().parent)
        except ValueError:
            pass
        text = text.replace(TEMPLATE_INPUT_LINE, f"  activity: {rel.as_posix()}")
        text = TEMPLATE_COLUMNS_BLOCK.sub(lambda _: columns_yaml(suggestions) + "\n", text, count=1)
        if missing:
            print("Could not match: " + ", ".join(missing) + ". Add them under `columns:` by hand.")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(text, encoding="utf-8", newline="\n")
    print(f"Config written to {args.output}")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "profile":
            return _profile(args)
        if args.command == "init-config":
            return _init_config(args)
        if args.command == "report":
            return _build(_config_for_report(args), args)
        config = load_config(args.config)
        return _build(config, args) if args.command == "run" else _validate(config, args)
    except (ConfigError, FileNotFoundError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except OSError as exc:  # unwritable output, locked file, directory in the way, ...
        hint = " - is it open in Excel?" if isinstance(exc, PermissionError) else ""
        print(f"error: cannot use {exc.filename or 'the output path'}: {exc.strerror or exc}{hint}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
