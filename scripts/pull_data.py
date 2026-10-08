#!/usr/bin/env python3
"""Fetch MN DLI electrical-license registry CSV + a city->county map.

- data/raw-mn/MNDLILicRegCertExport_Electrical.csv (single-file bulk export)
- data/geo/mn_city_county.json (Wikipedia 'List of cities / townships in Minnesota')
"""
import json, re
from pathlib import Path
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data/raw-mn"
GEO = ROOT / "data/geo"
for d in (RAW, GEO):
    d.mkdir(parents=True, exist_ok=True)

UA = {"User-Agent": "mn-electricians-directory build (contact: repo owner)"}
CSV_URL = "https://secure.doli.state.mn.us/ccld/data/MNDLILicRegCertExport_Electrical.csv"
WIKI_TPL = "https://en.wikipedia.org/w/index.php?title={title}&action=raw"


def fetch(url, tries=3, timeout=300):
    import time
    for t in range(tries):
        try:
            with urlopen(Request(url, headers=UA), timeout=timeout) as r:
                return r.read()
        except Exception as e:
            if t == tries - 1:
                raise
            print(f"retry {t+1} after {e}", flush=True)
            time.sleep(5)


def norm_name(c):
    c = (c or "").strip().upper()
    c = c.replace(".", "").replace("'", "")
    c = re.sub(r",\s*MN\s*\d*.*$", "", c)   # "APPLE VALLEY, MN 55124" -> APPLE VALLEY
    c = re.sub(r"\bMN\b", " ", c)           # stray "ALBERTVILLE MN"
    c = re.sub(r"\s+", " ", c).strip(" ,")
    if c.startswith("ST "):
        c = "SAINT " + c[3:]
    return c


def parse_wiki(title):
    txt = fetch(WIKI_TPL.format(title=title)).decode("utf-8", "replace")
    mapping = {}
    rows = re.split(r"^\|-", txt, flags=re.M)
    for blob in rows:
        links = re.findall(r"\[\[([^\]|]+)(?:\|([^\]]+))?\]\]", blob)
        if not links:
            continue
        town, county = "", ""
        for target, disp in links:
            t = (disp or target).strip()
            if "County" in blob and "County" in (target or ""):
                if not county:
                    county = (disp or target.split("|")[0].replace(" County, Minnesota", "").replace(" County", "")).strip()
                continue
            if town:
                continue
            if "{{" in t or "|" in t:
                continue
            # city link: prefer the explicit display name
            base = t
            for suf in (", Minnesota", ", MN"):
                base = base.replace(suf, "")
            if 2 <= len(base) <= 40 and re.match(r"^[A-Za-z .']+$", base):
                town = norm_name(base)
        if town and county:
            mapping.setdefault(town, county)
    return mapping


def main():
    csv_path = RAW / "MNDLILicRegCertExport_Electrical.csv"
    data = fetch(CSV_URL)
    csv_path.write_bytes(data)
    print(f"registry CSV: {len(data):,} bytes -> {csv_path.name}")

    if not csv_path.exists() or csv_path.stat().st_size < 1_000_000:
        raise SystemExit("registry CSV missing/too small")

    mapping = {}
    mapping.update(parse_wiki("List_of_cities_in_Minnesota"))
    mapping.update(parse_wiki("List_of_townships_in_Minnesota"))
    (GEO / "mn_city_county.json").write_text(json.dumps(mapping, indent=0, sort_keys=True))
    print(f"city->county map: {len(mapping):,} entries")
    for probe in ("MINNEAPOLIS", "SAINT PAUL", "ROCHESTER", "DULUTH", "SAINT CLOUD", "ST CLOUD"):
        print("  map:", probe, "->", mapping.get(probe))


if __name__ == "__main__":
    main()