from __future__ import annotations

import csv
from collections import defaultdict
from html import escape
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_PATH = PROJECT_ROOT / "data" / "fundraising_kpi_sample.csv"
OUTPUT_DIR = PROJECT_ROOT / "outputs"
OUTPUT_PATH = OUTPUT_DIR / "area_kpi_summary.csv"
INSIGHTS_PATH = OUTPUT_DIR / "insights.md"
SIGNUPS_CHART_PATH = OUTPUT_DIR / "signups_by_area.svg"
SIGNUP_RATE_CHART_PATH = OUTPUT_DIR / "signup_rate_by_area.svg"


def safe_rate(numerator: float, denominator: float) -> float:
    if denominator == 0:
        return 0.0
    return numerator / denominator


def read_rows() -> list[dict[str, str]]:
    with DATA_PATH.open(newline="", encoding="utf-8") as file:
        return list(csv.DictReader(file))


def summarize_by_area(rows: list[dict[str, str]]) -> list[dict[str, object]]:
    area_totals: dict[str, dict[str, float]] = defaultdict(
        lambda: {
            "doors_knocked": 0,
            "conversations": 0,
            "signups": 0,
            "donations_eur": 0,
            "active_hours": 0,
        }
    )

    for row in rows:
        area = row["area"]
        area_totals[area]["doors_knocked"] += float(row["doors_knocked"])
        area_totals[area]["conversations"] += float(row["conversations"])
        area_totals[area]["signups"] += float(row["signups"])
        area_totals[area]["donations_eur"] += float(row["donations_eur"])
        area_totals[area]["active_hours"] += float(row["active_hours"])

    summary = []
    for area, totals in area_totals.items():
        doors = totals["doors_knocked"]
        conversations = totals["conversations"]
        signups = totals["signups"]
        donations = totals["donations_eur"]
        hours = totals["active_hours"]

        summary.append(
            {
                "area": area,
                "doors_knocked": int(doors),
                "conversations": int(conversations),
                "signups": int(signups),
                "donations_eur": round(donations, 2),
                "active_hours": round(hours, 1),
                "conversation_rate": round(safe_rate(conversations, doors), 3),
                "signup_rate": round(safe_rate(signups, conversations), 3),
                "avg_donation_per_signup": round(safe_rate(donations, signups), 2),
                "signups_per_hour": round(safe_rate(signups, hours), 2),
            }
        )

    return sorted(summary, key=lambda item: item["signups"], reverse=True)


def write_summary(summary: list[dict[str, object]]) -> None:
    OUTPUT_DIR.mkdir(exist_ok=True)
    fieldnames = [
        "area",
        "doors_knocked",
        "conversations",
        "signups",
        "donations_eur",
        "active_hours",
        "conversation_rate",
        "signup_rate",
        "avg_donation_per_signup",
        "signups_per_hour",
    ]

    with OUTPUT_PATH.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(summary)


def write_bar_chart(
    summary: list[dict[str, object]],
    metric: str,
    title: str,
    output_path: Path,
    value_suffix: str = "",
) -> None:
    width = 900
    row_height = 58
    left_margin = 190
    right_margin = 110
    top_margin = 78
    height = top_margin + (len(summary) * row_height) + 50
    chart_width = width - left_margin - right_margin
    max_value = max(float(item[metric]) for item in summary)

    rows = [
        f'<svg width="{width}" height="{height}" viewBox="0 0 {width} {height}" '
        'xmlns="http://www.w3.org/2000/svg" role="img">'
        f"<title>{escape(title)}</title>"
        '<rect width="100%" height="100%" fill="#f8fafc"/>'
        f'<text x="{left_margin}" y="42" font-family="Arial" font-size="24" '
        f'font-weight="700" fill="#0f172a">{escape(title)}</text>'
    ]

    for index, item in enumerate(summary):
        y = top_margin + index * row_height
        value = float(item[metric])
        bar_width = 0 if max_value == 0 else int((value / max_value) * chart_width)
        label = escape(str(item["area"]))
        value_label = f"{value:.1%}" if metric.endswith("rate") else f"{value:g}{value_suffix}"

        rows.extend(
            [
                f'<text x="24" y="{y + 28}" font-family="Arial" font-size="16" '
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

    rows.append("</svg>")
    output_path.write_text("\n".join(rows), encoding="utf-8")


def write_insights(summary: list[dict[str, object]]) -> None:
    top_signups = max(summary, key=lambda item: item["signups"])
    top_signup_rate = max(summary, key=lambda item: item["signup_rate"])
    top_donations = max(summary, key=lambda item: item["donations_eur"])
    lowest_signup_rate = min(summary, key=lambda item: item["signup_rate"])

    content = f"""# Fundraising KPI Analysis - Insights

## Executive Summary

This sample analysis compares fundraising performance across four areas. The analysis uses basic KPI calculations to understand activity volume, conversion quality, donation value, and productivity.

## Key Findings

- Best area by total signups: {top_signups["area"]} with {top_signups["signups"]} signups.
- Best area by signup rate: {top_signup_rate["area"]} with {top_signup_rate["signup_rate"]:.1%}.
- Best area by total donation value: {top_donations["area"]} with {top_donations["donations_eur"]} EUR.
- Lowest signup rate: {lowest_signup_rate["area"]} with {lowest_signup_rate["signup_rate"]:.1%}.

## Business Recommendations

- Prioritize high-performing areas when planning future team routes.
- Review lower conversion areas to understand whether timing, team approach, or location quality affected results.
- Use signup rate and signups per hour together, because total signups alone does not show efficiency.
- Continue tracking KPIs weekly so team leaders can coach based on data instead of guesswork.

## Portfolio Note

This is a sample portfolio project. The data is fictional and created for learning purposes, but the analysis structure reflects real fundraising KPI work.
"""
    INSIGHTS_PATH.write_text(content, encoding="utf-8")


def print_insights(summary: list[dict[str, object]]) -> None:
    top_signups = max(summary, key=lambda item: item["signups"])
    top_signup_rate = max(summary, key=lambda item: item["signup_rate"])
    top_donations = max(summary, key=lambda item: item["donations_eur"])

    print("Fundraising KPI Analysis")
    print("========================")
    print(f"Best area by total signups: {top_signups['area']} ({top_signups['signups']} signups)")
    print(
        "Best area by signup rate: "
        f"{top_signup_rate['area']} ({top_signup_rate['signup_rate']:.1%})"
    )
    print(
        "Best area by donation value: "
        f"{top_donations['area']} ({top_donations['donations_eur']} EUR)"
    )
    print(f"Summary saved to: {OUTPUT_PATH}")


def main() -> None:
    rows = read_rows()
    summary = summarize_by_area(rows)
    write_summary(summary)
    write_insights(summary)
    write_bar_chart(summary, "signups", "Total Signups by Area", SIGNUPS_CHART_PATH)
    write_bar_chart(summary, "signup_rate", "Signup Rate by Area", SIGNUP_RATE_CHART_PATH)
    print_insights(summary)


if __name__ == "__main__":
    main()
