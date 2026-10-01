#!/usr/bin/env python3
"""
AI Regulation Tracker v2 — legislative tracker
==============================================
Tracks REAL legislation and litigation instead of news headlines:

  1. US federal AI bills        (Congress.gov API — needs CONGRESS_API_KEY)
  2. US state AI bills          (OpenStates API v3 — needs OPENSTATES_API_KEY)
  3. US AI-related lawsuits     (CourtListener search — no key needed)
  4. Enacted AI laws worldwide  (hand-curated data/global_laws.json)

Renders a single static page at docs/index.html, designed for GitHub Pages.

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
FEDERAL_CAP = 10
STATE_CAP = 15
DOCKET_CAP = 6              # RECAP dockets
OPINION_CAP = 4             # published opinions
REQUEST_TIMEOUT = 25
UA = {"User-Agent": "AI-Regulation-Tracker/2.0"}

# Congress.gov has no keyword search, so federal bills are filtered client-side
# against title + policy area + latest action text.
AI_RE = re.compile(
    r"\b(artificial intelligence|\bai\b|machine learning|generative ai|"
    r"foundation models?|frontier ai|large language models?|deepfakes?|"
    r"algorithmic|chatbots?|automated decisions?)\b",
    re.IGNORECASE,
)


def esc(s):
    return html.escape("" if s is None else str(s))


def fetch_json(url, headers=None):
    req = urllib.request.Request(url, headers={**UA, **(headers or {})})
    with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
        return json.loads(resp.read().decode("utf-8"))


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
    """Returns (items, error). items is None when no key AND no cached data.

    Congress.gov's /v3/bill endpoint has no full-text search -- it only
    filters by congress and bill type. So we pull the 250 most recently
    updated bills and match AI keywords client-side. Without an API key we
    fall back to a locally cached response (data/.congress_cache.json,
    refreshed by the maintainer; never committed).
    """
    data = None
    if CONGRESS_KEY:
        url = (f"https://api.congress.gov/v3/bill/{CONGRESS}"
               f"?sort=updateDate+desc&limit=250&api_key={CONGRESS_KEY}")
        data = fetch_json(url)
    else:
        here = os.path.dirname(os.path.abspath(__file__))
        cache = os.path.join(here, "data", ".congress_cache.json")
        if os.path.exists(cache):
            with open(cache, encoding="utf-8") as f:
                data = json.load(f)
    if data is None:
        return None, "needs-key"
    items = []
    for b in data.get("bills", []):
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
            "meta": f"Latest action: {esc(latest.get('text', '—'))}",
            "date": pretty_date(latest.get("actionDate", "")),
            "extra": f"Sponsor: {sponsor}" if sponsor else "",
            "link": link,
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
    """Returns (items, error). items is None when no API key is set."""
    if not OPENSTATES_KEY:
        return None, "needs-key"
    q = urllib.parse.quote('"artificial intelligence"')
    url = (f"https://v3.openstates.org/bills?q={q}&per_page=25"
           f"&sort=updated_desc&include=actions")
    data = fetch_json(url, headers={"X-API-KEY": OPENSTATES_KEY})
    scored = []
    for b in data.get("results", []):
        latest_desc = b.get("latest_action_description", "")
        badge = state_badge(latest_desc)
        juris = (b.get("jurisdiction") or {}).get("name", "")
        # Prefer enacted / recently-active bills at the top.
        boost = 2 if badge == "Enacted" else (1 if badge == "Passed chamber" else 0)
        scored.append((boost, b.get("latest_action_date", ""), {
            "title": f"{b.get('identifier', '')} — {b.get('title', '')}",
            "badge": badge,
            "meta": f"{esc(juris)} · {esc(b.get('session', ''))}",
            "date": pretty_date(b.get("latest_action_date", "")),
            "extra": f"Latest action: {latest_desc}" if latest_desc else "",
            "link": b.get("openstates_url", "") or "",
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
    # RECAP dockets — recently filed federal cases about AI (copyright,
    # deepfakes, chatbots). A bare "artificial intelligence" search mostly
    # returns unrelated cases that merely mention the phrase.
    dockets = courtlistener_search(
        '"artificial intelligence" (copyright OR deepfake OR chatbot)',
        "r", "&filed_after=2025-04-01")
    for d in (dockets.get("results") or [])[:DOCKET_CAP]:
        badge = "Terminated" if d.get("dateTerminated") else "Filed"
        items.append({
            "title": d.get("caseName", "Untitled case"),
            "badge": badge,
            "meta": f"{esc(d.get('court', ''))} · Docket {esc(d.get('docketNumber', ''))}",
            "date": pretty_date(d.get("dateFiled", "")),
            "extra": "",
            "link": "https://www.courtlistener.com" + (d.get("docket_absolute_url") or ""),
        })
    # Published opinions mentioning AI.
    opinions = courtlistener_search('"artificial intelligence"', "o")
    for o in (opinions.get("results") or [])[:OPINION_CAP]:
        items.append({
            "title": o.get("caseName", "Untitled opinion"),
            "badge": "Decided",
            "meta": f"{esc(o.get('court', ''))} · {esc(o.get('court_citation_string', ''))}",
            "date": pretty_date(o.get("dateFiled", "")),
            "extra": "",
            "link": "https://www.courtlistener.com" + (o.get("absolute_url") or ""),
        })
    return items, None


# --------------------------------------------------------------- global laws
def global_laws():
    here = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(here, "data", "global_laws.json")
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    items = []
    for law in data.get("laws", []):
        items.append({
            "title": f"{law.get('name', '')}",
            "badge": "Enacted",
            "meta": f"{esc(law.get('country', ''))} · Enacted: {esc(law.get('enacted', ''))} · In force: {esc(law.get('in_force', ''))}",
            "date": "",
            "extra": law.get("summary", ""),
            "link": law.get("link", ""),
        })
    return items, None


# ------------------------------------------------------------------- rendering
BADGE_COLORS = {
    "Enacted": "#1a7f37", "Passed both chambers": "#1a7f37",
    "Passed chamber": "#9a6700", "Introduced": "#57606a",
    "Active": "#0969da", "Filed": "#cf5016", "Terminated": "#57606a",
    "Decided": "#8250df",
}


def badge_html(badge):
    color = BADGE_COLORS.get(badge, "#57606a")
    return (f'<span style="display:inline-block;background:{color};color:#fff;'
            f'font-size:.72rem;font-weight:600;padding:.15rem .55rem;'
            f'border-radius:999px;margin-bottom:.4rem;">{esc(badge)}</span>')


def card(item):
    date_line = f" &middot; {esc(item['date'])}" if item["date"] else ""
    extra = f'<p class="extra">{esc(item["extra"])}</p>' if item["extra"] else ""
    return f"""
        <article class="card">
          {badge_html(item['badge'])}
          <h2><a href="{esc(item['link'])}">{esc(item['title'])}</a></h2>
          <p class="meta">{item['meta']}{date_line}</p>
          {extra}
        </article>"""


def key_notice(name, url, env):
    return f"""
        <div class="notice">
          <p>This section needs a free API key. Set the <code>{env}</code> environment
          variable (get a key at <a href="{url}">{url}</a>), then re-run
          <code>python3 tracker.py</code>.</p>
        </div>"""


def error_notice(what):
    return f"""
        <div class="notice">
          <p>Could not load {esc(what)} this run — the source may be down or rate-limited.
          Re-run later.</p>
        </div>"""


def section(heading, blurb, body):
    return f"""
      <section>
        <h2 class="section-head">{esc(heading)}</h2>
        <p class="blurb">{blurb}</p>
        {body}
      </section>"""


def render_page(sections_html, generated_at):
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>AI Regulation Tracker</title>
<style>
  body {{ font-family: -apple-system, Helvetica, Arial, sans-serif; max-width: 760px;
         margin: 0 auto; padding: 2rem 1rem; color: #1a1a1a; background: #fafafa; }}
  header {{ border-bottom: 2px solid #1a1a1a; margin-bottom: 1.5rem; padding-bottom: 1rem; }}
  h1 {{ margin: 0 0 .25rem; }}
  .sub {{ color: #555; margin: 0; }}
  .section-head {{ font-size: 1.25rem; margin: 2rem 0 .25rem;
                   padding-top: 1rem; border-top: 1px solid #ddd; }}
  section:first-of-type .section-head {{ border-top: none; margin-top: 1rem; padding-top: 0; }}
  .blurb {{ color: #555; font-size: .92rem; margin: 0 0 1rem; }}
  .card {{ background: #fff; border: 1px solid #e3e3e3; border-radius: 8px;
           padding: 1rem 1.25rem; margin-bottom: 1rem; }}
  .card h2 {{ font-size: 1.02rem; margin: 0 0 .3rem; }}
  .card h2 a {{ color: #1a1a1a; text-decoration: none; }}
  .card h2 a:hover {{ text-decoration: underline; }}
  .meta {{ color: #777; font-size: .85rem; margin: 0 0 .5rem; }}
  .extra {{ font-size: .9rem; margin: .4rem 0 0; color: #333; }}
  .notice {{ background: #fff8e1; border: 1px solid #e6c200; border-radius: 8px;
             padding: .75rem 1.1rem; margin-bottom: 1rem; font-size: .9rem; }}
  footer {{ color: #777; font-size: .85rem; margin-top: 2rem; }}
  code {{ background: #eee; padding: .1rem .35rem; border-radius: 4px; }}
</style>
</head>
<body>
<header>
  <h1>AI Regulation Tracker</h1>
  <p class="sub">US federal &amp; state AI bills &middot; AI lawsuits &middot; enacted AI laws worldwide</p>
  <p class="sub">Updated {generated_at}</p>
</header>
{sections_html}
<footer>
  <p>Sources: Congress.gov API (federal bills) · OpenStates API v3 (state bills) ·
     CourtListener (lawsuits) · hand-curated list (enacted laws).
     API keys are read from environment variables at build time and are never committed.
     Re-run <code>tracker.py</code> to refresh.</p>
</footer>
</body>
</html>
"""


def build_section(items, error, heading, blurb, key_info=None):
    if error == "needs-key":
        name, url, env = key_info
        body = key_notice(name, url, env)
    elif error:
        body = error_notice(heading)
    elif not items:
        body = "<p>No results this run.</p>"
    else:
        body = "".join(card(i) for i in items)
    return section(heading, blurb, body)


def main():
    now = datetime.now(LOCAL_TZ)
    generated_at = f"{now.strftime('%B')} {now.day}, {now.year}"

    fed, fed_err = safe_run(federal_bills, "federal bills")
    st, st_err = safe_run(state_bills, "state bills")
    suits, suits_err = safe_run(lawsuits, "lawsuits")
    glob, glob_err = safe_run(global_laws, "global laws")

    print(f"[federal] {len(fed) if fed else 0} bills" + (" (no API key)" if fed_err == "needs-key" else ""))
    print(f"[states]  {len(st) if st else 0} bills" + (" (no API key)" if st_err == "needs-key" else ""))
    print(f"[lawsuits] {len(suits) if suits else 0} cases")
    print(f"[global]  {len(glob) if glob else 0} laws")

    sections = "".join([
        build_section(fed, fed_err, "US Federal Bills",
                      f"AI-related bills in the {CONGRESS}th Congress, newest action first.",
                      ("Congress.gov", "https://api.congress.gov/sign-up", "CONGRESS_API_KEY")),
        build_section(st, st_err, "US State Bills",
                      "AI bills across all state legislatures, current sessions. Enacted and recently-active bills first.",
                      ("OpenStates", "https://open.pluralpolicy.com/accounts/signup", "OPENSTATES_API_KEY")),
        build_section(suits, suits_err, "US AI Lawsuits",
                      "Recently filed federal cases and published opinions mentioning artificial intelligence. "
                      "Coverage is federal dockets (via RECAP) plus published opinions — "
                      "county and most state trial courts are not in any free database."),
        build_section(glob, glob_err, "Enacted AI Laws Worldwide",
                      "Hand-curated, verified list of AI laws actually in force. Maintained in "
                      "<code>data/global_laws.json</code> — edit it directly to add new laws."),
    ])

    page = render_page(sections, generated_at)
    os.makedirs("docs", exist_ok=True)
    with open("docs/index.html", "w", encoding="utf-8") as f:
        f.write(page)
    print(f"Wrote docs/index.html ({len(page)} bytes).")


def safe_run(fn, label):
    try:
        return fn()
    except Exception as exc:  # one bad source shouldn't kill the run
        print(f"[{label}] skipped ({exc})")
        return [], str(exc)


if __name__ == "__main__":
    main()
