#!/usr/bin/env python3
"""Monday-log health instrument: live pages, sitemap fields, canonical, robots."""
import json, re, urllib.request
from pathlib import Path

BASE = "https://minnesotaelectriciansdirectory.com"
NAME = "Minnesota Electricians Directory"

def get(u):
    try:
        with urllib.request.urlopen(u, timeout=60) as r:
            return r.status, r.read().decode(errors="replace")
    except Exception as e:
        return 0, str(e)

rows = []
for suf in ("/", "/methodology/index.html", "/sitemap.xml", "/robots.txt", "/electricians/index.html"):
    st, _ = get(BASE + suf)
    rows.append(f"{suf or '/'} -> {st}")
sm = get(BASE + "/sitemap.xml")[1]
n = sm.count("<url>")
lastmod = sm.count("<lastmod>")
change = sm.count("<changefreq>")
st, home = get(BASE + "/index.html") if False else get(BASE + "/")
m = re.search(r'rel="canonical" href="([^"]+)"', home)
canonical = m.group(1) if m else "MISSING"
robots = get(BASE + "/robots.txt")[1]
print(f"**{NAME} ops** — " + " | ".join(rows))
print(f"sitemap: {n} urls | lastmod {lastmod} | changefreq {change} | home canonical: {canonical}")
print("robots:", [ln for ln in robots.splitlines() if "Sitemap" in ln])
