"""F2F KPI web app. Run from the repository root with:  streamlit run app/streamlit_app.py

The page only collects choices and draws results. Reading, validating, calculating and the Excel report all
come from the f2f_kpi package, the same code the command line uses.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

import pandas as pd
import streamlit as st

import app_logic as logic
import figures
from f2f_kpi import ConfigError, analyse, filter_options, report_bytes, with_filters
from f2f_kpi.io import FileReadError, excel_sheet_names, read_bytes

SAMPLE_DIR = Path(__file__).resolve().parents[1] / "data" / "sample"
XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
REPORT_NAME = "f2f_kpi_report.xlsx"


# ---- inputs -----------------------------------------------------------------------------------------

def sample_inputs() -> dict[str, tuple[str, bytes]] | None:
    files = {"activity": SAMPLE_DIR / "shifts.csv", "locations": SAMPLE_DIR / "locations.csv"}
    if not all(p.exists() for p in files.values()):
        return None
    return {name: (p.name, p.read_bytes()) for name, p in files.items()}


def collect_inputs() -> dict[str, tuple[str, bytes]]:
    """Name -> (filename, bytes) for the activity file and, optionally, the location list."""
    st.sidebar.header("1. Your files")
    activity = st.sidebar.file_uploader("Activity file", type=logic.UPLOAD_TYPES, key="up_activity",
                                        help="One row per shift or day: region, pledges, hours, and so on. CSV or Excel.")
    locations = st.sidebar.file_uploader("Location list (optional)", type=logic.UPLOAD_TYPES, key="up_locations",
                                         help="One row per location with its target pledges per hour. "
                                              "Needed for target attainment and the location ranking.")
    if activity is not None:
        st.session_state["use_sample"] = False
        found = {"activity": (activity.name, activity.getvalue())}
        if locations is not None:
            found["locations"] = (locations.name, locations.getvalue())
        return found

    sample = sample_inputs()
    if sample and st.session_state.get("use_sample"):
        st.sidebar.info("Showing the built-in sample data (made up, no real people).")
        if st.sidebar.button("Stop using the sample"):
            st.session_state["use_sample"] = False
            st.rerun()
        return sample
    if sample and st.sidebar.button("Try it with sample data"):
        st.session_state["use_sample"] = True
        st.rerun()
    return {}


def reading_options(dataset: str, filename: str, data: bytes) -> dict:
    """Sheet, header row, separator and encoding for one file. The defaults suit most exports."""
    suffix = Path(filename).suffix.lower()
    opts: dict = {"sheet": None, "header_row": 1, "delimiter": None, "encoding": "utf-8-sig"}
    with st.sidebar.expander(f"Reading options: {logic.DATASET_NAMES[dataset].lower()}"):
        if suffix in (".xlsx", ".xlsm"):
            sheets = excel_sheet_names(data, filename)  # raises FileReadError for a damaged workbook
            opts["sheet"] = st.selectbox("Sheet", sheets, key=f"sheet_{dataset}")
        else:
            opts["delimiter"] = logic.DELIMITERS[st.selectbox("Separator", list(logic.DELIMITERS), key=f"delim_{dataset}")]
            opts["encoding"] = logic.ENCODINGS[st.selectbox("Text encoding", list(logic.ENCODINGS), key=f"enc_{dataset}",
                                                           help="Try another one if accents look wrong or the file won't open.")]
        opts["header_row"] = int(st.number_input("Row with the column names", min_value=1, value=1, step=1,
                                                 key=f"hdr_{dataset}"))
    return opts


def base_config():
    """Defaults, or the settings file the user supplied."""
    with st.sidebar.expander("Settings file (optional)"):
        st.caption("A YAML config like the one the command line uses. Its column mapping, thresholds and tiers apply "
                   "here; file paths inside it are ignored.")
        uploaded = st.file_uploader("YAML settings", type=["yaml", "yml"], key="up_config", label_visibility="collapsed")
    if uploaded is None:
        return logic.default_config(), "default"
    text = uploaded.getvalue().decode("utf-8", errors="replace")
    try:
        return logic.parse_config_text(text), hashlib.sha1(text.encode()).hexdigest()[:8]
    except ConfigError as exc:
        st.sidebar.error(f"Could not use that settings file: {logic.markdown_safe(exc)}. Using the defaults instead.")
        return logic.default_config(), "default"


def format_options(config, tag: str) -> tuple[str, str]:
    with st.sidebar.expander("Number and date format"):
        point = config.formats.decimal == "."
        choice = st.radio("Decimal mark", ["Point (4.5)", "Comma (4,5)"], index=0 if point else 1, key=f"dec_{tag}")
        date_format = st.text_input("Date format", value=config.formats.date or "", placeholder="%d.%m.%Y", key=f"datefmt_{tag}",
                                    help="Leave blank for dates like 2024-03-31. Use a pattern such as %d.%m.%Y otherwise.")
    return ("." if choice.startswith("Point") else ","), date_format


# ---- mapping ----------------------------------------------------------------------------------------

def mapping_widgets(dataset: str, columns: list[str], config, tag: str) -> dict[str, str | None]:
    """One dropdown per field. Returns {field: header or None}."""
    start = logic.initial_mapping(columns, dataset, config)
    options = [logic.NOT_MAPPED] + columns
    mapping: dict[str, str | None] = {}
    grid = st.columns(3)
    fields = list(logic.FIELD_LABELS[dataset])
    for i, field in enumerate(fields):
        label = logic.label_for(dataset, field) + (" (required)" if logic.is_required(dataset, field) else "")
        default = options.index(start[field]) if start.get(field) in options else 0
        choice = grid[i % 3].selectbox(label, options, index=default, key=f"map_{dataset}_{field}_{tag}")
        mapping[field] = None if choice == logic.NOT_MAPPED else choice
    return mapping


# ---- results ----------------------------------------------------------------------------------------

def show_cards(view) -> None:
    cards = logic.kpi_cards(view)
    for col, card in zip(st.columns(len(cards)), cards):
        col.metric(card.label, card.value, help=card.note)
    missing = [f"**{c.label}**: {c.note}" for c in cards if not c.available]
    if missing:
        st.caption("Not shown: " + " · ".join(missing))


def show_figure(fig, fallback: str) -> None:
    if fig is None:
        st.info(fallback)
    else:
        st.plotly_chart(fig, width="stretch")


def show_overview(view, config) -> None:
    show_cards(view)
    st.write("")
    left, right = st.columns(2)
    with left:
        show_figure(figures.pph_by_region(view.by_region), "Pledges per hour needs the pledges, active hours and region columns.")
    with right:
        show_figure(figures.rates_by_region(view.by_region),
                    "Conversion rates need the doors knocked and conversations columns.")
    period = config.report.trend_period
    left, right = st.columns(2)
    no_dates = "Trends need a date column. Map one above if your file has dates."
    with left:
        show_figure(figures.trend_pph(view.trends, period), no_dates)
    with right:
        show_figure(figures.trend_pledges(view.trends, period), no_dates)


def show_locations(view, config) -> None:
    ranking = logic.location_ranking(view)
    if ranking is None:
        st.info("The ranking needs a location list with a target pledges-per-hour for each location, plus a location ID "
                "column in the activity file. Add the list in the sidebar.")
        return
    cols = st.columns(max(len(logic.tier_counts(view, config)), 1))
    for col, (label, count) in zip(cols, logic.tier_counts(view, config)):
        col.metric(label, count)
    st.dataframe(ranking, hide_index=True, width="stretch", column_config={
        "Target attainment (%)": st.column_config.NumberColumn(format="%.0f%%"),
        "Hours": st.column_config.NumberColumn(format="%.1f"),
        "Target PPH": st.column_config.NumberColumn(format="%.2f"),
        "Achieved PPH": st.column_config.NumberColumn(format="%.2f"),
        "Pledges": st.column_config.NumberColumn(format="%d"),
        "Why": st.column_config.TextColumn(width="large"),
    })
    tiers = ", ".join(f"{t.label}: {t.min:.0%} or more" for t in config.classification.tiers)
    st.caption(f"Tiers (share of target): {tiers}. Locations with under {config.classification.min_hours:g} hours "
               f"are labelled '{config.classification.insufficient_label}'.")


def show_issues(result) -> None:
    issues = result.issues
    if issues.empty:
        st.success("No problems found in your data.")
        return
    errors = int((issues["severity"] == "error").sum())
    warnings = int((issues["severity"] == "warning").sum())
    a, b = st.columns(2)
    a.metric("Errors", errors, help="These rows are left out of every figure.")
    b.metric("Warnings", warnings, help="These rows are kept, but worth a look (or they were tidied up).")
    chosen = st.multiselect("Show", ["error", "warning"], default=["error", "warning"], key="sev_filter")
    st.dataframe(logic.issues_table(issues, chosen), hide_index=True, width="stretch", column_config={
        "Row in file": st.column_config.NumberColumn(help="The line in your file, counting the column names as the first."),
        "What is wrong": st.column_config.TextColumn(width="large"),
    })
    st.caption("Fix these in the original file and upload it again. The values shown are copied from your file.")


# ---- page -------------------------------------------------------------------------------------------

def welcome() -> None:
    st.title("F2F fundraising KPIs")
    st.write("Upload an export from your team and get conversion rates, pledges per hour and a location ranking, "
             "with every data problem listed so you can fix it at the source.")
    st.markdown("1. **Upload** an activity file in the sidebar (CSV or Excel).\n"
                "2. **Match the columns**: the app guesses, you confirm.\n"
                "3. **Look around**, filter by region and date, then **download the Excel report**.")
    st.info("No file handy? Use *Try it with sample data* in the sidebar. It is made up and contains no real people.")
    with st.expander("What the activity file needs"):
        st.write("At least a **region**, a **pledge count** and the **active hours** for each row. Doors knocked, "
                 "conversations, dates and monthly values give you more of the figures.")


def privacy_note() -> None:
    with st.expander("How your data is handled"):
        st.write("Your file is kept in memory while this page is open. The app doesn't save it, send it to any other "
                 "service, or write its contents to logs, and it is forgotten when you close or refresh the page.")
        st.write("One small exception: while it builds the Excel report, the spreadsheet library creates short-lived "
                 "temporary files in this computer's temp folder and deletes them straight away.")
        st.write("If someone else hosts this app, your file does reach their server. For sensitive exports, run the "
                 "app on your own computer.")


def run_app() -> None:
    inputs = collect_inputs()
    if "activity" not in inputs:
        welcome()
        return

    st.title("F2F fundraising KPIs")
    privacy_note()
    config0, config_tag = base_config()
    decimal, date_format = format_options(config0, config_tag)

    # read
    raw, digests = {}, []
    for dataset, (filename, data) in inputs.items():
        try:
            opts = reading_options(dataset, filename, data)
            digests.append(hashlib.sha1(data).hexdigest()[:8] + str(sorted(opts.items(), key=str)))
            with st.spinner(f"Reading {logic.markdown_safe(filename)}…"):
                raw[dataset] = read_bytes(data, filename, decimal=decimal, **opts)
        except FileReadError as exc:
            st.error(f"**{logic.DATASET_NAMES[dataset]}:** {logic.markdown_safe(exc)}")
            if dataset == "activity":
                return
            st.warning("Carrying on without the location list.")
    if raw["activity"].empty:
        st.error(f"'{logic.markdown_safe(inputs['activity'][0])}' has column names but no data rows. Check that the right sheet and header row "
                 "are selected in the sidebar.")
        return
    tag = hashlib.sha1("|".join(digests + [config_tag]).encode()).hexdigest()[:10]

    # map
    st.subheader("Match your columns")
    st.caption("We guessed from the column names. Change any dropdown that is wrong; fields marked required must be set.")
    mappings, ready = {}, True
    for dataset, table in raw.items():
        columns = [c for c in table.columns if c != "_row"]
        with st.expander(f"{logic.DATASET_NAMES[dataset]}: {logic.markdown_safe(inputs[dataset][0])}", expanded=(dataset == "activity")):
            mapping = mapping_widgets(dataset, columns, config0, tag)
            missing = logic.missing_required(mapping, dataset)
            reused = logic.reused_headers(mapping)
            if missing:
                names = ", ".join(logic.label_for(dataset, f) for f in missing)
                st.warning(f"Still needed: **{names}**. Pick the column that holds it.")
            if reused:
                st.warning("Each column can fill only one field. Used twice: " + ", ".join(f"'{logic.markdown_safe(h)}'" for h in reused) + ".")
            if missing or reused:
                if dataset == "activity":
                    ready = False
                else:
                    st.caption("The location list is left out until this is fixed.")
                    continue
            mappings[dataset] = mapping
    if not ready:
        st.stop()

    config = logic.build_config(config0, mappings, decimal=decimal, date_format=date_format)

    # analyse (kept in this browser session only)
    cached = st.session_state.get("analysis")
    key = (tag, repr(sorted((d, sorted(m.items(), key=str)) for d, m in mappings.items())), decimal, date_format)
    if cached is None or cached["key"] != key:
        with st.spinner("Checking your data and working out the figures…"):
            result = analyse(config, {d: raw[d] for d in mappings})
            report = report_bytes(result, config) if not result.activity.empty else None
        cached = {"key": key, "result": result, "report": report}
        st.session_state["analysis"] = cached
    result, report = cached["result"], cached["report"]

    read, used = result.rows_read.get("activity", 0), len(result.activity)
    if used == 0:
        st.error(f"None of the {read} rows could be used, so there is nothing to show yet. The problems are listed below.")
        show_issues(result)
        return
    st.success(f"Read {read} rows from your activity file and used {used}." +
               (f" {read - used} left out because of errors (see Data issues)." if used < read else ""))

    # filter
    st.sidebar.header("2. Filters")
    options = filter_options(result)
    regions = st.sidebar.multiselect("Regions", options["regions"], default=options["regions"], key=f"regions_{tag}")
    lo = options["date_min"].date() if options["date_min"] is not None else None
    hi = options["date_max"].date() if options["date_max"] is not None else None
    start = end = None
    if lo is not None:
        picked = st.sidebar.date_input("Dates", value=(lo, hi), min_value=lo, max_value=hi, key=f"dates_{tag}")
        if isinstance(picked, (tuple, list)) and len(picked) == 2:
            start, end = picked
        else:
            st.sidebar.caption("Pick an end date to apply the date filter.")
    # an untouched filter should not drop rows that have no date, so only pass dates on when they narrow the range
    narrowed = start is not None and (start != lo or end != hi)
    all_regions = set(regions) == set(options["regions"])
    view = with_filters(result, config, regions=None if all_regions else regions,
                        start=start if narrowed else None, end=end if narrowed else None)

    st.sidebar.header("3. Report")
    if report:
        st.sidebar.download_button("Download Excel report", data=report, file_name=REPORT_NAME, mime=XLSX_MIME,
                                   help="Seven sheets: summary, breakdowns, locations, trends, data issues and methods.")
        st.sidebar.caption("The report covers every usable row in your file, whatever the filters are set to.")

    if view.activity.empty:
        st.warning("No rows match these filters. Widen the date range or pick more regions.")
        tabs = st.tabs(["Data issues"])
        with tabs[0]:
            show_issues(result)
        return
    shown = logic.describe_filters(regions, options["regions"], start, end, lo, hi)
    st.caption(f"Showing {len(view.activity):,} shifts. Filters: {shown}.")

    overview, locations, issues = st.tabs(["Overview", "Locations", f"Data issues ({len(result.issues)})"])
    with overview:
        show_overview(view, config)
    with locations:
        show_locations(view, config)
    with issues:
        show_issues(result)


def network_warning() -> None:
    """Streamlit only reads .streamlit/config.toml from the folder it was started in. Started anywhere else, it
    listens on every network interface, so say so instead of letting that pass unnoticed."""
    if st.get_option("server.address") in ("localhost", "127.0.0.1", "::1"):
        return
    st.warning("Other computers on your network can reach this app. If you only want to use it yourself, restart it "
               "with `streamlit run app/streamlit_app.py --server.address localhost`. If it is meant to be shared, "
               "ignore this.")


def main() -> None:
    st.set_page_config(page_title="F2F KPI toolkit", layout="wide")
    try:
        network_warning()
        run_app()
    except st.errors.StreamlitAPIException:
        raise
    except Exception as exc:  # never echo the message: it can contain a value from the user's file
        st.error(f"Something unexpected went wrong ({type(exc).__name__}). Your data was not saved or sent anywhere. "
                 "Try another file or different reading options, and report the problem if it keeps happening.")


main()
