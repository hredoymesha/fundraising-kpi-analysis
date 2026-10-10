"""Plotly figures for the web app. They only draw tables the engine has already calculated."""
from __future__ import annotations

import html

import pandas as pd
import plotly.graph_objects as go

BLUE, ORANGE, GREEN = "#2f6db5", "#e08a1e", "#3a9d5d"
LAYOUT = dict(margin=dict(l=10, r=10, t=50, b=10), height=340, legend=dict(orientation="h", y=-0.2),
              font=dict(size=13))
TITLE_SIZE = 16
PERIOD_DAYS = {"week": 7, "month": 30}
FEW_PERIODS = 4  # up to this many periods, label every one instead of letting Plotly choose the ticks


def _title(text: str) -> dict:
    return dict(text=text, font=dict(size=TITLE_SIZE))


def _plain(labels: pd.Series) -> list[str]:
    """Plotly reads a few HTML tags in labels (<b>, <a href=...>), so a region named '<a href=...>' from an uploaded
    file would become a clickable link. Escaping makes it show up as the text it is."""
    return [html.escape(str(label)) for label in labels]


def _fit_time_axis(fig: go.Figure, trends: pd.DataFrame, period: str) -> None:
    """With only a few periods Plotly zooms in on a sliver of time and labels it in milliseconds.
    Label each period by its start date and leave room around it."""
    if len(trends) > FEW_PERIODS:
        return
    starts = list(trends["period_start"])
    pad = pd.Timedelta(days=PERIOD_DAYS[period])
    fig.update_xaxes(tickmode="array", tickvals=starts, tickformat="%d %b %Y",
                     range=[starts[0] - pad * 0.75, starts[-1] + pad * 1.25])


def pph_by_region(by_region: pd.DataFrame) -> go.Figure | None:
    if by_region is None or by_region.empty or "pledges_per_hour" not in by_region:
        return None
    df = by_region.sort_values("pledges_per_hour", ascending=True)
    fig = go.Figure(go.Bar(
        x=df["pledges_per_hour"], y=_plain(df["region"]), orientation="h", marker_color=BLUE,
        text=df["pledges_per_hour"].map(lambda v: "" if pd.isna(v) else f"{v:.2f}"), textposition="outside",
        hovertemplate="%{y}<br>%{x:.2f} pledges per hour<extra></extra>"))
    fig.update_layout(title=_title("Pledges per hour by region"), xaxis_title="Pledges per hour", yaxis_title=None, **LAYOUT)
    return fig


def rates_by_region(by_region: pd.DataFrame) -> go.Figure | None:
    if by_region is None or by_region.empty or not {"conversation_rate", "pledge_rate"} <= set(by_region.columns):
        return None
    df = by_region.sort_values("region")
    fig = go.Figure()
    for column, name, colour in [("conversation_rate", "Conversation rate", BLUE), ("pledge_rate", "Pledge rate", ORANGE)]:
        fig.add_bar(x=_plain(df["region"]), y=df[column], name=name, marker_color=colour,
                    hovertemplate=f"%{{x}}<br>{name}: %{{y:.1%}}<extra></extra>")
    fig.update_layout(title=_title("Conversion rates by region"), barmode="group", yaxis_tickformat=".0%", yaxis_title=None,
                      xaxis_title=None, **LAYOUT)
    return fig


def trend_pph(trends: pd.DataFrame | None, period: str = "week") -> go.Figure | None:
    if trends is None or trends.empty or "pledges_per_hour" not in trends:
        return None
    fig = go.Figure()
    fig.add_scatter(x=trends["period_start"], y=trends["pledges_per_hour"], mode="lines+markers",
                    name=f"Each {period}", line=dict(color=BLUE),
                    hovertemplate="%{x|%d %b %Y}<br>%{y:.2f} pledges per hour<extra></extra>")
    if "pph_rolling_4" in trends and trends["pph_rolling_4"].notna().any():
        fig.add_scatter(x=trends["period_start"], y=trends["pph_rolling_4"], mode="lines",
                        name=f"Last 4 {period}s", line=dict(color=ORANGE, dash="dash"),
                        hovertemplate="%{x|%d %b %Y}<br>%{y:.2f} (last 4)<extra></extra>")
    fig.update_layout(title=_title(f"Pledges per hour, by {period}"), yaxis_title="Pledges per hour", xaxis_title=None,
                      **{**LAYOUT, "height": 360})
    _fit_time_axis(fig, trends, period)
    return fig


def trend_pledges(trends: pd.DataFrame | None, period: str = "week") -> go.Figure | None:
    if trends is None or trends.empty or "pledges" not in trends:
        return None
    bar_width_ms = int(PERIOD_DAYS[period] * 0.8 * 24 * 3600 * 1000)  # a date axis needs an explicit bar width
    fig = go.Figure(go.Bar(x=trends["period_start"], y=trends["pledges"], marker_color=GREEN, width=bar_width_ms,
                           hovertemplate="%{x|%d %b %Y}<br>%{y:,.0f} pledges<extra></extra>"))
    fig.update_layout(title=_title(f"Pledges, by {period}"), yaxis_title="Pledges", xaxis_title=None,
                      **{**LAYOUT, "height": 360})
    _fit_time_axis(fig, trends, period)
    return fig
