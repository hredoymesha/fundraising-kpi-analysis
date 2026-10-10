"""Native Excel charts for the Trends sheet. They are real chart objects, so anyone can restyle them in Excel."""
from __future__ import annotations

from openpyxl.chart import BarChart, LineChart, Reference
from openpyxl.worksheet.worksheet import Worksheet

WIDTH_CM, HEIGHT_CM = 16, 8


def _finish(chart, title: str, y_title: str, y_format: str | None) -> None:
    chart.title = title
    chart.y_axis.title = y_title
    if y_format:
        chart.y_axis.number_format = y_format
    chart.x_axis.title = None
    chart.x_axis.delete = False  # openpyxl hides axes unless told otherwise
    chart.y_axis.delete = False
    chart.legend.position = "b"
    chart.width, chart.height = WIDTH_CM, HEIGHT_CM
    chart.display_blanks = "gap"


def _line(ws: Worksheet, cols: dict[str, int], keys: list[str], n_rows: int, title: str, y_title: str,
          y_format: str | None) -> LineChart | None:
    keys = [k for k in keys if k in cols]
    if not keys:
        return None
    chart = LineChart()
    for key in keys:
        chart.add_data(Reference(ws, min_col=cols[key], min_row=1, max_row=n_rows + 1), titles_from_data=True)
    chart.set_categories(Reference(ws, min_col=cols["period"], min_row=2, max_row=n_rows + 1))
    for s in chart.series:
        s.smooth = False
        s.marker.symbol = "circle"
    _finish(chart, title, y_title, y_format)
    return chart


def add_trend_charts(ws: Worksheet, cols: dict[str, int], n_rows: int, first_row: int) -> int:
    """Place the charts below the table, side by side. `cols` maps trend column keys to sheet column numbers.
    Returns how many charts were added."""
    charts = []
    if "pledges" in cols:
        bar = BarChart()
        bar.add_data(Reference(ws, min_col=cols["pledges"], min_row=1, max_row=n_rows + 1), titles_from_data=True)
        bar.set_categories(Reference(ws, min_col=cols["period"], min_row=2, max_row=n_rows + 1))
        _finish(bar, "Pledges per period", "Pledges", "#,##0")
        bar.legend = None
        charts.append(bar)
    charts += [c for c in [
        _line(ws, cols, ["pledges_per_hour", "pph_rolling_4"], n_rows, "Pledges per hour", "Pledges per hour", "0.0"),
        _line(ws, cols, ["conversation_rate", "pledge_rate"], n_rows, "Conversion rates", "Rate", "0%"),
    ] if c is not None]
    for i, chart in enumerate(charts):
        ws.add_chart(chart, f"{'A' if i == 0 else 'J' if i == 1 else 'S'}{first_row}")
    return len(charts)
