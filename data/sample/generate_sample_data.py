"""Generate fully synthetic face-to-face (F2F) fundraising data for testing.

Standard library only. Deterministic for a given --seed.

Everything is invented: fundraisers are pseudonymous IDs (F001..F040), regions
and locations are generic fictional labels. Nothing here relates to a real
organisation, person or venue.

Outputs (written to --out, default: this script's folder):
  fundraisers.csv          fundraiser_id, home_region, start_date, experience
  locations.csv            location_id, location_label, region, location_type, target_pph
  shifts.csv               one row per fundraiser shift (activity grain); CONTAINS INJECTED ERRORS
  location_weekly.csv      location x ISO-week aggregates; CONTAINS ONE INJECTED ERROR
  injected_errors.csv      manifest of every deliberate error (rule, file, csv line, detail)

Conventions
  * hours are per-fundraiser active hours, so pledges_per_hour is per person-hour
    for every location type (target_pph is on the same basis).
  * For stands and fairs, "doors_knocked" means people approached.

Usage:  python generate_sample_data.py [--seed 42] [--out DIR]
"""
from __future__ import annotations

import argparse
import csv
import random
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

WEEKS = 12
START_MONDAY = date(2024, 1, 8)
N_FUNDRAISERS = 40
REGIONS = ["Metro Center", "West District", "North Transit", "East Residential", "South Campus"]

# per-region location mix: 3 stands, 1 fair, 2 door-to-door areas  => 6 x 5 = 30
LOCATION_MIX = [("Stand", 3), ("Fair", 1), ("Door to Door", 2)]

# funnel parameters by type: (doors lo, doors hi, conv rate, pledge-per-conversation rate, target pph)
TYPE_PARAMS = {
    "Door to Door": dict(doors=(300, 460), conv=0.30, pledge=0.15, target=2.2),
    "Stand":        dict(doors=(140, 260), conv=0.26, pledge=0.13, target=1.2),
    "Fair":         dict(doors=(110, 230), conv=0.38, pledge=0.18, target=1.8),
}
DONATION_CHOICES = [10, 12, 15, 20, 25, 30]
DONATION_WEIGHTS = [20, 10, 30, 20, 12, 8]
LABEL_PREFIX = {"Stand": "Shopping Centre", "Fair": "Community Fair", "Door to Door": "Residential Zone"}


def build_fundraisers(rng: random.Random):
    rows = []
    for i in range(1, N_FUNDRAISERS + 1):
        region = REGIONS[(i - 1) % len(REGIONS)]
        experience = rng.choices(["new", "mid", "senior"], weights=[25, 50, 25])[0]
        # "new" starts partway through the window so ramp-up is visible
        start = START_MONDAY - timedelta(days=rng.randint(200, 900))
        if experience == "new":
            start = START_MONDAY + timedelta(weeks=rng.randint(0, 4))
        rows.append(dict(fundraiser_id=f"F{i:03d}", home_region=region,
                         start_date=start.isoformat(), experience=experience))
    return rows


def build_locations(rng: random.Random):
    rows, n = [], 0
    for region in REGIONS:
        counters = defaultdict(int)
        for ltype, count in LOCATION_MIX:
            for _ in range(count):
                n += 1
                counters[ltype] += 1
                suffix = chr(ord("A") + counters[ltype] - 1)
                label = f"{LABEL_PREFIX[ltype]} {region.split()[0][0]}{suffix}"
                target = round(TYPE_PARAMS[ltype]["target"] * rng.uniform(0.9, 1.1), 2)
                rows.append(dict(location_id=f"L{n:02d}", location_label=label, region=region,
                                 location_type=ltype, target_pph=target))
    return rows


def build_shifts(rng: random.Random, fundraisers, locations):
    by_region = defaultdict(list)
    for loc in locations:
        by_region[loc["region"]].append(loc)

    skill = {f["fundraiser_id"]: rng.lognormvariate(0, 0.18) for f in fundraisers}
    # each location has a persistent quality factor; a few are clearly weak or strong
    loc_quality = {l["location_id"]: rng.lognormvariate(0, 0.25) for l in locations}
    week_region_noise = {(w, r): rng.uniform(0.9, 1.1) for w in range(WEEKS) for r in REGIONS}

    shifts, sid = [], 0
    for w in range(WEEKS):
        monday = START_MONDAY + timedelta(weeks=w)
        for f in fundraisers:
            fstart = date.fromisoformat(f["start_date"])
            n_shifts = rng.choices([2, 3, 4, 5], weights=[10, 35, 40, 15])[0]
            days = sorted(rng.sample([1, 2, 3, 4, 5], n_shifts))  # Tue..Sat
            for d in days:
                day = monday + timedelta(days=d)
                if day < fstart:
                    continue
                if rng.random() < 0.05:  # sickness / leave
                    continue
                loc = rng.choice(by_region[f["home_region"]])
                p = TYPE_PARAMS[loc["location_type"]]
                weeks_in = max(0, (day - fstart).days / 7)
                ramp = min(1.0, 0.65 + 0.35 * weeks_in / 6)  # new starters take ~6 weeks to reach full pace
                q = skill[f["fundraiser_id"]] * loc_quality[loc["location_id"]] \
                    * week_region_noise[(w, f["home_region"])] * ramp

                hours = round(rng.uniform(5, 7.5) * 2) / 2
                doors = int(rng.uniform(*p["doors"]) * (hours / 6.25))
                conv = min(doors, int(round(doors * p["conv"] * rng.uniform(0.8, 1.2) * min(q, 1.4) ** 0.5)))
                pledges = min(conv, int(round(conv * p["pledge"] * rng.uniform(0.7, 1.3) * q ** 0.7)))
                amounts = rng.choices(DONATION_CHOICES, weights=DONATION_WEIGHTS, k=pledges)
                # per-pledge supporter attributes -> used for the location-level quality columns
                monthly = sum(1 for _ in range(pledges) if rng.random() < (0.9 if loc["location_type"] == "Door to Door" else 0.72))
                regular = sum(1 for _ in range(pledges) if rng.random() < (0.62 if loc["location_type"] != "Fair" else 0.5))
                age_sum = sum(max(18, rng.gauss(42 if loc["location_type"] == "Fair" else 37, 9)) for _ in range(pledges))

                sid += 1
                shifts.append(dict(
                    shift_id=f"S{sid:05d}", date=day.isoformat(), iso_week=f"{day.isocalendar()[0]}-W{day.isocalendar()[1]:02d}",
                    region=f["home_region"], location_id=loc["location_id"], fundraiser_id=f["fundraiser_id"],
                    activity_type=loc["location_type"], doors_knocked=doors, conversations=conv, pledges=pledges,
                    total_monthly_value_eur=sum(amounts), active_hours=hours,
                    _monthly=monthly, _regular=regular, _age_sum=age_sum,
                ))
    return shifts


def build_location_weekly(shifts, locations):
    loc = {l["location_id"]: l for l in locations}
    agg = defaultdict(lambda: dict(pledges=0, hours=0.0, value=0, monthly=0, regular=0, age=0.0))
    for s in shifts:
        a = agg[(s["iso_week"], s["location_id"])]
        a["pledges"] += s["pledges"]; a["hours"] += s["active_hours"]; a["value"] += s["total_monthly_value_eur"]
        a["monthly"] += s["_monthly"]; a["regular"] += s["_regular"]; a["age"] += s["_age_sum"]
    rows = []
    for (week, lid), a in sorted(agg.items()):
        l, n = loc[lid], a["pledges"]
        rows.append(dict(
            period=week, location_id=lid, location_label=l["location_label"], location_type=l["location_type"],
            pledges=n, hours=round(a["hours"], 1), target_pph=l["target_pph"],
            achieved_pph=round(n / a["hours"], 2) if a["hours"] else "",
            monthly_pledge_share=round(a["monthly"] / n, 2) if n else "",
            regular_giving_share=round(a["regular"] / n, 2) if n else "",
            avg_supporter_age=round(a["age"] / n, 1) if n else "",
            avg_monthly_donation_eur=round(a["value"] / n, 2) if n else "",
        ))
    return rows


def inject_shift_errors(rng: random.Random, shifts, fundraisers):
    """Corrupt a handful of shift rows. Returns [(shift_id, rule, detail)]."""
    clean = [s for s in shifts if s["pledges"] >= 2 and s["conversations"] > s["pledges"] + 2]
    victims = rng.sample(clean, 12)
    log = []

    def note(row, rule, detail):
        log.append((row["shift_id"], rule, detail))

    v = iter(victims)
    r = next(v); old = r["conversations"]; r["conversations"] = r["doors_knocked"] + rng.randint(5, 30)
    note(r, "conversations_gt_doors", f"conversations {old} -> {r['conversations']} (doors {r['doors_knocked']})")
    r = next(v); old = r["pledges"]; r["pledges"] = r["conversations"] + rng.randint(2, 6)
    note(r, "pledges_gt_conversations", f"pledges {old} -> {r['pledges']} (conversations {r['conversations']})")
    r = next(v); r["active_hours"] = -abs(r["active_hours"])
    note(r, "negative_hours", f"active_hours -> {r['active_hours']}")
    r = next(v); r["active_hours"] = 0
    note(r, "zero_hours_with_activity", f"active_hours -> 0 with pledges={r['pledges']}")
    r = next(v); r["active_hours"] = ""
    note(r, "missing_required_value", "active_hours blank")
    r = next(v); r["active_hours"] = 62.0
    note(r, "implausible_hours", "active_hours -> 62.0")
    r = next(v); r["date"] = "2024-13-45"
    note(r, "unparseable_date", "date -> 2024-13-45")
    r = next(v); r["pledges"] = "n/a"
    note(r, "non_numeric_value", "pledges -> 'n/a'")
    r = next(v); old = r["region"]; r["region"] = old.lower() + " "
    note(r, "inconsistent_region_label", f"region {old!r} -> {r['region']!r}")
    r = next(v); r["fundraiser_id"] = "F999"
    note(r, "unknown_fundraiser_id", "fundraiser_id -> F999 (not in fundraisers.csv)")
    r = next(v); old = r["total_monthly_value_eur"]; r["total_monthly_value_eur"] = old * 12 + 400
    note(r, "implausible_value_per_pledge", f"total_monthly_value_eur {old} -> {r['total_monthly_value_eur']}")
    r = next(v); r["date"] = (date.fromisoformat(r["date"]) + timedelta(days=400)).isoformat()
    note(r, "date_out_of_range", f"date -> {r['date']} (outside the 12-week window)")

    dup = rng.choice([s for s in shifts if s["shift_id"] not in {x[0] for x in log}])
    shifts.append(dict(dup))
    log.append((dup["shift_id"], "exact_duplicate_row", "row appended a second time"))
    rng.shuffle(shifts)  # errors should not cluster at the end
    return log


def write_csv(path: Path, rows, fields):
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--out", type=Path, default=Path(__file__).resolve().parent)
    args = ap.parse_args()
    rng = random.Random(args.seed)
    args.out.mkdir(parents=True, exist_ok=True)

    fundraisers = build_fundraisers(rng)
    locations = build_locations(rng)
    shifts = build_shifts(rng, fundraisers, locations)
    weekly = build_location_weekly(shifts, locations)  # built from clean data, then corrupted below

    # location_weekly: one achieved_pph that no longer equals pledges / hours
    bad = rng.choice([w for w in weekly if w["pledges"] and w["hours"]])
    true_pph = bad["achieved_pph"]
    bad["achieved_pph"] = round(true_pph * 1.8 + 0.4, 2)
    weekly_log = [(bad["period"] + "/" + bad["location_id"], "achieved_pph_mismatch",
                   f"achieved_pph {true_pph} -> {bad['achieved_pph']} (pledges/hours disagree)")]

    shift_log = inject_shift_errors(rng, shifts, fundraisers)

    shift_fields = ["shift_id", "date", "iso_week", "region", "location_id", "fundraiser_id", "activity_type",
                    "doors_knocked", "conversations", "pledges", "total_monthly_value_eur", "active_hours"]
    weekly_fields = ["period", "location_id", "location_label", "location_type", "pledges", "hours", "target_pph",
                     "achieved_pph", "monthly_pledge_share", "regular_giving_share", "avg_supporter_age",
                     "avg_monthly_donation_eur"]
    write_csv(args.out / "fundraisers.csv", fundraisers, ["fundraiser_id", "home_region", "start_date", "experience"])
    write_csv(args.out / "locations.csv", locations,
              ["location_id", "location_label", "region", "location_type", "target_pph"])
    write_csv(args.out / "shifts.csv", shifts, shift_fields)
    write_csv(args.out / "location_weekly.csv", weekly, weekly_fields)

    # manifest: csv line numbers (header = line 1) so tests can assert exact row-level findings
    manifest = []
    for sid, rule, detail in shift_log:
        lines = [i + 2 for i, s in enumerate(shifts) if s["shift_id"] == sid]
        manifest.append(dict(file="shifts.csv", csv_line="|".join(map(str, lines)), key=sid, rule=rule, detail=detail))
    for key, rule, detail in weekly_log:
        period, lid = key.split("/")
        line = next(i + 2 for i, w in enumerate(weekly) if w["period"] == period and w["location_id"] == lid)
        manifest.append(dict(file="location_weekly.csv", csv_line=line, key=key, rule=rule, detail=detail))
    write_csv(args.out / "injected_errors.csv", manifest, ["file", "csv_line", "key", "rule", "detail"])

    print(f"fundraisers: {len(fundraisers)}  locations: {len(locations)}  regions: {len(REGIONS)}  weeks: {WEEKS}")
    print(f"shifts.csv: {len(shifts)} rows   location_weekly.csv: {len(weekly)} rows")
    print(f"injected errors: {len(manifest)}  (see injected_errors.csv)")
    print(f"written to {args.out}")


if __name__ == "__main__":
    main()
