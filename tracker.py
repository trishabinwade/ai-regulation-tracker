#!/usr/bin/env python3
"""
AI Regulation Tracker v3 — multi-page dark editorial site
=========================================================
Tracks REAL legislation and litigation instead of news headlines:

  1. US federal + state AI bills  (Congress.gov / OpenStates APIs)
  2. US AI-related lawsuits        (CourtListener search — no key needed)
  3. Enacted AI laws worldwide     (hand-curated data/global_laws.json)

Renders a four-page static site into docs/ for GitHub Pages:

  docs/index.html       home / introduction
  docs/us-laws.html     US AI Law Tracker (federal bills + clickable state map)
  docs/litigation.html  AI Litigation Monitor (dockets + opinions)
  docs/global.html      Global AI Regulation Index (clickable world map)

Run it with:
    python3 tracker.py

Optional environment variables (sections degrade gracefully without them):
    CONGRESS_API_KEY    free at https://api.congress.gov/sign-up
    OPENSTATES_API_KEY  free at https://open.pluralpolicy.com/accounts/signup/

Standard library only — no third-party packages.
"""

import html
import json
import os
import re
import urllib.parse
import urllib.request
from datetime import datetime
from zoneinfo import ZoneInfo

# Display dates in the owner's local timezone.
LOCAL_TZ = ZoneInfo("America/Los_Angeles")

CONGRESS_KEY = os.environ.get("CONGRESS_API_KEY", "").strip()
OPENSTATES_KEY = os.environ.get("OPENSTATES_API_KEY", "").strip()
CONGRESS = "119"            # current Congress
FEDERAL_PAGES = 4          # 250 bills/page -> scan the 1000 most recently updated
FEDERAL_CAP = 25
STATE_QUERIES = [          # OpenStates full-text searches, merged and deduped
    '"artificial intelligence"',
    'deepfake',
    '"algorithmic discrimination"',
    '"automated decision"',
    '"synthetic media"',
]
STATE_CAP = 40
DOCKET_CAP = 12             # RECAP dockets
OPINION_CAP = 8             # published opinions
REQUEST_TIMEOUT = 25
UA = {"User-Agent": "AI-Regulation-Tracker/3.0"}

# Congress.gov has no keyword search, so federal bills are filtered client-side
# against title + policy area + latest action text.
AI_RE = re.compile(
    r"\b(artificial intelligence|\bai\b|machine learning|generative ai|"
    r"foundation models?|frontier ai|large language models?|deepfakes?|"
    r"algorithmic|chatbots?|automated decisions?)\b",
    re.IGNORECASE,
)

STATE_ABBR = {
    "Alabama": "AL", "Alaska": "AK", "Arizona": "AZ", "Arkansas": "AR",
    "California": "CA", "Colorado": "CO", "Connecticut": "CT", "Delaware": "DE",
    "District of Columbia": "DC", "Florida": "FL", "Georgia": "GA",
    "Hawaii": "HI", "Idaho": "ID", "Illinois": "IL", "Indiana": "IN",
    "Iowa": "IA", "Kansas": "KS", "Kentucky": "KY", "Louisiana": "LA",
    "Maine": "ME", "Maryland": "MD", "Massachusetts": "MA", "Michigan": "MI",
    "Minnesota": "MN", "Mississippi": "MS", "Missouri": "MO", "Montana": "MT",
    "Nebraska": "NE", "Nevada": "NV", "New Hampshire": "NH",
    "New Jersey": "NJ", "New Mexico": "NM", "New York": "NY",
    "North Carolina": "NC", "North Dakota": "ND", "Ohio": "OH",
    "Oklahoma": "OK", "Oregon": "OR", "Pennsylvania": "PA",
    "Rhode Island": "RI", "South Carolina": "SC", "South Dakota": "SD",
    "Tennessee": "TN", "Texas": "TX", "Utah": "UT", "Vermont": "VT",
    "Virginia": "VA", "Washington": "WA", "West Virginia": "WV",
    "Wisconsin": "WI", "Wyoming": "WY",
}
STATE_NAMES = {v: k for k, v in STATE_ABBR.items()}

# Stylised tile-grid US map: abbr -> (row, col) on a 12-column grid.
STATE_GRID = {
    "AK": (0, 0), "ME": (0, 11),
    "VT": (1, 9), "NH": (1, 10),
    "WA": (2, 0), "MT": (2, 1), "ND": (2, 2), "MN": (2, 3), "WI": (2, 4),
    "NY": (2, 8), "MA": (2, 9),
    "OR": (3, 0), "ID": (3, 1), "SD": (3, 2), "IA": (3, 3), "IL": (3, 4),
    "MI": (3, 5), "OH": (3, 7), "PA": (3, 8), "NJ": (3, 9), "CT": (3, 10),
    "RI": (3, 11),
    "CA": (4, 0), "NV": (4, 1), "WY": (4, 2), "NE": (4, 3), "MO": (4, 4),
    "IN": (4, 5), "KY": (4, 6), "WV": (4, 7), "VA": (4, 8), "MD": (4, 9),
    "DE": (4, 10), "DC": (4, 11),
    "UT": (5, 1), "CO": (5, 2), "KS": (5, 3), "TN": (5, 5),
    "NC": (5, 7), "SC": (5, 8), "GA": (5, 9),
    "AZ": (6, 1), "NM": (6, 2), "OK": (6, 3), "AR": (6, 4), "MS": (6, 5),
    "AL": (6, 6), "FL": (6, 8),
    "TX": (7, 3), "LA": (7, 4),
    "HI": (8, 0),
}

# World-map markers for the Global Index: marker key -> (lat, lng).
JURIS_COORDS = {
    "United States": (38.9, -77.0),
    "China": (39.9, 116.4),
    "European Union": (50.85, 4.35),
    "South Korea": (37.57, 126.98),
    "Japan": (35.68, 139.69),
    "Canada": (45.42, -75.7),
    "United Kingdom": (51.5, -0.12),
    "Taiwan": (25.03, 121.57),
    "Brazil": (-15.79, -47.88),
    "Russia": (55.76, 37.62),
    "Vietnam": (21.03, 105.85),
    "Peru": (-12.05, -77.04),
    "Saudi Arabia": (24.63, 46.68),
    "United Arab Emirates": (25.2, 55.27),
}

# Fold sub-jurisdictions into their map marker.
JURIS_FOLD = {
    "United States — Texas": "United States",
    "United States — Connecticut": "United States",
    "United States — Utah": "United States",
    "United States — California": "United States",
    "United States — Illinois": "United States",
    "United States — New York City": "United States",
    "United States — Tennessee": "United States",
    "United States — Colorado": "United States",
    "United States (various states)": "United States",
    "Canada — Quebec": "Canada",
    "United Arab Emirates — Dubai (DIFC)": "United Arab Emirates",
}


def esc(s):
    return html.escape("" if s is None else str(s))


def fetch_json(url, headers=None):
    req = urllib.request.Request(url, headers={**UA, **(headers or {})})
    with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _credential_helpers():
    """Import the secure-credential helpers. None when unavailable (public use)."""
    try:
        import sys
        sys.path.insert(0, "/opt/hatch/skills/skill-creator/bin")
        from dynamic_credentials import (  # noqa: E402
            add_surrogate_to_request, read_json_response,
            url_with_surrogate_query_param)
        return add_surrogate_to_request, read_json_response, url_with_surrogate_query_param
    except ImportError:
        return None


def live_json_congress(url):
    """Fetch a Congress.gov API URL with the stored credential. None if unavailable."""
    helpers = _credential_helpers()
    if helpers is None:
        return None
    _, read_json_response, url_with_surrogate_query_param = helpers
    try:
        authed = url_with_surrogate_query_param(
            url, "custom.congress-gov", allowed_hosts=["api.congress.gov"])
        req = urllib.request.Request(authed, headers=UA)
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
            return read_json_response(resp)
    except Exception:
        return None


def live_json_openstates(url):
    """Fetch an OpenStates API URL with the stored credential. None if unavailable."""
    helpers = _credential_helpers()
    if helpers is None:
        return None
    add_surrogate_to_request, read_json_response, _ = helpers
    try:
        req = urllib.request.Request(url, headers=UA)
        add_surrogate_to_request(
            req, "custom.openstates", allowed_hosts=["v3.openstates.org"])
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
            return read_json_response(resp)
    except Exception:
        return None


def pretty_date(iso):
    """'2026-09-30' -> 'Sep 30, 2026'; pass through anything unparseable."""
    if not iso:
        return "date unknown"
    try:
        return datetime.strptime(iso[:10], "%Y-%m-%d").strftime("%b %d, %Y")
    except ValueError:
        return iso


# ---------------------------------------------------------------- federal bills
BILL_TYPE_SLUGS = {
    "hr": "house-bill", "s": "senate-bill",
    "hjres": "house-joint-resolution", "sjres": "senate-joint-resolution",
    "hconres": "house-concurrent-resolution", "sconres": "senate-concurrent-resolution",
    "hres": "house-resolution", "sres": "senate-resolution",
}


def federal_badge(action_text):
    t = (action_text or "").lower()
    if "became public law" in t or "signed by president" in t:
        return "Enacted"
    if "passed house" in t and "passed senate" in t:
        return "Passed both chambers"
    if "passed house" in t or "passed senate" in t:
        return "Passed chamber"
    if "referred to" in t or "introduced" in t:
        return "Introduced"
    return "Active"


def federal_bills():
    """Returns (items, error). items is None when no key AND no cached data."""
    bills = []
    if CONGRESS_KEY:
        for offset in range(0, FEDERAL_PAGES * 250, 250):
            url = (f"https://api.congress.gov/v3/bill/{CONGRESS}"
                   f"?sort=updateDate+desc&limit=250&offset={offset}"
                   f"&api_key={CONGRESS_KEY}")
            bills.extend(fetch_json(url).get("bills", []))
    else:
        for offset in range(0, FEDERAL_PAGES * 250, 250):
            url = (f"https://api.congress.gov/v3/bill/{CONGRESS}"
                   f"?sort=updateDate+desc&limit=250&offset={offset}")
            data = live_json_congress(url)
            if data is None:
                break
            bills.extend(data.get("bills", []))
    if not bills:
        here = os.path.dirname(os.path.abspath(__file__))
        cache = os.path.join(here, "data", ".congress_cache.json")
        if os.path.exists(cache):
            with open(cache, encoding="utf-8") as f:
                bills = json.load(f).get("bills", [])
    if not bills:
        return None, "needs-key"
    items = []
    for b in bills:
        btype = (b.get("type") or "").lower()
        number = b.get("number", "")
        title = b.get("title", "")
        latest = b.get("latestAction") or {}
        policy = (b.get("policyArea") or {}).get("name", "")
        haystack = " ".join([title, policy, latest.get("text", "")])
        if not AI_RE.search(haystack):
            continue
        slug = BILL_TYPE_SLUGS.get(btype, btype)
        link = f"https://www.congress.gov/bill/{CONGRESS}th-congress/{slug}/{number}"
        sponsors = b.get("sponsors") or []
        sponsor = sponsors[0].get("fullName", "") if sponsors else ""
        items.append({
            "title": f"{btype.upper()} {number} — {title}",
            "badge": federal_badge(latest.get("text", "")),
            "meta": f"Latest action: {latest.get('text', '—')}",
            "date": pretty_date(latest.get("actionDate", "")),
            "extra": f"Sponsor: {sponsor}" if sponsor else "",
            "link": link,
            "search": " ".join([f"{btype} {number}", title, policy,
                                latest.get("text", ""), sponsor]),
        })
        if len(items) >= FEDERAL_CAP:
            break
    return items, None


# ------------------------------------------------------------------- state bills
def state_badge(action_desc):
    t = (action_desc or "").lower()
    if "signed" in t or "enacted" in t or "approved by governor" in t:
        return "Enacted"
    if "passed" in t:
        return "Passed chamber"
    return "Active"


def state_bills():
    """Returns (items, error). items is None when no key AND no cached data."""
    seen = {}
    live = False
    if OPENSTATES_KEY:
        for q in STATE_QUERIES:
            url = (f"https://v3.openstates.org/bills"
                   f"?q={urllib.parse.quote(q)}&per_page=20&sort=updated_desc")
            data = fetch_json(url, headers={"X-API-KEY": OPENSTATES_KEY})
            for b in data.get("results", []):
                seen.setdefault(b.get("id"), b)
        live = True
    else:
        for q in STATE_QUERIES:
            url = (f"https://v3.openstates.org/bills"
                   f"?q={urllib.parse.quote(q)}&per_page=20&sort=updated_desc")
            data = live_json_openstates(url)
            if data is None:
                break
            for b in data.get("results", []):
                seen.setdefault(b.get("id"), b)
            live = True
    if not live:
        here = os.path.dirname(os.path.abspath(__file__))
        cache = os.path.join(here, "data", ".openstates_cache.json")
        if os.path.exists(cache):
            with open(cache, encoding="utf-8") as f:
                for b in json.load(f).get("results", []):
                    seen.setdefault(b.get("id"), b)
    if not seen:
        return None, "needs-key"
    scored = []
    for b in seen.values():
        latest_desc = b.get("latest_action_description", "")
        badge = state_badge(latest_desc)
        juris = (b.get("jurisdiction") or {}).get("name", "")
        boost = 2 if badge == "Enacted" else (1 if badge == "Passed chamber" else 0)
        scored.append((boost, b.get("latest_action_date", ""), {
            "title": f"{b.get('identifier', '')} — {b.get('title', '')}",
            "badge": badge,
            "meta": f"{juris} · {b.get('session', '')}",
            "date": pretty_date(b.get("latest_action_date", "")),
            "extra": f"Latest action: {latest_desc}" if latest_desc else "",
            "link": b.get("openstates_url", "") or "",
            "state": STATE_ABBR.get(juris, ""),
            "search": " ".join([b.get("identifier", ""), b.get("title", ""),
                                juris, b.get("session", ""), latest_desc]),
        }))
    scored.sort(key=lambda s: (s[0], s[1]), reverse=True)
    return [s[2] for s in scored[:STATE_CAP]], None


# --------------------------------------------------------------------- lawsuits
def courtlistener_search(q, rtype, extra=""):
    qenc = urllib.parse.quote(q)
    url = (f"https://www.courtlistener.com/api/rest/v4/search/?q={qenc}"
           f"&type={rtype}&order_by=dateFiled%20desc{extra}")
    return fetch_json(url)


def lawsuits():
    """Returns (items, error). CourtListener search needs no API key."""
    items = []
    dockets = courtlistener_search(
        '"artificial intelligence" (copyright OR deepfake OR chatbot)',
        "r", "&filed_after=2025-04-01")
    for d in (dockets.get("results") or [])[:DOCKET_CAP]:
        badge = "Terminated" if d.get("dateTerminated") else "Filed"
        items.append({
            "title": d.get("caseName", "Untitled case"),
            "badge": badge,
            "kind": "Docket",
            "meta": f"{d.get('court', '')} · Docket {d.get('docketNumber', '')}",
            "date": pretty_date(d.get("dateFiled", "")),
            "extra": "",
            "link": "https://www.courtlistener.com" + (d.get("docket_absolute_url") or ""),
            "search": " ".join([d.get("caseName", ""), d.get("court", ""),
                                d.get("docketNumber", "")]),
        })
    opinions = courtlistener_search('"artificial intelligence"', "o")
    for o in (opinions.get("results") or [])[:OPINION_CAP]:
        items.append({
            "title": o.get("caseName", "Untitled opinion"),
            "badge": "Decided",
            "kind": "Opinion",
            "meta": f"{o.get('court', '')} · {o.get('court_citation_string', '')}",
            "date": pretty_date(o.get("dateFiled", "")),
            "extra": "",
            "link": "https://www.courtlistener.com" + (o.get("absolute_url") or ""),
            "search": " ".join([o.get("caseName", ""), o.get("court", ""),
                                o.get("court_citation_string", "")]),
        })
    return items, None


# --------------------------------------------------------------- global laws
def load_global_raw():
    here = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(here, "data", "global_laws.json")
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def global_laws():
    data = load_global_raw()
    items = []
    for law in data.get("laws", []):
        items.append({
            "title": law.get("name", ""),
            "badge": "Enacted",
            "meta": (f"{law.get('country', '')} · Enacted: {law.get('enacted', '')} "
                     f"· In force: {law.get('in_force', '')}"),
            "date": "",
            "extra": law.get("summary", ""),
            "link": law.get("link", ""),
            "search": " ".join([law.get("name", ""), law.get("country", ""),
                                law.get("summary", "")]),
        })
    for law in data.get("unverified", []):
        missing = law.get("missing", "")
        src = law.get("source_name", "")
        extra = law.get("summary", "")
        extra += f" Best lead so far: {src}." if src else ""
        extra += f" Still needed: {missing}" if missing else ""
        items.append({
            "title": law.get("name", ""),
            "badge": "Unverified",
            "meta": (f"{law.get('country', '')} · Reported — "
                     "NOT yet confirmed against an official source"),
            "date": "",
            "extra": extra,
            "link": law.get("source_url", ""),
            "search": " ".join([law.get("name", ""), law.get("country", ""),
                                law.get("summary", "")]),
        })
    return items, None


def safe_run(fn, label):
    try:
        return fn()
    except Exception as exc:  # one bad source shouldn't kill the run
        print(f"[{label}] skipped ({exc})")
        return [], str(exc)

# ------------------------------------------------------------------ rendering
# Design language: dark editorial data-journalism, after CNAS interactives.
# Spectral (serif) + Montserrat (sans, tracked uppercase labels),
# #34a3d7 blue accent, #d74b17 orange data encoding on dark maps.

SITE_CSS = """
:root{
  --blue:#34a3d7; --magenta:#c71585; --orange:#d74b17;
  --ink:#ffffff; --muted:#a9b6c7; --line:rgba(255,255,255,.14);
  --card:#ffffff; --ctext:#101418;
}
*{box-sizing:border-box}
html{scroll-behavior:smooth}
body{margin:0;color:var(--ink);font-family:'Spectral',Georgia,'Times New Roman',serif;
  background:#000 linear-gradient(180deg,#000 0%,#000 18%,#222844 90%) fixed;}
.sans{font-family:'Montserrat',-apple-system,'Segoe UI',sans-serif}
.wrap{max-width:1180px;margin:0 auto;padding:0 1.5rem}
.eyebrow{font-family:'Montserrat',sans-serif;font-weight:600;font-size:.78rem;
  letter-spacing:.28em;text-transform:uppercase;color:var(--blue)}
/* ---- nav ---- */
#progress{position:fixed;top:0;left:0;height:3px;background:var(--blue);width:0;z-index:99}
.nav{position:fixed;top:0;left:0;right:0;z-index:60;display:flex;align-items:center;
  justify-content:space-between;padding:1.05rem 1.6rem;transition:background .25s,box-shadow .25s}
.nav.scrolled{background:#000;box-shadow:0 2px 18px rgba(0,0,0,.55)}
.brand{font-family:'Montserrat',sans-serif;font-weight:800;font-size:.92rem;
  letter-spacing:.2em;color:#fff;text-decoration:none}
.brand b{color:var(--blue);font-weight:800}
.navlinks{display:flex;gap:1.5rem;align-items:center}
.navlinks a{font-family:'Montserrat',sans-serif;font-weight:600;font-size:.76rem;
  letter-spacing:.16em;color:#fff;text-decoration:none;opacity:.72;text-transform:uppercase}
.navlinks a:hover{opacity:1}
.navlinks a.active{opacity:1;color:var(--blue)}
@media(max-width:720px){.navlinks{gap:.9rem}.navlinks a{font-size:.66rem;letter-spacing:.1em}}
/* ---- hero ---- */
.hero{position:relative;min-height:100vh;display:flex;align-items:center;
  justify-content:center;text-align:center;overflow:hidden}
.hero.short{min-height:52vh}
#heroMap{position:absolute;inset:0;z-index:0;background:#020608}
.hero::after{content:'';position:absolute;inset:0;z-index:1;pointer-events:none;
  background:linear-gradient(180deg,rgba(0,0,0,.62) 0%,rgba(0,0,0,.28) 42%,rgba(0,0,0,.88) 96%)}
.hero-inner{position:relative;z-index:2;max-width:920px;padding:7rem 1.5rem 4rem}
.hero h1{font-weight:400;font-size:clamp(2.9rem,7.5vw,5.9rem);line-height:1.04;
  margin:1.1rem 0;letter-spacing:-.01em}
.hero .sub{font-family:'Montserrat',sans-serif;font-weight:300;font-size:1.08rem;
  color:#dfe6f0;max-width:62ch;margin:0 auto;line-height:1.65}
.scrollcue{position:absolute;bottom:1.6rem;left:50%;transform:translateX(-50%);z-index:2;
  font-family:'Montserrat',sans-serif;font-size:.68rem;letter-spacing:.3em;color:var(--muted);
  text-transform:uppercase;animation:bob 2.4s ease-in-out infinite}
@keyframes bob{0%,100%{transform:translate(-50%,0);opacity:.7}50%{transform:translate(-50%,10px);opacity:1}}
/* pulsing map dots */
.pdot{position:relative;display:block;border-radius:50%;background:var(--orange);
  box-shadow:0 0 14px 4px rgba(215,75,23,.75)}
.pdot::after{content:'';position:absolute;inset:-9px;border-radius:50%;
  border:2px solid rgba(215,75,23,.55);animation:ping 2.4s ease-out infinite}
.pdot.hollow{background:transparent;box-shadow:none;border:2px dashed rgba(215,75,23,.9)}
.pdot.hollow::after{border-color:rgba(215,75,23,.35)}
@keyframes ping{0%{transform:scale(.45);opacity:1}100%{transform:scale(1.35);opacity:0}}
/* ---- stats ---- */
.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:1px;
  background:var(--line);border-top:1px solid var(--line);border-bottom:1px solid var(--line)}
.stat{background:rgba(0,0,0,.42);padding:1.7rem 1.2rem;text-align:center}
.stat .num{font-size:2.7rem;font-weight:400;color:#fff}
.stat .num em{font-style:normal;color:var(--blue)}
.stat .lbl{font-family:'Montserrat',sans-serif;font-weight:600;font-size:.7rem;
  letter-spacing:.22em;color:var(--muted);text-transform:uppercase;margin-top:.45rem}
/* ---- sections ---- */
.sec{padding:5.2rem 0 1rem}
.sec-head{max-width:720px;margin-bottom:2.2rem}
.sec-head h2{font-weight:400;font-size:clamp(1.9rem,3.6vw,2.7rem);margin:.7rem 0 .8rem}
.sec-head p{color:var(--muted);font-size:1.06rem;line-height:1.65;margin:0}
.sec-head p a{color:var(--blue)}
.glyph{width:34px;height:20px;margin-bottom:.4rem}
/* ---- white index cards (home) ---- */
.cards3{display:grid;grid-template-columns:repeat(auto-fit,minmax(290px,1fr));gap:1.2rem}
.wcard{background:#fff;color:var(--ctext);border-radius:6px;overflow:hidden;
  display:flex;flex-direction:column;text-decoration:none;transition:transform .18s,box-shadow .18s}
.wcard:hover{transform:translateY(-4px);box-shadow:0 18px 44px rgba(0,0,0,.5)}
.wcard .banner{padding:.72rem 1.3rem;font-family:'Montserrat',sans-serif;font-weight:700;
  font-size:.7rem;letter-spacing:.22em;text-transform:uppercase;color:#000}
.wcard .body{padding:1.5rem 1.4rem 1.3rem;flex:1}
.wcard h3{font-family:'Montserrat',sans-serif;font-weight:700;font-size:1.32rem;
  margin:0 0 .55rem;color:#000}
.wcard .body p{font-size:1rem;color:#33373d;line-height:1.6;margin:0 0 1.1rem}
.wcard .go{font-family:'Montserrat',sans-serif;font-weight:700;font-size:.76rem;
  letter-spacing:.18em;color:var(--blue);text-transform:uppercase}
.wcard .go:hover{text-decoration:underline}
/* ---- filter bar (CNAS explorer style) ---- */
.fbar{display:flex;gap:.7rem;flex-wrap:wrap;align-items:center;margin:1.6rem 0 1.8rem}
.fbar select{background:transparent;color:#fff;border:1px solid rgba(255,255,255,.55);
  border-radius:4px;padding:.62rem .8rem;font-family:'Montserrat',sans-serif;
  font-weight:600;font-size:.76rem;letter-spacing:.1em;text-transform:uppercase;cursor:pointer}
.fbar select:hover{border-color:var(--blue)}
.fbar select option{color:#000;text-transform:none;letter-spacing:0}
.fsearch{flex:1;min-width:200px;background:transparent;border:none;
  border-bottom:1px solid rgba(255,255,255,.55);color:#fff;padding:.62rem .2rem;font-size:1.02rem}
.fsearch::placeholder{color:#8b96a8}
.fsearch:focus{outline:none;border-bottom-color:var(--blue)}
.fcount{margin-left:auto;font-family:'Montserrat',sans-serif;font-weight:600;
  font-size:.78rem;letter-spacing:.14em;color:var(--muted);text-transform:uppercase}
/* ---- white data cards ---- */
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(330px,1fr));gap:1rem}
.bcard{background:#fff;color:#111;border-radius:6px;padding:1.35rem 1.4rem;
  display:flex;flex-direction:column}
.badge{align-self:flex-start;font-family:'Montserrat',sans-serif;font-weight:700;
  font-size:.64rem;letter-spacing:.14em;text-transform:uppercase;color:#fff;
  border-radius:999px;padding:.3rem .72rem;margin-bottom:.75rem}
.b-green{background:#1a7f37}.b-amber{background:#b45309}.b-blue{background:#0969da}
.b-gray{background:#57606a}.b-gold{background:#9a6700}.b-orange{background:#cf5016}
.b-purple{background:#8250df}
.bcard h3{font-family:'Montserrat',sans-serif;font-weight:700;font-size:1rem;
  line-height:1.42;margin:0 0 .45rem;color:#000}
.bcard h3 a{color:#000;text-decoration:none}
.bcard h3 a:hover{color:var(--blue);text-decoration:underline}
.bcard .meta{font-family:'Montserrat',sans-serif;font-weight:600;font-size:.76rem;
  color:#5b6572;margin:0 0 .5rem;line-height:1.5}
.bcard .txt{font-size:.94rem;color:#2a3138;line-height:1.58;margin:0}
.bcard .foot{margin-top:auto;padding-top:1rem}
.offlink{font-family:'Montserrat',sans-serif;font-weight:700;font-size:.72rem;
  letter-spacing:.16em;color:var(--blue);text-decoration:none;text-transform:uppercase}
.offlink:hover{text-decoration:underline}
/* ---- map + side panel ---- */
.mapsec{position:relative;margin:1rem 0 3rem}
#map{height:600px;background:#07141d;border:1px solid var(--line);border-radius:8px;z-index:1}
.leaflet-container{font-family:'Montserrat',sans-serif}
.maplegend{position:absolute;left:14px;bottom:14px;z-index:500;background:rgba(0,0,0,.82);
  border:1px solid var(--line);border-radius:6px;padding:.8rem 1rem;color:#fff}
.maplegend h4{font-family:'Montserrat',sans-serif;font-weight:600;font-size:.68rem;
  letter-spacing:.18em;text-transform:uppercase;margin:0 0 .55rem;color:#fff}
.maplegend .row{display:flex;align-items:center;gap:.55rem;
  font-family:'Montserrat',sans-serif;font-size:.72rem;color:var(--muted);margin:.3rem 0}
.sw{width:22px;height:12px;border-radius:2px;background:var(--orange)}
.panel{position:absolute;top:0;right:0;bottom:0;width:min(430px,94%);background:#fff;
  color:#111;z-index:600;transform:translateX(106%);transition:transform .35s ease;
  overflow-y:auto;padding:1.7rem 1.6rem;box-shadow:-14px 0 44px rgba(0,0,0,.5);
  border-radius:0 8px 8px 0}
.panel.open{transform:none}
.panel .xrow{display:flex;justify-content:space-between;align-items:center}
.panel .reset{font-family:'Montserrat',sans-serif;font-weight:700;font-size:.7rem;
  letter-spacing:.16em;color:#2c5d75;text-decoration:none;text-transform:uppercase;cursor:pointer}
.panel .reset:hover{text-decoration:underline}
.panel h3{font-family:'Montserrat',sans-serif;font-weight:700;font-size:1.45rem;
  margin:.5rem 0 .2rem;color:#000}
.panel .rule{height:3px;background:#000;width:66px;margin:.65rem 0 1rem}
.pill{display:inline-block;border:1px solid #000;border-radius:999px;padding:.28rem .75rem;
  font-family:'Montserrat',sans-serif;font-weight:600;font-size:.66rem;letter-spacing:.16em;
  text-transform:uppercase;color:#000;margin:0 .4rem .6rem 0}
.plaw{border-top:1px solid #e3e6ea;padding:.95rem 0}
.plaw h4{font-family:'Montserrat',sans-serif;font-weight:700;font-size:.98rem;
  margin:0 0 .3rem;color:#000;line-height:1.4}
.plaw h4 a{color:#000;text-decoration:none}
.plaw h4 a:hover{color:var(--blue);text-decoration:underline}
.plaw .sub2{font-family:'Montserrat',sans-serif;font-size:.72rem;font-weight:600;
  color:#5b6572;margin:0 0 .35rem}
.plaw p{font-size:.9rem;color:#33373d;margin:0;line-height:1.55}
/* ---- tile grid US map ---- */
.tilegrid{display:grid;grid-template-columns:repeat(12,1fr);gap:6px;max-width:780px;margin:0 auto}
.tile{aspect-ratio:1/.92;border-radius:6px;border:1px solid rgba(255,255,255,.22);
  background:rgba(255,255,255,.045);color:#fff;font-family:'Montserrat',sans-serif;
  font-weight:700;font-size:.72rem;display:flex;flex-direction:column;align-items:center;
  justify-content:center;cursor:default;line-height:1.25}
.tile .n{font-size:.62rem;font-weight:600;color:#cdd6e2}
.tile.has{cursor:pointer;border-color:var(--blue)}
.tile.has:hover{transform:scale(1.1);z-index:2}
@media(max-width:640px){.tile{font-size:.58rem}.tile .n{display:none}}
/* ---- status bars ---- */
.bars{max-width:760px;margin:1.6rem 0 2.4rem}
.barrow{margin:.65rem 0}
.barrow .t{display:flex;justify-content:space-between;font-family:'Montserrat',sans-serif;
  font-weight:600;font-size:.74rem;letter-spacing:.16em;text-transform:uppercase;
  color:var(--muted);margin-bottom:.35rem}
.barrow .t b{color:#fff}
.barrow .track{height:14px;background:rgba(255,255,255,.1);border-radius:7px;overflow:hidden}
.barrow .fill{height:100%;border-radius:7px;background:#5d8aa0;transition:width 1s ease}
/* ---- misc ---- */
.empty{display:none;text-align:center;color:var(--muted);padding:3.5rem 1rem}
.empty h3{color:#fff;font-weight:400;font-size:1.6rem}
.notice{background:rgba(255,255,255,.06);border:1px solid var(--line);
  border-left:4px solid #d4a017;border-radius:8px;padding:.9rem 1.1rem;font-size:.95rem;color:#dfe6f0}
.notice a{color:var(--blue)}
.kv{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:1rem;margin:2rem 0}
.kv .k{background:rgba(255,255,255,.045);border:1px solid var(--line);border-radius:8px;
  padding:1.2rem 1.3rem}
.kv .k h4{font-family:'Montserrat',sans-serif;font-weight:700;font-size:.74rem;
  letter-spacing:.2em;text-transform:uppercase;color:var(--blue);margin:0 0 .5rem}
.kv .k p{margin:0;color:#c9d2e0;font-size:.96rem;line-height:1.6}
footer{margin-top:5rem}
.fband{background:#222844;border-top:1px solid #fff;padding:3rem 0 2.2rem}
.fcols{display:grid;grid-template-columns:1.4fr 1fr 1fr;gap:2rem}
@media(max-width:760px){.fcols{grid-template-columns:1fr}}
.fcols h5{font-family:'Montserrat',sans-serif;font-weight:700;font-size:.72rem;
  letter-spacing:.22em;text-transform:uppercase;color:#fff;margin:0 0 .9rem}
.fcols p,.fcols li{font-size:.95rem;color:#c9d2e0;line-height:1.65}
.fcols ul{list-style:none;margin:0;padding:0}
.fcols li{margin:.4rem 0}
.fcols a{color:#fff;text-decoration:none;border-bottom:1px solid var(--blue)}
.fcols a:hover{color:var(--blue)}
.fbottom{background:#000;padding:1.1rem 0;display:flex;justify-content:space-between;
  align-items:center;gap:1rem;flex-wrap:wrap}
.fbottom small{font-family:'Montserrat',sans-serif;font-size:.72rem;color:#8b96a8;letter-spacing:.06em}
.reveal{opacity:0;transform:translateY(26px);transition:opacity .7s ease,transform .7s ease}
.reveal.in{opacity:1;transform:none}
"""

BASE_HEAD = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>%%TITLE%%</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Montserrat:wght@300;400;600;700;800&family=Spectral:ital,wght@0,300;0,400;0,600;1,400&display=swap" rel="stylesheet">
%%EXTRA_HEAD%%
<style>%%CSS%%</style>
</head>
"""

NAV_ITEMS = [
    ("index.html", "Home"),
    ("us-laws.html", "US Laws"),
    ("litigation.html", "Litigation"),
    ("global.html", "Global Index"),
]

CORE_JS = """
<script>
(function(){
  var nav=document.getElementById('nav'), prog=document.getElementById('progress');
  function onScroll(){
    nav.classList.toggle('scrolled', window.scrollY>40);
    var h=document.documentElement, p=h.scrollTop/(h.scrollHeight-h.clientHeight||1);
    prog.style.width=(p*100)+'%';
  }
  window.addEventListener('scroll', onScroll, {passive:true}); onScroll();
  var io=new IntersectionObserver(function(es){es.forEach(function(e){
    if(e.isIntersecting){e.target.classList.add('in');io.unobserve(e.target);}});},{threshold:.12});
  document.querySelectorAll('.reveal').forEach(function(el){io.observe(el);});
  document.querySelectorAll('[data-count]').forEach(function(el){
    var target=parseInt(el.getAttribute('data-count'),10), t0=null;
    function step(ts){ if(!t0)t0=ts; var k=Math.min(1,(ts-t0)/1100);
      el.textContent=Math.round(target*(1-Math.pow(1-k,3))); if(k<1)requestAnimationFrame(step); }
    var io2=new IntersectionObserver(function(es){es.forEach(function(e){
      if(e.isIntersecting){requestAnimationFrame(step);io2.disconnect();}});});
    io2.observe(el);
  });
  // generic explorer filter: [data-explorer] wraps cards with data-search/data-badge/data-kind
  document.querySelectorAll('[data-explorer]').forEach(function(root){
    var q=root.querySelector('[data-f=q]'),
        badge=root.querySelector('[data-f=badge]'),
        kind=root.querySelector('[data-f=kind]'),
        count=root.querySelector('[data-f=count]'),
        empty=root.querySelector('[data-f=empty]'),
        cards=Array.prototype.slice.call(root.querySelectorAll('[data-card]')),
        total=cards.length;
    function apply(){
      var s=q?q.value.trim().toLowerCase():'', b=badge?badge.value:'',
          k=kind?kind.value:'', shown=0;
      cards.forEach(function(c){
        var ok=(!s||c.getAttribute('data-search').indexOf(s)!==-1)
          &&(!b||c.getAttribute('data-badge')===b)
          &&(!k||c.getAttribute('data-kind')===k);
        c.style.display=ok?'':'none'; if(ok)shown++;
      });
      if(count)count.textContent='Showing '+shown+' of '+total;
      if(empty)empty.style.display=shown===0?'':'none';
    }
    [q,badge,kind].forEach(function(el){if(el)el.addEventListener('input',apply);if(el)el.addEventListener('change',apply);});
    apply();
  });
})();
</script>
"""

FOOTER_HTML = """
<footer>
  <div class="fband"><div class="wrap"><div class="fcols">
    <div>
      <h5>About this tracker</h5>
      <p>A public index of artificial-intelligence law and litigation: US federal
      and state bills, AI lawsuits in federal court, and enacted AI laws worldwide.
      Every enacted law is verified against an official government source; reported
      laws that cannot be confirmed are marked <b>Unverified</b> and kept out of the
      enacted count.</p>
    </div>
    <div>
      <h5>Index</h5>
      <ul>
        <li><a href="index.html">Home</a></li>
        <li><a href="us-laws.html">US AI Law Tracker</a></li>
        <li><a href="litigation.html">AI Litigation Monitor</a></li>
        <li><a href="global.html">Global AI Regulation Index</a></li>
      </ul>
    </div>
    <div>
      <h5>Sources</h5>
      <ul>
        <li><a href="https://www.congress.gov">Congress.gov</a> — federal bills</li>
        <li><a href="https://openstates.org">OpenStates</a> — state bills</li>
        <li><a href="https://www.courtlistener.com">CourtListener</a> — lawsuits</li>
        <li>Official gazettes &amp; agency sites — enacted laws</li>
      </ul>
    </div>
  </div></div></div>
  <div class="fbottom"><div class="wrap" style="display:flex;justify-content:space-between;flex-wrap:wrap;gap:1rem;width:100%">
    <small>AI REGULATION TRACKER · UPDATED %%DATE%%</small>
    <small>CODE &amp; CURATION NOTES ON <a href="https://github.com/trishabinwade/ai-regulation-tracker" style="color:#fff">GITHUB</a></small>
  </div></div>
</footer>
"""


def base_page(title, active, body_html, extra_head="", extra_scripts="", updated=""):
    nav = "".join(
        f'<a href="{href}" class="{ "active" if href == active else ""}">{label}</a>'
        for href, label in NAV_ITEMS
    )
    head = (BASE_HEAD.replace("%%TITLE%%", esc(title))
                     .replace("%%CSS%%", SITE_CSS)
                     .replace("%%EXTRA_HEAD%%", extra_head))
    footer = FOOTER_HTML.replace("%%DATE%%", esc(updated))
    return f"""{head}
<body>
<div id="progress"></div>
<nav class="nav" id="nav">
  <a class="brand" href="index.html">AI<b>·</b>REGULATION<b>·</b>TRACKER</a>
  <div class="navlinks">{nav}</div>
</nav>
{body_html}
{footer}
{CORE_JS}
{extra_scripts}
</body>
</html>
"""


def badge_class(badge):
    return {
        "Enacted": "b-green", "Unverified": "b-amber",
        "Passed both chambers": "b-green", "Passed chamber": "b-gold",
        "Introduced": "b-gray", "Active": "b-blue",
        "Filed": "b-orange", "Terminated": "b-gray", "Decided": "b-purple",
    }.get(badge, "b-gray")


def glyph(color="#34a3d7"):
    return f"""<svg class="glyph" viewBox="0 0 34 20" fill="none" aria-hidden="true">
<path d="M2 18 A 16 16 0 0 1 32 18" stroke="{color}" stroke-width="2.5"/></svg>"""


def explorer_bar(statuses, kinds=None, search_ph="Search…"):
    opts = "".join(f'<option value="{esc(s)}">{esc(s)}</option>' for s in statuses)
    kind_sel = ""
    if kinds:
        kopts = "".join(f'<option value="{esc(k)}">{esc(k)}</option>' for k in kinds)
        kind_sel = f'<select data-f="kind" aria-label="Filter by type"><option value="">All types</option>{kopts}</select>'
    return f"""
    <div class="fbar">
      <input class="fsearch" data-f="q" type="search" placeholder="{esc(search_ph)}" aria-label="Search">
      {kind_sel}
      <select data-f="badge" aria-label="Filter by status"><option value="">All statuses</option>{opts}</select>
      <span class="fcount" data-f="count"></span>
    </div>"""


def data_card(item, kind=""):
    date_line = f" · {esc(item['date'])}" if item.get("date") else ""
    extra = f'<p class="txt">{esc(item["extra"])}</p>' if item.get("extra") else ""
    link = item.get("link") or ""
    title = (f'<h3><a href="{esc(link)}" target="_blank" rel="noopener">{esc(item["title"])}</a></h3>'
             if link else f'<h3>{esc(item["title"])}</h3>')
    offlink = (f'<div class="foot"><a class="offlink" href="{esc(link)}" target="_blank" '
               f'rel="noopener">View official text &#8599;</a></div>' if link else "")
    return f"""
    <article class="bcard" data-card data-badge="{esc(item['badge'])}" data-kind="{esc(kind)}"
             data-search="{esc(item.get('search', '').lower())}">
      <span class="badge {badge_class(item['badge'])}">{esc(item['badge'])}</span>
      {title}
      <p class="meta">{esc(item['meta'])}{date_line}</p>
      {extra}
      {offlink}
    </article>"""


def notice_block(msg):
    return f'<div class="notice"><p>{msg}</p></div>'


# ------------------------------------------------------------ home page
def render_home(fed, st, suits, verified_n, unverified_n, updated):
    hero_markers = [
        {"lat": lat, "lng": lng, "n": n, "hollow": hollow}
        for lat, lng, n, hollow in [
            (38.9, -77.0, 12, False), (39.9, 116.4, 4, False),
            (50.85, 4.35, 3, False), (37.57, 126.98, 1, False),
            (35.68, 139.69, 1, False), (45.42, -75.7, 1, False),
            (51.5, -0.12, 1, False), (25.03, 121.57, 0, True),
            (-15.79, -47.88, 0, True), (55.76, 37.62, 0, True),
            (21.03, 105.85, 0, True), (-12.05, -77.04, 0, True),
            (24.63, 46.68, 0, True), (25.2, 55.27, 0, True),
        ]
    ]
    cards = [
        ("#98d2ea", "US AI Law Tracker",
         "Every AI bill moving through Congress and the state legislatures — "
         "searchable, filterable, and mapped state by state.",
         "us-laws.html", "Explore US laws"),
        ("#d2a3ce", "AI Litigation Monitor",
         "Federal dockets and published opinions where artificial intelligence "
         "is at issue — copyright, deepfakes, chatbots and beyond.",
         "litigation.html", "Follow the cases"),
        ("#bacbd3", "Global AI Regulation Index",
         "The world's enacted AI laws, each verified against an official "
         "government source — on a clickable world map.",
         "global.html", "See the world"),
    ]
    cards_html = "".join(f"""
      <a class="wcard reveal" href="{href}">
        <div class="banner" style="background:{color}">{esc(title)}</div>
        <div class="body"><h3>{esc(title)}</h3><p>{esc(desc)}</p>
        <span class="go">{esc(go)} &#8594;</span></div>
      </a>""" for color, title, desc, href, go in cards)

    body = f"""
<header class="hero">
  <div id="heroMap"></div>
  <div class="hero-inner">
    <div class="eyebrow reveal">Tracking AI law &amp; policy</div>
    <h1 class="reveal">AI Regulation Tracker</h1>
    <p class="sub reveal">US federal and state AI bills &middot; AI lawsuits in federal
    court &middot; enacted AI laws worldwide — each one verified against an official
    government source.</p>
  </div>
  <div class="scrollcue">Scroll</div>
</header>

<div class="stats">
  <div class="stat"><div class="num"><span data-count="{len(fed) if fed else 0}">0</span></div>
    <div class="lbl">Federal bills</div></div>
  <div class="stat"><div class="num"><span data-count="{len(st) if st else 0}">0</span></div>
    <div class="lbl">State bills</div></div>
  <div class="stat"><div class="num"><span data-count="{len(suits) if suits else 0}">0</span></div>
    <div class="lbl">Lawsuits</div></div>
  <div class="stat"><div class="num"><span data-count="{verified_n}">0</span><em>+{unverified_n}</em></div>
    <div class="lbl">Enacted laws <span style="letter-spacing:.1em">(blue: awaiting verification)</span></div></div>
</div>

<section class="sec"><div class="wrap">
  <div class="sec-head reveal">{glyph()}
    <div class="eyebrow">The index</div>
    <h2>Three lenses on AI governance</h2>
    <p>Legislation still moving, cases testing the boundaries, and the laws already
    in force — pick a lens.</p>
  </div>
  <div class="cards3">{cards_html}</div>
</div></section>

<section class="sec"><div class="wrap">
  <div class="sec-head reveal">{glyph("#c71585")}
    <div class="eyebrow">Method</div>
    <h2>How the tracker works</h2>
  </div>
  <div class="kv">
    <div class="k reveal"><h4>Live legislation</h4><p>Federal bills via the Congress.gov
    API; state bills via OpenStates — refreshed every build, newest action first.</p></div>
    <div class="k reveal"><h4>Real litigation</h4><p>Federal dockets and published
    opinions from CourtListener's free database. No headlines, no punditry.</p></div>
    <div class="k reveal"><h4>Verified enactments</h4><p>A law is listed as enacted only
    when confirmed against an official government source. Convincing but unconfirmed
    candidates are flagged <b>Unverified</b> and excluded from the count.</p></div>
  </div>
</div></section>
"""
    extra_head = """
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>"""
    extra_scripts = f"""
<script>
(function(){{
  try{{
    var map=L.map('heroMap',{{zoomControl:false,attributionControl:false,
      dragging:false,scrollWheelZoom:false,doubleClickZoom:false,boxZoom:false,
      keyboard:false,tap:false}}).setView([28,8],2);
    L.tileLayer('https://{{s}}.basemaps.cartocdn.com/dark_all/{{z}}/{{x}}/{{y}}{{r}}.png',
      {{maxZoom:4}}).addTo(map);
    var pts={json.dumps(hero_markers)};
    pts.forEach(function(p){{
      var s=p.hollow?10:10+Math.min(p.n,12)*1.6;
      L.marker([p.lat,p.lng],{{interactive:false,keyboard:false}},
        {{icon:L.divIcon({{className:'',html:'<span class="pdot'+(p.hollow?' hollow':'')+'" style="width:'+s+'px;height:'+s+'px"></span>',iconSize:[s,s],iconAnchor:[s/2,s/2]}})}}).addTo(map);
    }});
  }}catch(e){{document.getElementById('heroMap').style.background=
    'radial-gradient(ellipse at 30% 20%,#1b2b4a 0%,#000 60%)';}}
}})();
</script>"""
    return base_page("AI Regulation Tracker", "index.html", body,
                      extra_head, extra_scripts, updated)

# ------------------------------------------------------------ US laws page
def render_us_laws(fed, fed_err, st, st_err, updated):
    # group state bills by abbreviation
    by_state = {}
    for item in (st or []):
        abbr = item.get("state", "")
        if abbr:
            by_state.setdefault(abbr, []).append(item)

    # tile grid
    max_n = max([len(v) for v in by_state.values()] or [1])
    tiles = []
    for abbr, (r, c) in STATE_GRID.items():
        n = len(by_state.get(abbr, []))
        if n:
            op = 0.25 + 0.75 * (n / max_n)
            tiles.append(
                f'<button class="tile has" data-state="{abbr}" '
                f'style="grid-row:{r + 1};grid-column:{c + 1};'
                f'background:rgba(52,163,215,{op:.2f})" '
                f'aria-label="{esc(STATE_NAMES.get(abbr, abbr))}: {n} bills">'
                f'{abbr}<span class="n">{n}</span></button>')
        else:
            tiles.append(
                f'<div class="tile" style="grid-row:{r + 1};grid-column:{c + 1}" '
                f'aria-hidden="true">{abbr}</div>')
    state_panel_data = {
        abbr: [{"title": i["title"], "badge": i["badge"], "meta": i["meta"],
                "date": i["date"], "extra": i["extra"], "link": i["link"]}
               for i in items]
        for abbr, items in by_state.items()
    }

    if fed_err == "needs-key":
        fed_body = notice_block(
            'Federal bills need a free Congress.gov API key at build time. '
            'State coverage below is unaffected.')
    elif fed_err or not fed:
        fed_body = notice_block(
            'Could not load federal bills this run — the source may be down or rate-limited.')
    else:
        statuses = sorted({i["badge"] for i in fed})
        cards = "".join(data_card(i) for i in fed)
        fed_body = f"""
        <div data-explorer>
          {explorer_bar(statuses, search_ph="Search federal bills…")}
          <div class="grid">{cards}</div>
          <div class="empty" data-f="empty"><h3>No matches</h3>
            <p>Try a different search term or clear the filters.</p></div>
        </div>"""

    if st_err == "needs-key":
        st_body = notice_block(
            'State bills need a free OpenStates API key at build time.')
    elif st_err or not st:
        st_body = notice_block(
            'Could not load state bills this run — the source may be down or rate-limited.')
    else:
        state_opts = "".join(
            f'<option value="{abbr}">{esc(STATE_NAMES.get(abbr, abbr))}</option>'
            for abbr in sorted(by_state))
        statuses = sorted({i["badge"] for i in st})
        cards = "".join(
            data_card(dict(i, ), kind=i.get("state", "")) for i in st)
        st_body = f"""
        <div data-explorer>
          <div class="fbar">
            <input class="fsearch" data-f="q" type="search"
                   placeholder="Search state bills…" aria-label="Search">
            <select data-f="kind" aria-label="Filter by state">
              <option value="">All states</option>{state_opts}</select>
            <select data-f="badge" aria-label="Filter by status">
              <option value="">All statuses</option>
              {"".join(f'<option value="{esc(s)}">{esc(s)}</option>' for s in statuses)}</select>
            <span class="fcount" data-f="count"></span>
          </div>
          <div class="grid">{cards}</div>
          <div class="empty" data-f="empty"><h3>No matches</h3>
            <p>Try a different search term or clear the filters.</p></div>
        </div>"""

    body = f"""
<header class="hero short">
  <div class="hero-inner">
    <div class="eyebrow reveal">United States</div>
    <h1 class="reveal">US AI Law Tracker</h1>
    <p class="sub reveal">Every AI bill moving through the 119th Congress and the state
    legislatures — newest action first. Click a state to see its bills.</p>
  </div>
</header>

<section class="sec" style="padding-top:2.5rem"><div class="wrap">
  <div class="sec-head reveal">{glyph()}
    <div class="eyebrow">By state</div>
    <h2>The state map</h2>
    <p>Darker states have more AI bills in this build's coverage. Select a state to
    browse its bills.</p>
  </div>
  <div class="mapsec reveal">
    <div class="tilegrid" id="tilegrid" role="list">{''.join(tiles)}</div>
    <aside class="panel" id="statePanel" aria-label="State bills">
      <div class="xrow"><span class="reset" id="statePanelClose">&#8592; All states</span></div>
      <h3 id="statePanelTitle"></h3><div class="rule"></div>
      <div id="statePanelBody"></div>
    </aside>
  </div>
</div></section>

<section class="sec"><div class="wrap">
  <div class="sec-head reveal">{glyph()}
    <div class="eyebrow">119th Congress</div>
    <h2>Federal bills</h2>
    <p>AI-related bills in the current Congress, drawn from the 1,000 most recently
    updated bills via Congress.gov.</p>
  </div>
  {fed_body}
</div></section>

<section class="sec"><div class="wrap">
  <div class="sec-head reveal">{glyph("#c71585")}
    <div class="eyebrow">Fifty states</div>
    <h2>State bills</h2>
    <p>AI bills across all state legislatures via OpenStates full-text search.
    Enacted and recently-active bills first.</p>
  </div>
  {st_body}
</div></section>
"""
    extra_scripts = f"""
<script>
(function(){{
  var data={json.dumps(state_panel_data)};
  var names={json.dumps(STATE_NAMES)};
  var panel=document.getElementById('statePanel'),
      title=document.getElementById('statePanelTitle'),
      body=document.getElementById('statePanelBody');
  function esc(s){{return String(s).replace(/[&<>"]/g,function(c){{
    return {{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}}[c];}});}}
  document.getElementById('tilegrid').addEventListener('click',function(e){{
    var t=e.target.closest('.tile.has'); if(!t)return;
    var abbr=t.getAttribute('data-state'), items=data[abbr]||[];
    title.textContent=(names[abbr]||abbr)+' — '+items.length+' bill'+(items.length===1?'':'s');
    body.innerHTML=items.map(function(i){{
      return '<div class="plaw"><h4>'+(i.link
        ? '<a href="'+esc(i.link)+'" target="_blank" rel="noopener">'+esc(i.title)+'</a>'
        : esc(i.title))+'</h4>'
        +'<p class="sub2">'+esc(i.badge)+' · '+esc(i.meta)+(i.date?' · '+esc(i.date):'')+'</p>'
        +(i.extra?'<p>'+esc(i.extra)+'</p>':'')+'</div>';
    }}).join('');
    panel.classList.add('open');
    panel.scrollTop=0;
  }});
  document.getElementById('statePanelClose').addEventListener('click',function(){{
    panel.classList.remove('open');
  }});
}})();
</script>"""
    return base_page("US AI Law Tracker", "us-laws.html", body,
                      extra_scripts=extra_scripts, updated=updated)


# ------------------------------------------------------------ litigation page
def render_litigation(suits, suits_err, updated):
    if suits_err or not suits:
        body_inner = notice_block(
            'Could not load lawsuits this run — the source may be down or rate-limited. '
            'Re-run later.')
        bars = ""
    else:
        counts = {"Filed": 0, "Terminated": 0, "Decided": 0}
        for i in suits:
            if i["badge"] in counts:
                counts[i["badge"]] += 1
        total = sum(counts.values()) or 1
        bars = '<div class="bars">' + "".join(f"""
          <div class="barrow"><div class="t"><span>{k}</span><b>{v}</b></div>
          <div class="track"><div class="fill" style="width:{100.0 * v / total:.1f}%"></div></div></div>"""
            for k, v in counts.items()) + "</div>"
        statuses = sorted({i["badge"] for i in suits})
        kinds = sorted({i["kind"] for i in suits})
        cards = "".join(data_card(i, kind=i["kind"]) for i in suits)
        body_inner = f"""
        <div data-explorer>
          {explorer_bar(statuses, kinds=kinds, search_ph="Search cases…")}
          <div class="grid">{cards}</div>
          <div class="empty" data-f="empty"><h3>No matches</h3>
            <p>Try a different search term or clear the filters.</p></div>
        </div>"""

    body = f"""
<header class="hero short">
  <div class="hero-inner">
    <div class="eyebrow reveal">Courts</div>
    <h1 class="reveal">AI Litigation Monitor</h1>
    <p class="sub reveal">Federal cases where artificial intelligence is at issue —
    copyright, deepfakes, chatbots. Dockets filed since April 2025 plus the newest
    published opinions.</p>
  </div>
</header>

<section class="sec" style="padding-top:2.5rem"><div class="wrap">
  <div class="sec-head reveal">{glyph()}
    <div class="eyebrow">This build</div>
    <h2>Cases by status</h2>
  </div>
  {bars}
  <div class="sec-head reveal">{glyph("#c71585")}
    <div class="eyebrow">The docket</div>
    <h2>Browse the cases</h2>
    <p>Coverage is federal dockets via RECAP plus published opinions — county and
    most state trial courts are not in any free database.</p>
  </div>
  {body_inner}
</div></section>
"""
    return base_page("AI Litigation Monitor", "litigation.html", body, updated=updated)


# ------------------------------------------------------------ global page
def render_global(updated):
    data = load_global_raw()
    markers = []
    by_marker = {}
    for law in data.get("laws", []):
        key = JURIS_FOLD.get(law.get("country", ""), law.get("country", ""))
        by_marker.setdefault(key, {"verified": [], "unverified": []})
        by_marker[key]["verified"].append({
            "name": law.get("name", ""), "country": law.get("country", ""),
            "summary": law.get("summary", ""), "link": law.get("link", ""),
            "enacted": law.get("enacted", ""), "in_force": law.get("in_force", ""),
        })
    for law in data.get("unverified", []):
        key = JURIS_FOLD.get(law.get("country", ""), law.get("country", ""))
        by_marker.setdefault(key, {"verified": [], "unverified": []})
        by_marker[key]["unverified"].append({
            "name": law.get("name", ""), "country": law.get("country", ""),
            "summary": law.get("summary", ""), "link": law.get("source_url", ""),
            "missing": law.get("missing", ""),
        })
    for key, groups in by_marker.items():
        if key not in JURIS_COORDS:
            continue
        lat, lng = JURIS_COORDS[key]
        markers.append({
            "name": key, "lat": lat, "lng": lng,
            "verified": groups["verified"], "unverified": groups["unverified"],
        })
    markers.sort(key=lambda m: -(len(m["verified"]) + len(m["unverified"])))

    def law_card(law, badge):
        sub = f"Enacted {esc(law['enacted'])} · In force {esc(law['in_force'])}" \
            if badge == "Enacted" else f"Still needed: {esc(law.get('missing', 'official confirmation'))}"
        link = law.get("link") or ""
        label = "View official text &#8599;" if badge == "Enacted" else "Best lead so far &#8599;"
        title = (f'<h3><a href="{esc(link)}" target="_blank" rel="noopener">{esc(law["name"])}</a></h3>'
                 if link else f'<h3>{esc(law["name"])}</h3>')
        return f"""
        <article class="bcard" data-card data-badge="{badge}" data-kind=""
                 data-search="{esc((law['name'] + ' ' + law['country'] + ' ' + law['summary']).lower())}">
          <span class="badge {badge_class(badge)}">{badge}</span>
          {title}
          <p class="meta">{esc(law['country'])}</p>
          <p class="txt">{esc(law['summary'])}</p>
          <p class="meta" style="margin-top:.5rem">{sub}</p>
          {f'<div class="foot"><a class="offlink" href="{esc(link)}" target="_blank" rel="noopener">{label}</a></div>' if link else ""}
        </article>"""

    verified_cards = "".join(
        law_card({"name": l.get("name", ""), "country": l.get("country", ""),
                  "summary": l.get("summary", ""), "link": l.get("link", ""),
                  "enacted": l.get("enacted", ""), "in_force": l.get("in_force", "")},
                 "Enacted")
        for l in data.get("laws", []))
    unverified_cards = "".join(
        law_card({"name": l.get("name", ""), "country": l.get("country", ""),
                  "summary": l.get("summary", ""), "link": l.get("source_url", ""),
                  "missing": l.get("missing", "")},
                 "Unverified")
        for l in data.get("unverified", []))

    body = f"""
<header class="hero short">
  <div class="hero-inner">
    <div class="eyebrow reveal">Worldwide</div>
    <h1 class="reveal">Global AI Regulation Index</h1>
    <p class="sub reveal">The world's enacted AI laws — each one verified against an
    official government source. Select a marker to inspect a jurisdiction.</p>
  </div>
</header>

<section class="sec" style="padding-top:2.5rem"><div class="wrap">
  <div class="sec-head reveal">{glyph()}
    <div class="eyebrow">The world map</div>
    <h2>Click a jurisdiction</h2>
    <p>Glowing markers show jurisdictions with enacted AI laws; hollow markers are
    reported laws still awaiting verification.</p>
  </div>
  <div class="mapsec reveal">
    <div id="map"></div>
    <div class="maplegend">
      <h4>AI laws in force</h4>
      <div class="row"><span class="sw"></span> Enacted &amp; verified</div>
      <div class="row"><span class="sw" style="background:transparent;border:2px dashed #d74b17"></span> Awaiting verification</div>
    </div>
    <aside class="panel" id="mapPanel" aria-label="Jurisdiction detail">
      <div class="xrow"><span class="reset" id="mapPanelClose">&#8592; Start over</span></div>
      <h3 id="mapPanelTitle"></h3><div class="rule"></div>
      <div id="mapPanelPills"></div>
      <div id="mapPanelBody"></div>
    </aside>
  </div>
</div></section>

<section class="sec"><div class="wrap">
  <div class="sec-head reveal">{glyph()}
    <div class="eyebrow">Verified · {len(data.get('laws', []))}</div>
    <h2>Enacted laws</h2>
    <p>Confirmed against official government sources — legal text or authoritative
    status pages. General privacy and technology laws appear where their provisions
    clearly govern AI or automated decisions.</p>
  </div>
  <div data-explorer>
    {explorer_bar(["Enacted"], search_ph="Search enacted laws…")}
    <div class="grid">{verified_cards}</div>
    <div class="empty" data-f="empty"><h3>No matches</h3>
      <p>Try a different search term or clear the filters.</p></div>
  </div>
</div></section>

<section class="sec"><div class="wrap">
  <div class="sec-head reveal">{glyph("#c71585")}
    <div class="eyebrow">Awaiting verification · {len(data.get('unverified', []))}</div>
    <h2>The watchlist</h2>
    <p>Convincing candidates that could not be confirmed on an official source.
    They carry no weight in the enacted count until verified.</p>
  </div>
  <div data-explorer>
    {explorer_bar(["Unverified"], search_ph="Search the watchlist…")}
    <div class="grid">{unverified_cards}</div>
    <div class="empty" data-f="empty"><h3>No matches</h3>
      <p>Try a different search term or clear the filters.</p></div>
  </div>
</div></section>
"""
    extra_head = """
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>"""
    extra_scripts = f"""
<script>
(function(){{
  try{{
    var map=L.map('map',{{attributionControl:false}}).setView([30,10],2);
    map.attributionControl.setPrefix(false);
    L.tileLayer('https://{{s}}.basemaps.cartocdn.com/dark_all/{{z}}/{{x}}/{{y}}{{r}}.png',
      {{maxZoom:6,attribution:'&copy; OpenStreetMap &copy; CARTO'}}).addTo(map);
    var data={json.dumps(markers)};
    var panel=document.getElementById('mapPanel'),
        ptitle=document.getElementById('mapPanelTitle'),
        ppills=document.getElementById('mapPanelPills'),
        pbody=document.getElementById('mapPanelBody');
    function esc(s){{return String(s==null?'':s).replace(/[&<>"]/g,function(c){{
      return {{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}}[c];}});}}
    function lawHtml(l,verified){{
      var sub=verified
        ? 'Enacted '+esc(l.enacted)+' · In force '+esc(l.in_force)
        : 'Still needed: '+esc(l.missing||'official confirmation');
      return '<div class="plaw"><h4>'+(l.link
        ? '<a href="'+esc(l.link)+'" target="_blank" rel="noopener">'+esc(l.name)+'</a>'
        : esc(l.name))+'</h4>'
        +'<p class="sub2">'+esc(l.country)+' · '+sub+'</p>'
        +'<p>'+esc(l.summary)+'</p></div>';
    }}
    data.forEach(function(m){{
      var n=m.verified.length, hollow=n===0;
      var s=hollow?12:12+Math.min(n,12)*2.2;
      var mk=L.marker([m.lat,m.lng],{{title:m.name,
        icon:L.divIcon({{className:'',html:'<span class="pdot'+(hollow?' hollow':'')+'" style="width:'+s+'px;height:'+s+'px"></span>',iconSize:[s,s],iconAnchor:[s/2,s/2]}})}}).addTo(map);
      mk.bindTooltip(esc(m.name)+' — '+n+' enacted'+(m.unverified.length?', '+m.unverified.length+' unverified':''),{{direction:'top',offset:[0,-8]}});
      mk.on('click',function(){{
        ptitle.textContent=m.name;
        ppills.innerHTML='<span class="pill">'+n+' enacted</span>'
          +(m.unverified.length?'<span class="pill">'+m.unverified.length+' unverified</span>':'');
        pbody.innerHTML=
          m.verified.map(function(l){{return lawHtml(l,true);}}).join('')+
          m.unverified.map(function(l){{return lawHtml(l,false);}}).join('');
        panel.classList.add('open');
      }});
    }});
    document.getElementById('mapPanelClose').addEventListener('click',function(){{
      panel.classList.remove('open');
    }});
  }}catch(e){{
    document.getElementById('map').innerHTML=
      '<div class="notice" style="margin:2rem"><p>Map failed to load (network needed for map tiles). The full index is listed below.</p></div>';
  }}
}})();
</script>"""
    return base_page("Global AI Regulation Index", "global.html", body,
                      extra_head, extra_scripts, updated)


# ------------------------------------------------------------------- main
def main():
    now = datetime.now(LOCAL_TZ)
    updated = f"{now.strftime('%B')} {now.day}, {now.year}"

    fed, fed_err = safe_run(federal_bills, "federal bills")
    st, st_err = safe_run(state_bills, "state bills")
    suits, suits_err = safe_run(lawsuits, "lawsuits")
    glob, _ = safe_run(global_laws, "global laws")

    verified_n = len([i for i in (glob or []) if i["badge"] == "Enacted"])
    unverified_n = len([i for i in (glob or []) if i["badge"] == "Unverified"])
    print(f"[federal]  {len(fed) if fed else 0} bills")
    print(f"[states]   {len(st) if st else 0} bills")
    print(f"[lawsuits] {len(suits) if suits else 0} cases")
    print(f"[global]   {verified_n} verified laws, {unverified_n} unverified")

    pages = {
        "index.html": render_home(fed, st, suits, verified_n, unverified_n, updated),
        "us-laws.html": render_us_laws(fed, fed_err, st, st_err, updated),
        "litigation.html": render_litigation(suits, suits_err, updated),
        "global.html": render_global(updated),
    }
    here = os.path.dirname(os.path.abspath(__file__))
    docs = os.path.join(here, "docs")
    os.makedirs(docs, exist_ok=True)
    for name, page in pages.items():
        path = os.path.join(docs, name)
        with open(path, "w", encoding="utf-8") as f:
            f.write(page)
        print(f"Wrote docs/{name} ({len(page)} bytes).")


if __name__ == "__main__":
    main()
