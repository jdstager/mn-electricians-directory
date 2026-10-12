# Micro Directory — Minnesota Electricians (home-state Stage-1b)

The Minnesota half of the adopted play; Texas lab stays live: https://jdstager.github.io/texas-electricians-directory/
Playbook: [recommendation-use-both-plays-jesse-cunningham.md](../recommendation-use-both-plays-jesse-cunningham.md)

## Working decisions (locked 2026-10-08)
- **Niche:** electricians; **State:** Minnesota (home state — Stage-2 partner territory)
- **Source:** MN DLI CCLD bulk export `MNDLILicRegCertExport_Electrical.csv` (109,873 rows). Schema richer than TX: Orig_Date (tenure), Enforcement_Action (verifiable discipline flag), DBA_Name, email.
- **Included classes:** Class A/B Electrical Contractor · Class A/B Master Electrician · Journeyworker A/B · Maintenance Electrician. **Excluded on purpose:** Registered *Unlicensed* Electrician (52,613 — not licensed), power-limited/technology-systems (low-voltage trade), satellite/sign, lineman, electrical-employer registrations.
- **County mapping:** city→county from Wikipedia city/township gazetteer (scripts/pull_data.py); unresolved towns group on "Other towns" rollups.
- **Ranking:** class → registry tenure ("licensed since") → enforcement flag (disclosed on-page) → license count → phone → alphabetical.
- **Domain:** user registers exact-match at publish (candidates in VERDICT.md).

## Layout
- `scripts/pull_data.py` — registry CSV + city→county map fetch
- `scripts/prep.py` — clean + entity rollup (same schema as TX: drop-in generator)
- `scripts/build_site.py` — vendored state-agnostic generator (reads config/state.json)
- `config/state.json` — all MN strings/ranks
- `VERDICT.md` — 90-day keep/kill protocol

## Live
- staging: https://jdstager.github.io/mn-electricians-directory/ (after Pages enablement; weekly Thursday auto-rebuild)
6. **Bing Webmaster Tools** (5 min, free): create at bing.com/webmasters, "import from GSC" or add site minnesotaelectriciansdirectory.com (and the staging host) — send me the verification meta/file token and I place it; this becomes the real indexation instrument for the weekly log.
