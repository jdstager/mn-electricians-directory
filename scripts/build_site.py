#!/usr/bin/env python3
"""Build the flat static directory site from data/clean/*.

Design rules (from the adopted play):
- Flat HTML/CSS, no images required, no JS, no build deps (stdlib only).
- Concrete slugs, one page per city with >=3 entities; 1-2 entity towns
  roll up onto their county page (anti-thin-pages rule).
- Schema.org JSON-LD on listings (Electrician = LocalBusiness subtype),
  ItemList on city pages, BreadcrumbList everywhere.
- Every listing links to the state licensing agency's public search for verification.
- No "best" overclaim in headings: pages say what the data is.

Output: site/dist/
"""
import csv, hashlib, html, json, re
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG = json.load(open(ROOT / "config/state.json"))
STATE = CONFIG["postal"]          # "TX"
STATE_NAME = CONFIG["state_name"] # "Texas"
TRADE = CONFIG["trade_noun"]      # "Electricians"
CLEAN = ROOT / "data/clean"
DIST = ROOT / "site/dist"

SITE_NAME = CONFIG["site_name"]
TDLR_SEARCH = CONFIG["verify_url"]
TDLR_LABEL = CONFIG["verify_label"]
AS_OF = None  # set from coverage_report
ESCAPE = html.escape

# ---------------------------------------------------------------- helpers

def proper_case(city):
    c = city.title()
    for a, b in [("Mckinney", "McKinney"), ("Mcallen", "McAllen"), ("Mccamey", "McCamey"),
                 ("Mclennan", "McLennan"), ("Mcallen", "McAllen"), ("Mcallen", "McAllen"),
                 ("Mcallen", "McAllen"), ("Mcallen", "McAllen"), ("Mcallen", "McAllen")]:
        c = c.replace(a, b)
    for pref in ("Mc", "Mac", "O'"):
        for word in c.split():
            if word.startswith(pref) and len(word) > len(pref):
                c = c.replace(word, pref + word[len(pref)].upper() + word[len(pref)+1:])
    return c


def slugify(s):
    s = re.sub(r"[^A-Z0-9]+", "-", (s or "").strip().upper())
    s = s.strip("-").lower()
    return s or "x"


# depth-aware relative links: pass depth int, compute prefix
def up(depth):
    return "" if depth == 0 else "../" * depth


def fmt_phone(p):
    p = (p or "").strip()
    if len(p) == 10 and p.isdigit():
        return f"({p[:3]}) {p[3:6]}-{p[6:]}"
    return p


def maps_link(e):
    # Address-string links: the dataset's own geocode column falls back to
    # city centroids on rows whose street geocode failed, which would print
    # a fake-precise pin. Google Maps geocodes the full address at click time.
    q = "+".join([e["line1"], proper_case(e["city"]).replace(" ", "+"), STATE, e["zip"]])
    return f"https://www.google.com/maps/search/?api=1&query={q}"


PAGE_HEAD = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<meta name="description" content="{desc}">
<link rel="stylesheet" href="{css}">
{jsonld}
</head>
<body>
<header class="site">
  <a class="brand" href="{home}">{site_name}</a>
  <nav><a href="{state_href}">All cities</a> · <a href="{meth_href}">Methodology</a></nav>
</header>
<main>
{body}
</main>
<footer>
<p>Sources: {source_name}, as of {as_of}. Not affiliated with or endorsed by the licensing agency. License details listed here are public record; verify any license at <a href="{tdlr}" rel="nofollow">{verify_label}</a>.</p>
<p><a href="{meth_href}">Ranking methodology</a></p>
</footer>
</body>
</html>"""


def page(title, desc, depth, body, jsonld=""):
    d = up(depth)
    return PAGE_HEAD.format(
        title=ESCAPE(title), desc=ESCAPE(desc), css=d + "static/site.css",
        home=d + "index.html",
        state_href=d + "electricians/index.html", meth_href=d + "methodology/index.html",
        tdlr=TDLR_SEARCH, verify_label=TDLR_LABEL, as_of=AS_OF,
        source_name=CONFIG["source_name"], site_name=SITE_NAME, body=body, jsonld=jsonld)


MICRO_CSS = """:root{--ink:#16181d;--mut:#5a5f6b;--line:#e6e8ec;--bg:#fff;--accent:#0b5cad}
*{box-sizing:border-box}body{margin:0;font:16px/1.55 -apple-system,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;color:var(--ink);background:var(--bg)}
a{color:var(--accent);text-decoration:none}a:hover{text-decoration:underline}
header.site{display:flex;gap:1.5rem;align-items:baseline;justify-content:space-between;padding:.9rem 1.2rem;border-bottom:1px solid var(--line)}
.brand{font-weight:700;font-size:1.05rem;color:var(--ink)}
main{max-width:44rem;margin:0 auto;padding:1.2rem}
h1{font-size:1.45rem;margin:.4rem 0 .3rem}h2{font-size:1.05rem;margin:1.2rem 0 .4rem;color:var(--ink)}
p.lede{color:var(--mut);margin:.2rem 0 1rem}
ul.plain{list-style:none;margin:0;padding:0}
ul.plain li{padding:.55rem 0;border-bottom:1px solid var(--line)}
ul.plain li:last-child{border-bottom:0}
.name{font-weight:600}
.cls{display:inline-block;font-size:.72rem;border:1px solid var(--line);border-radius:4px;padding:.05rem .35rem;margin-left:.35rem;color:var(--mut)}
.meta{color:var(--mut);font-size:.85rem}
.crumbs{font-size:.8rem;color:var(--mut);margin-bottom:.6rem}
ul.cities{columns:3 10rem;margin:0;padding-left:1.1rem}
ul.cities li{margin:.15rem 0}
table{border-collapse:collapse;width:100%}
footer{max-width:44rem;margin:0 auto;padding:1rem 1.2rem 2rem;color:var(--mut);font-size:.8rem;border-top:1px solid var(--line);margin-top:2rem}
.bigtiles{display:grid;grid-template-columns:repeat(auto-fill,minmax(11rem,1fr));gap:.5rem;margin:1rem 0}
.bigtiles a{border:1px solid var(--line);border-radius:8px;padding:.55rem .7rem;display:flex;justify-content:space-between;color:var(--ink)}
.bigtiles a span.n{color:var(--mut)}"""

# ---------------------------------------------------------------- loaders

def load():
    global AS_OF
    entities = list(csv.DictReader(open(CLEAN / "businesses.csv")))
    import ast as _ast
    for e in entities:
        e["classes"] = _ast.literal_eval(e["classes"])
        e["lics"] = _ast.literal_eval(e["lics"])
        e["latlon"] = _ast.literal_eval(e["latlon"]) if e["latlon"] else None
        e["tenure_years"] = float(e.get("tenure_years") or 0)
        e["enf"] = 1 if str(e.get("enf") or "0").strip() in ("1", "True", "true") else 0
        e["email"] = (e.get("email") or "").strip()
        e["entity_key"] = (
            e["name_norm"] + "::" + e["city"] + "::" + e["line1"]
        )
        slug_seed = slugify(e["name_norm"]) + "-" + e["lics"][0]["n"] if e["lics"] else slugify(e["name_norm"])
        # stable slug: name + city-short-hash to avoid collisions
        h = hashlib.md5(e["entity_key"].encode()).hexdigest()[:6]
        e["slug"] = f"{slugify(e['name_norm'])[:60]}-{h}"
    rep = json.load(open(CLEAN / "coverage_report.json"))
    AS_OF = rep["as_of"]
    return entities, rep


def rank_key(e):
    more = max([CLASS_RANK.get(l["class"], 0) for l in e["lics"]], default=0)
    return (-more, -e["tenure_years"], e["enf"], -(len(e["lics"])), 0 if e["phone"] else 1, e["name_norm"])


CLASS_RANK = CONFIG["class_rank"]

CLS_BADGE = CONFIG["class_badge"]


def lic_line(l):
    exp = l["exp"]
    return f"{CLS_BADGE.get(l['class'], l['class'])} #{l['n']} · valid through {exp}"


# ---------------------------------------------------------------- pages

def city_body(entities, city, disp, county, depth=2):
    ents = sorted(entities, key=rank_key)
    count = len(ents)
    body = [f'<div class="crumbs"><a href="{up(depth)}index.html">Home</a> › <a href="index.html">All cities</a> › {ESCAPE(disp)}</div>']
    body.append(f"<h1>{TRADE} in {ESCAPE(disp)}, {STATE}</h1>")
    body.append(f'<p class="lede">{count} state-licensed businesses with an address in {ESCAPE(disp)}, {STATE_NAME}, from the {CONFIG["agency_name"]} public registry as of {AS_OF}. Licensed by class: {",".join(sorted({CLS_BADGE[l["class"]] for e in ents for l in e["lics"]}))}.</p>')
    items = []
    body.append('<ul class="plain">')
    for e in ents:
        href = f"{e['slug']}/index.html"
        classes = "".join(f'<span class="cls">{CLS_BADGE.get(l["class"], l["class"])}</span>' for l in e["lics"][:4])
        body.append(
            f'<li><a class="name" href="{href}">{ESCAPE(proper_case(e["name"].title() if e["name"].isupper() else e["name"]))}</a>{classes}'
            f'<br><span class="meta">{ESCAPE(e["line1"])}, {ESCAPE(disp)} {STATE} {ESCAPE(e["zip"])}'
            + (f' · <a href="{fmt_map(e)}" rel="nofollow">map</a>' if True else "")
            + (f' · {fmt_phone(e["phone"])}' if e["phone"] else "")
            + f' · {ESCAPE(lic_line(e["lics"][0]))}</span></li>')
        items.append({"@type": "ListItem", "position": len(items) + 1,
                      "name": e["name"].title() if e["name"].isupper() else e["name"],
                      "url": f"electricians/{slugify(city)}/{e['slug']}/"})
    body.append("</ul>")
    body.append(f'<p class="meta">Every licensed electrical business in {ESCAPE(disp)} with an on-file address appears above. See <a href="{up(depth)}methodology/index.html">how this list is built</a>.</p>')
    ld = {"@context": "https://schema.org", "@type": "ItemList", "name": f"{TRADE} in {disp}, {STATE}", "numberOfItems": count, "itemListElement": items}
    return "\n".join(body), json.dumps(ld)


def fmt_map(e):
    return maps_link(e)


def main():
    global DIST
    import shutil
    # staged build + swap: never rm via shell, never serve a half-written tree
    staged = ROOT / "site/dist.staged"
    if staged.exists():
        shutil.rmtree(staged)
    staged.mkdir(parents=True, exist_ok=True)
    DIST = staged
    entities, rep = load()
    DIST.mkdir(parents=True, exist_ok=True)
    (DIST / "static").mkdir(exist_ok=True)
    (DIST / "static/site.css").write_text(MICRO_CSS)

    # index by city / county
    by_city = defaultdict(list)
    for e in entities:
        if e["city"]:
            by_city[e["city"]].append(e)
    county_of = {e["city"]: e["county"] for e in entities}
    cities_ge3 = [c for c, es in by_city.items() if len(es) >= 3]
    small = [c for c, es in by_city.items() if 0 < len(es) < 3]
    county_small = defaultdict(list)
    for c in small:
        county_small[county_of.get(c, "") or "Other towns"].append((c, by_city[c]))

    total_entities = len(entities)
    n_city_pages = len(cities_ge3)
    n_counties_rollup = len(county_small)

    # ---------------- homepage
    top = sorted(by_city.items(), key=lambda kv: -len(kv[1]))[:60]
    tiles = "".join(f'<a href="electricians/{slugify(c)}/index.html">{proper_case(c.title())}<span class="n">{len(es)}</span></a>'
                    for c, es in top)
    home_body = f"""
<h1>{ESCAPE(SITE_NAME)}</h1>
<p class="lede">Every {STATE_NAME}-licensed business with an on-file business address —
{total_entities:,} verified listings across {rep['cities']:,} {STATE_NAME} cities, from the
{CONFIG["agency_name"]} public registry as of {AS_OF}. No paid placement, no fake reviews;
ranked by verifiable license signals only.</p>
<div class="bigtiles">{tiles}</div>
<p><a href="electricians/index.html">Browse all {rep['cities']:,} cities →</a> ·
<a href="methodology/index.html">How this directory is built →</a></p>
"""
    (DIST / "index.html").write_text(page(
        f"{SITE_NAME} — licensed electricians in {rep['cities']:,} {STATE_NAME} cities",
        f"Verified directory of {total_entities:,} state-licensed electrical businesses in {STATE_NAME}, from the {CONFIG['agency_name']} registry as of {AS_OF}.",
        0, home_body))

    # ---------------- state page (all cities by county)
    county_cities = defaultdict(list)
    for c in sorted(by_city, key=lambda x: -len(by_city[x])):
        d = proper_case(c)
        n = len(by_city[c])
        county = county_of.get(c, "") or "Other towns"
        if n >= 3:
            link = f'<a href="{slugify(c)}/index.html">{d}</a>'
        else:
            link = (f'<a href="../county/{slugify(county)}/index.html">{d}</a>'
                    f' <span class="meta">({n}, county page)</span>')
        county_cities[county].append((n, c, d, link))
    sc = [f"<h2>{ESCAPE(proper_case(cn))} County</h2><ul class='cities'>" +
          "".join(f"<li>{link}</li>" for _, _, _, link in sorted(lst, reverse=True)) + "</ul>"
          for cn, lst in sorted(county_cities.items())]
    state_body = f"""
<div class="crumbs"><a href="{up(1)}index.html">Home</a> › All cities</div>
<h1>All covered {STATE_NAME} cities</h1>
<p class="lede">{rep['cities']:,} cities / census-designated places appear in the registry as of {AS_OF}.
Cities with three or more licensed businesses have their own page; smaller towns are grouped on their county page.</p>
{''.join(sc)}
"""
    (DIST / "electricians").mkdir(parents=True, exist_ok=True)
    (DIST / "electricians/index.html").write_text(
        page(f"All cities — {SITE_NAME}",
             f"Complete city index: licensed electrical businesses by {STATE_NAME} city, from the {CONFIG['agency_name']} registry ({AS_OF}).",
             1, state_body))

    # ---------------- county rollups for small towns
    county_urls = []
    for cn, lst in sorted(county_small.items()):
        cslug = slugify(cn)
        rows = []
        for c, es in sorted(lst):
            rows.append(f'<li><strong>{proper_case(c)}</strong><ul class="plain">')
            for e in sorted(es, key=rank_key):
                href = up(2) + f"electricians/{slugify(c)}/{e['slug']}/index.html"
                rows.append(f'<li><span class="name">{ESCAPE(e["name"])}</span>'
                            f'<span class="meta"> · {ESCAPE(e["line1"])} · {fmt_phone(e["phone"]) or "no phone on file"} · {ESCAPE(lic_line(e["lics"][0]))}'
                            f' · <a href="{href}">details</a></span></li>')
            rows.append("</ul></li>")
        body = (f'<div class="crumbs"><a href="{up(2)}index.html">Home</a> › '
                f'<a href="{up(2)}electricians/index.html">All cities</a></div>'
                f"<h1>{ESCAPE(proper_case(cn))} County — small towns</h1>"
                f'<p class="lede">Cities in {ESCAPE(proper_case(cn))} County with fewer than three licensed electrical '
                f"businesses, from the {CONFIG['agency_name']} registry as of {AS_OF}.</p><ul class='plain'>{''.join(rows)}</ul>")
        out = DIST / "county" / cslug / "index.html"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(page(f"{proper_case(cn.title())} County — {SITE_NAME}",
                            f"Licensed electrical businesses in small-town {proper_case(cn.title())} County, {STATE} ({AS_OF}).",
                            2, body, ""))
        county_urls.append(f"county/{cslug}/index.html")

    # ---------------- city pages + listing pages
    urls = [("index.html", 1.0, "daily"), ("methodology/index.html", 0.7, "monthly"),
            ("electricians/index.html", 0.9, "weekly")]

    def entity_url(cslug, e):
        return f"electricians/{cslug}/{e['slug']}/index.html"

    def write_entity_page(e, cslug, disp, city_page_exists=True, county=""):
        licbits = ""
        for l in sorted(e["lics"], key=lambda x: -CLASS_RANK.get(x["class"], 0)):
            licbits += f"<li>{ESCAPE(l['class'])} — license #{ESCAPE(l['n'])}, valid through {ESCAPE(l['exp'])}</li>"
        addr = {"@type": "PostalAddress", "streetAddress": e["line1"], "addressLocality": disp,
                "addressRegion": STATE, "postalCode": e["zip"], "addressCountry": "US"}
        tenure = (f'<li><span class="name">Licensed since</span><span class="meta">{e["first_issued"]}</span></li>'
                  if e.get("first_issued") else "")
        enf = ('<li><span class="name">Registry enforcement</span><span class="meta">This license is flagged with an enforcement action in the registry — review the record before hiring. The flag is shown for every flagged listing; it is not hidden.</span></li>' if e.get("enf") else "")
        eb_body = f"""
<div class="crumbs"><a href="{up(3)}index.html">Home</a> ›
<a href="{up(3)}electricians/index.html">Cities</a> ›
<a href="{'../../index.html' if city_page_exists else (up(3) + f'county/{slugify(county)}/index.html' if county else up(3) + 'electricians/index.html')}">{ESCAPE(disp)}</a> › {ESCAPE(e["name"])}</div>
<h1>{ESCAPE(e["name"])}</h1>
<p class="lede">{ESCAPE(disp)}, {STATE} — {' · '.join(e["classes"])} — {CONFIG['agency_name']} registry as of {AS_OF}.</p>
<ul class="plain">
<li><span class="name">Address</span><span class="meta">{ESCAPE(e["line1"])}, {ESCAPE(disp)} {STATE} {ESCAPE(e["zip"])} · {ESCAPE(e["county"]) if e["county"] else ""} County
 · <a href="{maps_link(e)}" rel="nofollow">open in Google Maps</a></span></li>
<li><span class="name">Phone</span><span class="meta">{(fmt_phone(e["phone"]) and f'<a href="tel:{e["phone"]}">{fmt_phone(e["phone"])}</a>') or "none on file — verify with the business directly"}</span></li>
{f'<li><span class="name">Registry email</span><span class="meta">{ESCAPE(e["email"])}</span></li>' if CONFIG.get("show_email") and e.get("email") else ""}
{tenure}{enf}
<li><span class="name">Licenses on file ({len(e['lics'])})</span><span class="meta"></span><ul>{licbits}</ul></li>
</ul>
<p>What this listing is: an extract of the public {CONFIG['agency_name']} license registry for this address
(license class, number, and current validity). It is not a review, ranking endorsement, or
recommendation. Before hiring any electrician, you can independently verify each license at
<a href="{TDLR_SEARCH}" rel="nofollow">{TDLR_LABEL}</a> and confirm the permit history with your city.</p>
<p class="meta">Listing changes, corrections, or removal requests: see <a href="{up(3)}methodology/index.html">methodology</a>.</p>
"""
        ld2 = {"@context": "https://schema.org", "@type": "Electrician",
               "name": e["name"], "address": addr,
               "telephone": e["phone"] or None}
        out2 = DIST / "electricians" / cslug / e["slug"] / "index.html"
        out2.parent.mkdir(parents=True, exist_ok=True)
        out2.write_text(page(f'{e["name"]} — electrician in {disp} {STATE} — license {e["lics"][0]["n"]}',
                             f'{e["name"]}: {", ".join(e["classes"])} — licensed electrician at {e["line1"]}, {disp} {STATE}. {STATE_NAME} license info as of {AS_OF}.',
                             3, eb_body,
                             f'<script type="application/ld+json">{json.dumps({k: v for k, v in ld2.items() if v}, ensure_ascii=False)}</script>'))
        urls.append((entity_url(cslug, e), 0.4, "monthly"))

    done = set()
    for c in cities_ge3:
        ents = by_city[c]
        cslug = slugify(c)
        disp = proper_case(c)
        body, ld = city_body(ents, c, disp, county_of.get(c, ""))
        out = DIST / "electricians" / cslug / "index.html"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(page(f"{TRADE} in {disp}, {STATE} ({len(ents)}) — {SITE_NAME}",
                            f"{len(ents)} state-licensed electrical businesses in {disp}, {STATE}, from the {CONFIG['agency_name']} registry as of {AS_OF}.",
                            2, body,
                            f'<script type="application/ld+json">{ld}</script>'))
        urls.append((f"electricians/{cslug}/index.html", 0.8, "weekly"))
        for e in ents:
            write_entity_page(e, cslug, disp, True, county_of.get(c, ""))
            done.add(e["entity_key"])

    # entities in small towns (<3 per city): listing pages live under the same
    # city path, reached from their county rollup page
    for e in entities:
        if e["city"] and e["entity_key"] not in done:
            write_entity_page(e, slugify(e["city"]), proper_case(e["city"]), False, e["county"])
            done.add(e["entity_key"])
    for u in county_urls:
        urls.append((u, 0.5, "monthly"))
    print("city pages:", n_city_pages, "county rollups:", n_counties_rollup, "entities:", total_entities)

    # ---------------- methodology page
    # config HTML chunks may carry {as_of} {rows} {dropped_no_city} {agency}
    # placeholders — the single .format() below fills them.
    meth = f"""
<div class="crumbs"><a href="{up(1)}index.html">Home</a> › Methodology</div>
<h1>How this directory is built</h1>
{CONFIG["methodology_source_html"]}
<h2>Inclusion rules</h2>
<ul>
<li>License must be <strong>currently valid</strong> — expiration date on or after {AS_OF} (expired, terminated, revoked, or suspended licenses are excluded from listings).</li>
<li>Business address must be in {STATE_NAME} and parseable to a city. The registry is a state record;
we list every qualifying business — there is no application, payment, or opt-in to appear.</li>
<li>Entities: one listing per business (same name + address with several license holders merges, showing every license number).</li>
{CONFIG["methodology_inclusion_extra_html"]}
</ul>
<h2>Ordering (no pay, no reviews)</h2>
<ol>
{CONFIG["ordering_html"]}
</ol>
<p>There is <strong>no paid placement</strong>, no affiliate links, and no user reviews (which would be
unverifiable on a registry-derived directory). Rankings reflect registry facts only.</p>
<h2>What this directory is not</h2>
<p>No endorsement: a listing means “holds an active {STATE_NAME} electrical license at this address,”
nothing more. Confirm licensing at <a href="{TDLR_SEARCH}" rel="nofollow">{TDLR_LABEL}</a>
and permit history with your city building department before hiring.</p>
<h2>Corrections &amp; removal</h2>
<p>Registry data is updated on {CONFIG["agency_name"]}'s cycle, so listings can lag reality. If a listing is wrong,
or you are a business that wants out, email the contact address on the homepage — corrections and
removal requests are honored promptly, no conditions.</p>
"""
    meth = meth.format(
        as_of=AS_OF,
        rows=f"{rep['stats']['rows_read']:,}",
        dropped_no_city=f"{rep['stats']['dropped_no_city']:,}",
        agency=CONFIG["agency_name"])
    (DIST / "methodology").mkdir(parents=True, exist_ok=True)
    (DIST / "methodology/index.html").write_text(page(
        f"Methodology — {SITE_NAME}",
        "Data source, inclusion rules, ranking signals, and removal policy.",
        1, meth))

    # ---------------- sitemap + robots
    sm = ['<?xml version="1.0" encoding="UTF-8"?>', '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    sm += [f"<url><loc>/{u}</loc><priority>{p}</priority></url>" for u, p, _ in urls]
    sm.append("</urlset>")
    (DIST / "sitemap.xml").write_text("\n".join(sm))
    (DIST / "robots.txt").write_text("User-agent: *\nAllow: /\nSitemap: /sitemap.xml\n")

    n_files = sum(1 for _ in DIST.rglob("index.html"))
    print("total pages:", n_files, "sitemap urls:", len(urls))
    # atomic-ish swap: prev -> dist
    final = ROOT / "site/dist"
    prev = ROOT / "site/dist.prev"
    if final.exists():
        if prev.exists():
            shutil.rmtree(prev)
        final.rename(prev)
    DIST.rename(final)
    shutil.rmtree(prev, ignore_errors=True)
    print("done ->", final)


if __name__ == "__main__":
    main()