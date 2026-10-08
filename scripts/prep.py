#!/usr/bin/env python3
"""MN DLI electrical registry -> clean entities (same schema as TX prep).

Included classes only (see config/state.json); status normalized to active;
out-of-state rows dropped; city normalized + county joined from
data/geo/mn_city_county.json (unresolved -> "").

Outputs: data/clean/licenses_active_mn.csv.gz, businesses.csv,
         city_counts.csv, coverage_report.json
"""
import csv, collections, gzip, json, re, sys
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data/raw-mn" / "MNDLILicRegCertExport_Electrical.csv"
GEO = ROOT / "data/geo" / "mn_city_county.json"
CLEAN = ROOT / "data/clean"
CLEAN.mkdir(parents=True, exist_ok=True)
TODAY = date.today()

CLASS_MAP = {
    "Class A Electrical Contractor": "Electrical Contractor (Class A)",
    "Class B Electrical Contractor": "Electrical Contractor (Class B)",
    "Class A Master Electrician": "Master Electrician (Class A)",
    "Class B Master Electrician": "Master Electrician (Class B)",
    "Journeyworker A Electrician": "Journeyworker Electrician (Class A)",
    "Journeyworker B Electrician": "Journeyworker Electrician (Class B)",
    "Maintenance Electrician": "Maintenance Electrician",
}
ACTIVE = {"issued", "licensed"}


def norm_name(s):
    s = re.sub(r"\s+", " ", (s or "").strip().upper())
    s = s.replace(",", " ").replace(".", " ")
    s = re.sub(r"[^A-Z0-9& ]", "", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def norm_city(c):
    c = (c or "").strip().upper()
    c = re.sub(r",\s*MN\s*\d*.*$", "", c)       # "APPLE VALLEY, MN 55124"
    c = re.sub(r"\bMN\b", " ", c)               # stray "ALBERTVILLE MN"
    c = c.replace(".", "").replace("'", "")
    c = re.sub(r"\s+", " ", c).strip(" ,")
    if c.startswith("ST "):
        c = "SAINT " + c[3:]
    if not re.fullmatch(r"[A-Z][A-Z ]*", c):     # letters/spaces only else junk
        c = ""
    return c


def parse_date(s):
    try:
        return datetime.strptime((s or "").strip(), "%m/%d/%Y").date()
    except Exception:
        return None


def main():
    county_map = json.load(open(GEO)) if GEO.exists() else {}
    rows = csv.DictReader(open(RAW, encoding="utf-8-sig", errors="replace"))

    stats = {"rows_read": 0, "kept": 0, "dropped_out_of_state": 0,
             "dropped_inactive": 0, "dropped_no_city": 0,
             "by_class": collections.Counter(), "with_enforcement": 0}
    licenses, city_norm_map = [], {}

    def norm_c(c):
        k = norm_city(c)
        return k

    for r in rows:
        stats["rows_read"] += 1
        st = (r.get("Status") or "").strip().lower()
        if st not in ACTIVE:
            stats["dropped_inactive"] += 1
            continue
        if (r.get("St") or "").strip().upper() != "MN":
            stats["dropped_out_of_state"] += 1
            continue
        sub = (r.get("License_Subtype") or "").strip()
        cls = CLASS_MAP.get(sub)
        if not cls:
            continue  # excluded class rows are counted separately below
        stats["by_class"][cls] += 1
        city = norm_c(r.get("City"))
        if not city:
            stats["dropped_no_city"] += 1
        city_norm_map.setdefault(city, city)
        orig = parse_date(r.get("Orig_Date"))
        exp = parse_date(r.get("Exp_Date"))
        enf = "1" if (r.get("Enforcement_Action") or "").strip() == "1" else "0"
        if enf == "1":
            stats["with_enforcement"] += 1
        pers = (r.get("Bus_Pers") or "").strip()
        name = (r.get("DBA_Name") or "").strip() or (r.get("Name") or "").strip()
        licenses.append({
            "subtype": sub, "license_type": cls,
            "license_number": (r.get("Lic_Number") or "").strip(),
            "entity_name": name,
            "business_name_norm": norm_name(name),
            "is_business_row": "1" if pers == "Business" else "0",
            "line1": re.sub(r"\s+", " ", (r.get("Addr1") or "").strip().upper()),
            "line2": re.sub(r"\s+", " ", (r.get("Addr2") or "").strip().upper()),
            "city": city,
            "zip": (r.get("Zip") or "").strip()[:5],
            "county": county_map.get(city, ""),
            "phone": re.sub(r"\D", "", r.get("Phone_No") or ""),
            "email": (r.get("Email_Address") or "").strip(),
            "first_issued": orig.isoformat() if orig else "",
            "exp_date": exp.isoformat() if exp else "",
            "enf": enf,
            "latlon": None,
        })
        stats["kept"] += 1

    # dedupe licenses
    seen = {}
    for l in licenses:
        seen[l["license_number"] + "|" + l["license_type"]] = l
    licenses = list(seen.values())

    # entity rollup: name + line1 + city (line2 folded in)
    biz = {}
    for l in licenses:
        if not l["city"] or not l["line1"]:
            continue
        k = f"{l['business_name_norm']}::{l['line1']}::{l['city']}"
        e = biz.get(k)
        if e is None:
            e = {"key": k, "name": l["entity_name"], "name_norm": l["business_name_norm"],
                 "line1": l["line1"], "city": l["city"], "zip": l["zip"], "county": l["county"],
                 "phone": "", "email": "", "latlon": None, "class_set": set(),
                 "lics": [], "exp_max": "", "first_issued": "", "tenure_years": 0.0, "enf": 0}
        e["lics"].append({"class": l["license_type"], "n": l["license_number"], "exp": l["exp_date"]})
        if l["phone"] and not e["phone"]:
            e["phone"] = l["phone"]
        if l["email"] and not e["email"]:
            e["email"] = l["email"]
        e["class_set"].add(l["license_type"])
        if l["exp_date"] and l["exp_date"] > e["exp_max"]:
            e["exp_max"] = l["exp_date"]
        if l["first_issued"] and (not e["first_issued"] or l["first_issued"] < e["first_issued"]):
            e["first_issued"] = l["first_issued"]
        if l["enf"] == "1":
            e["enf"] = 1
        biz[k] = e
    entities = []
    for e in biz.values():
        e["classes"] = sorted(e.pop("class_set"))
        e["is_contractor"] = any(c.startswith("Electrical Contractor") for c in e["classes"])
        e["has_master"] = any(c.startswith("Master Electrician") for c in e["classes"])
        if e["first_issued"]:
            d0 = datetime.strptime(e["first_issued"], "%Y-%m-%d").date()
            e["tenure_years"] = round(max(0.0, (TODAY - d0).days / 365.25), 1)
        entities.append(e)

    # coverage
    city_counts = collections.Counter(e["city"] for e in entities)
    city_sorted = sorted(city_counts.items(), key=lambda x: -x[1])
    for c, n in city_sorted[:30]:
        print(f"{n:6d}  {c.title()}")
    coverage = {"as_of": TODAY.isoformat(), "stats": {k: (dict(v) if isinstance(v, collections.Counter) else v) for k, v in stats.items()},
                "unique_licenses": len(licenses), "unique_business_entities": len(entities),
                "cities": len(city_counts),
                "cities_ge3": sum(1 for _, n in city_counts.items() if n >= 3),
                "cities_ge5": sum(1 for _, n in city_counts.items() if n >= 5),
                "counties_mapped": sum(1 for _, n in collections.Counter(e['county'] for e in entities).items() if n),
                "top30": city_sorted[:30]}
    (CLEAN / "coverage_report.json").write_text(json.dumps(coverage, indent=1))

    with gzip.open(CLEAN / "licenses_active_mn.csv.gz", "wt", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(licenses[0].keys()))
        w.writeheader(); w.writerows(licenses)
    with open(CLEAN / "businesses.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(entities[0].keys()))
        w.writeheader(); w.writerows(entities)
    with open(CLEAN / "city_counts.csv", "w", newline="") as f:
        w = csv.writer(f); w.writerow(["city", "businesses"]); w.writerows(city_sorted)
    print(json.dumps({k: v for k, v in coverage.items() if k != "top30"}, indent=1))


if __name__ == "__main__":
    main()