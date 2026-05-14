from __future__ import annotations

import csv
from collections import defaultdict
from html import escape
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "data"
OUTPUT_DIR = PROJECT_ROOT / "outputs"

ACTIVITY_DATA_PATH = DATA_DIR / "fundraising_kpi_sample.csv"
LOCATION_DATA_PATH = DATA_DIR / "location_performance_sample.csv"

AREA_SUMMARY_PATH = OUTPUT_DIR / "area_kpi_summary.csv"
LOCATION_SUMMARY_PATH = OUTPUT_DIR / "location_kpi_summary.csv"
INSIGHTS_PATH = OUTPUT_DIR / "insights.md"

PLEDGES_CHART_PATH = OUTPUT_DIR / "pledges_by_region.svg"
PPH_CHART_PATH = OUTPUT_DIR / "pledges_per_hour_by_region.svg"
LOCATION_CHART_PATH = OUTPUT_DIR / "location_target_attainment.svg"


def safe_rate(numerator: float, denominator: float) -> float:
    if denominator == 0:
        return 0.0
    return numerator / denominator


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as file:
        return list(csv.DictReader(file))


def write_csv(path: Path, rows: list[dict[str, object]], fieldnames: list[str]) -> None:
    OUTPUT_DIR.mkdir(exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def summarize_by_region(rows: list[dict[str, str]]) -> list[dict[str, object]]:
    totals: dict[str, dict[str, float]] = defaultdict(
        lambda: {
            "doors_knocked": 0,
            "conversations": 0,
            "pledges": 0,
            "total_monthly_value_eur": 0,
            "active_hours": 0,
        }
    )

    for row in rows:
        region = row["region"]
        totals[region]["doors_knocked"] += float(row["doors_knocked"])
        totals[region]["conversations"] += float(row["conversations"])
        totals[region]["pledges"] += float(row["pledges"])
        totals[region]["total_monthly_value_eur"] += float(row["total_monthly_value_eur"])
        totals[region]["active_hours"] += float(row["active_hours"])

    summary = []
    for region, values in totals.items():
        doors = values["doors_knocked"]
        conversations = values["conversations"]
        pledges = values["pledges"]
        monthly_value = values["total_monthly_value_eur"]
        hours = values["active_hours"]

        summary.append(
            {
                "region": region,
                "doors_knocked": int(doors),
                "conversations": int(conversations),
                "pledges": int(pledges),
                "total_monthly_value_eur": round(monthly_value, 2),
                "active_hours": round(hours, 1),
                "conversation_rate": round(safe_rate(conversations, doors), 3),
                "pledge_rate": round(safe_rate(pledges, conversations), 3),
                "pledges_per_hour": round(safe_rate(pledges, hours), 2),
                "avg_monthly_donation_eur": round(safe_rate(monthly_value, pledges), 2),
            }
        )

    return sorted(summary, key=lambda item: item["pledges"], reverse=True)


def summarize_locations(rows: list[dict[str, str]]) -> list[dict[str, object]]:
    summary = []
    for row in rows:
        target_pph = float(row["target_pph"])
        achieved_pph = float(row["achieved_pph"])
        target_attainment = safe_rate(achieved_pph, target_pph)
        productivity_gap = achieved_pph - target_pph

        summary.append(
            {
                "period": row["period"],
                "location_label": row["location_label"],
                "location_type": row["location_type"],
                "pledges": int(float(row["pledges"])),
                "hours": round(float(row["hours"]), 1),
                "target_pph": round(target_pph, 2),
                "achieved_pph": round(achieved_pph, 2),
                "target_attainment": round(target_attainment, 3),
                "productivity_gap": round(productivity_gap, 2),
                "monthly_pledge_share": round(float(row["monthly_pledge_share"]), 3),
                "regular_giving_share": round(float(row["regular_giving_share"]), 3),
                "avg_supporter_age": round(float(row["avg_supporter_age"]), 1),
                "avg_monthly_donation_eur": round(float(row["avg_monthly_donation_eur"]), 2),
                "planning_priority": classify_planning_priority(target_attainment),
            }
        )

    return sorted(summary, key=lambda item: item["target_attainment"], reverse=True)


def classify_planning_priority(target_attainment: float) -> str:
    if target_attainment >= 1.0:
        return "Scale or repeat"
    if target_attainment >= 0.75:
        return "Keep and monitor"
    return "Review before repeating"


def write_bar_chart(
    rows: list[dict[str, object]],
    label_key: str,
    metric_key: str,
    title: str,
    output_path: Path,
    *,
    percent: bool = False,
    max_items: int | None = None,
) -> None:
    chart_rows = rows[:max_items] if max_items else rows
    width = 920
    row_height = 58
    left_margin = 220
    right_margin = 120
    top_margin = 78
    height = top_margin + (len(chart_rows) * row_height) + 50
    chart_width = width - left_margin - right_margin
    max_value = max(float(item[metric_key]) for item in chart_rows)

    svg_rows = [
        f'<svg width="{width}" height="{height}" viewBox="0 0 {width} {height}" '
        'xmlns="http://www.w3.org/2000/svg" role="img">',
        f"<title>{escape(title)}</title>",
        '<rect width="100%" height="100%" fill="#f8fafc"/>',
        f'<text x="{left_margin}" y="42" font-family="Arial" font-size="24" '
        f'font-weight="700" fill="#0f172a">{escape(title)}</text>',
    ]

    for index, item in enumerate(chart_rows):
        y = top_margin + index * row_height
        value = float(item[metric_key])
        bar_width = 0 if max_value == 0 else int((value / max_value) * chart_width)
        label = escape(str(item[label_key]))
        value_label = f"{value:.1%}" if percent else f"{value:g}"

        svg_rows.extend(
            [
                f'<text x="24" y="{y + 28}" font-family="Arial" font-size="15" '
                f'font-weight="600" fill="#334155">{label}</text>',
                f'<rect x="{left_margin}" y="{y + 6}" width="{chart_width}" height="30" '
                'rx="6" fill="#e2e8f0"/>',
                f'<rect x="{left_margin}" y="{y + 6}" width="{bar_width}" height="30" '
                'rx="6" fill="#2563eb"/>',
                f'<text x="{left_margin + chart_width + 18}" y="{y + 28}" '
                'font-family="Arial" font-size="15" font-weight="700" '
                f'fill="#0f172a">{escape(value_label)}</text>',
            ]
        )

    svg_rows.append("</svg>")
    output_path.write_text("\n".join(svg_rows), encoding="utf-8")


def write_insights(
    region_summary: list[dict[str, object]],
    location_summary: list[dict[str, object]],
) -> None:
    top_region_pledges = max(region_summary, key=lambda item: item["pledges"])
    top_region_pph = max(region_summary, key=lambda item: item["pledges_per_hour"])
    top_location = max(location_summary, key=lambda item: item["target_attainment"])
    review_locations = [
        item for item in location_summary if item["planning_priority"] == "Review before repeating"
    ]

    review_names = ", ".join(str(item["location_label"]) for item in review_locations[:3])
    if not review_names:
        review_names = "None in this sample"

    content = f"""# Fundraising KPI Analysis - Insights

## Executive Summary

This project analyzes fictional nonprofit face-to-face fundraising data. It combines team activity KPIs and location performance KPIs to support route planning, coaching, and performance reporting.

## Key Findings

- Best region by total pledges: {top_region_pledges["region"]} with {top_region_pledges["pledges"]} pledges.
- Best region by productivity: {top_region_pph["region"]} with {top_region_pph["pledges_per_hour"]} pledges per hour.
- Best location by target attainment: {top_location["location_label"]} at {top_location["target_attainment"]:.1%} of target PPH.
- Locations to review before repeating: {review_names}.

## Business Recommendations

- Prioritize regions with both high pledge volume and high pledges per hour.
- Repeat or scale locations that meet or exceed target PPH.
- Review locations below 75% target attainment before booking them again.
- Compare activity volume with conversion quality, because high traffic does not always mean strong fundraising performance.
- Use this analysis weekly so team leaders can coach with evidence instead of relying only on memory.

## Data Privacy Note

This project uses fictional sample data. It does not include private organizational data, real employee-level results, real route strategy, or exact confidential location performance.
"""
    INSIGHTS_PATH.write_text(content, encoding="utf-8")


def print_summary(
    region_summary: list[dict[str, object]],
    location_summary: list[dict[str, object]],
) -> None:
    best_region = max(region_summary, key=lambda item: item["pledges"])
    best_location = max(location_summary, key=lambda item: item["target_attainment"])

    print("Fundraising KPI Analysis")
    print("========================")
    print(f"Best region by pledges: {best_region['region']} ({best_region['pledges']} pledges)")
    print(
        "Best location by target attainment: "
        f"{best_location['location_label']} ({best_location['target_attainment']:.1%})"
    )
    print(f"Region summary saved to: {AREA_SUMMARY_PATH}")
    print(f"Location summary saved to: {LOCATION_SUMMARY_PATH}")


def main() -> None:
    activity_rows = read_csv(ACTIVITY_DATA_PATH)
    location_rows = read_csv(LOCATION_DATA_PATH)

    region_summary = summarize_by_region(activity_rows)
    location_summary = summarize_locations(location_rows)

    write_csv(
        AREA_SUMMARY_PATH,
        region_summary,
        [
            "region",
            "doors_knocked",
            "conversations",
            "pledges",
            "total_monthly_value_eur",
            "active_hours",
            "conversation_rate",
            "pledge_rate",
            "pledges_per_hour",
            "avg_monthly_donation_eur",
        ],
    )
    write_csv(
        LOCATION_SUMMARY_PATH,
        location_summary,
        [
            "period",
            "location_label",
            "location_type",
            "pledges",
            "hours",
            "target_pph",
            "achieved_pph",
            "target_attainment",
            "productivity_gap",
            "monthly_pledge_share",
            "regular_giving_share",
            "avg_supporter_age",
            "avg_monthly_donation_eur",
            "planning_priority",
        ],
    )

    write_insights(region_summary, location_summary)
    write_bar_chart(region_summary, "region", "pledges", "Pledges by Region", PLEDGES_CHART_PATH)
    write_bar_chart(region_summary, "region", "pledges_per_hour", "Pledges per Hour by Region", PPH_CHART_PATH)
    write_bar_chart(
        location_summary,
        "location_label",
        "target_attainment",
        "Location Target Attainment",
        LOCATION_CHART_PATH,
        percent=True,
        max_items=8,
    )
    print_summary(region_summary, location_summary)


if __name__ == "__main__":
    main()
