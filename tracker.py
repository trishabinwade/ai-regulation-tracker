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
            "search": " ".join([f"{btype} {number}", title, policy, latest.get("text", ""), sponsor]),
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
    """Returns (items, error). items is None when no key AND no cached data.

    Without an API key we fall back to a locally cached response
    (data/.openstates_cache.json, refreshed by the maintainer; never committed).
    """
    data = None
    if OPENSTATES_KEY:
        q = urllib.parse.quote('"artificial intelligence"')
        url = (f"https://v3.openstates.org/bills?q={q}&per_page=20"
               f"&sort=updated_desc")
        data = fetch_json(url, headers={"X-API-KEY": OPENSTATES_KEY})
    else:
        here = os.path.dirname(os.path.abspath(__file__))
        cache = os.path.join(here, "data", ".openstates_cache.json")
        if os.path.exists(cache):
            with open(cache, encoding="utf-8") as f:
                data = json.load(f)
    if data is None:
        return None, "needs-key"
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
            "search": " ".join([b.get("identifier", ""), b.get("title", ""), juris, b.get("session", ""), latest_desc]),
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
            "search": " ".join([d.get("caseName", ""), d.get("court", ""), d.get("docketNumber", "")]),
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
            "search": " ".join([o.get("caseName", ""), o.get("court", ""), o.get("court_citation_string", "")]),
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
            "search": " ".join([law.get("name", ""), law.get("country", ""), law.get("summary", "")]),
        })
    return items, None


# ------------------------------------------------------------------- rendering
BADGE_COLORS = {
    "Enacted": "#1a7f37", "Passed both chambers": "#1a7f37",
    "Passed chamber": "#9a6700", "Introduced": "#57606a",
    "Active": "#0969da", "Filed": "#cf5016", "Terminated": "#57606a",
    "Decided": "#8250df",
}

TABS = [
    ("all", "All"),
    ("federal", "Federal bills"),
    ("states", "State bills"),
    ("lawsuits", "Lawsuits"),
    ("global", "Global laws"),
]


def badge_html(badge):
    color = BADGE_COLORS.get(badge, "#57606a")
    return f'<span class="badge" style="background:{color};">{esc(badge)}</span>'


def card(item, section_key):
    date_line = f" &middot; {esc(item['date'])}" if item["date"] else ""
    extra = f'<p class="extra">{esc(item["extra"])}</p>' if item["extra"] else ""
    return f"""
        <article class="card" data-section="{section_key}"
                 data-badge="{esc(item['badge'])}"
                 data-search="{esc(item.get('search', '').lower())}">
          {badge_html(item['badge'])}
          <h2><a href="{esc(item['link'])}" target="_blank" rel="noopener">{esc(item['title'])}</a></h2>
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


def section_block(key, heading, blurb, body_html):
    return f"""
      <section class="sec" data-section="{key}">
        <div class="sec-head">
          <h2>{esc(heading)}</h2>
          <p class="blurb">{blurb}</p>
        </div>
        {body_html}
      </section>"""


def build_section(key, heading, blurb, items, error, key_info=None):
    if error == "needs-key":
        name, url, env = key_info
        body = key_notice(name, url, env)
    elif error:
        body = error_notice(heading)
    elif not items:
        body = '<div class="notice"><p>No results this run.</p></div>'
    else:
        body = '<div class="grid">' + "".join(card(i, key) for i in items) + "</div>"
    return section_block(key, heading, blurb, body)


PAGE_TEMPLATE = """<!DOCTYPE html>
<html lang="en" data-theme="light">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>AI Regulation Tracker</title>
<style>
:root{
  --bg:#f6f8fa; --card:#ffffff; --text:#1f2328; --muted:#59636e;
  --border:#d8dee4; --accent:#0969da; --codebg:#eaeef2;
}
[data-theme="dark"]{
  --bg:#0d1117; --card:#161b22; --text:#e6edf3; --muted:#8b949e;
  --border:#30363d; --accent:#4493f8; --codebg:#21262d;
}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--text);
  font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Helvetica,Arial,sans-serif;}
.wrap{max-width:1120px;margin:0 auto;padding:0 1.25rem 3rem}
.top{display:flex;justify-content:space-between;align-items:flex-start;gap:1rem;
  padding:2rem 0 .5rem;flex-wrap:wrap}
h1{margin:0;font-size:1.9rem;letter-spacing:-.02em}
.sub{color:var(--muted);margin:.35rem 0 0}
.theme-btn{border:1px solid var(--border);background:var(--card);color:var(--text);
  border-radius:999px;padding:.5rem .95rem;font-size:.85rem;cursor:pointer}
.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));
  gap:.75rem;margin:1.25rem 0 0}
.stat{background:var(--card);border:1px solid var(--border);border-radius:12px;
  padding:.85rem 1.05rem}
.stat .num{font-size:1.55rem;font-weight:700;letter-spacing:-.02em}
.stat .lbl{color:var(--muted);font-size:.82rem;margin-top:.15rem}
.controls{position:sticky;top:0;z-index:10;background:var(--bg);
  padding:.7rem 0;border-bottom:1px solid var(--border);
  display:flex;gap:.55rem;flex-wrap:wrap;align-items:center;margin-top:1.25rem}
.search{flex:1;min-width:180px;padding:.55rem .8rem;border:1px solid var(--border);
  border-radius:8px;background:var(--card);color:var(--text);font-size:.95rem}
.tabs{display:flex;gap:.4rem;flex-wrap:wrap}
.tab{border:1px solid var(--border);background:var(--card);color:var(--text);
  border-radius:999px;padding:.45rem .9rem;font-size:.85rem;cursor:pointer}
.tab.active{background:var(--text);color:var(--bg);border-color:var(--text)}
.status-sel{padding:.5rem .6rem;border:1px solid var(--border);border-radius:8px;
  background:var(--card);color:var(--text);font-size:.88rem}
.count{color:var(--muted);font-size:.85rem;margin-left:auto}
.sec{margin-top:2.25rem}
.sec-head h2{margin:0 0 .15rem;font-size:1.3rem;letter-spacing:-.01em}
.blurb{color:var(--muted);font-size:.92rem;margin:0 0 1rem;max-width:70ch}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(320px,1fr));gap:.9rem}
.card{background:var(--card);border:1px solid var(--border);border-radius:12px;
  padding:1rem 1.15rem}
.badge{display:inline-block;color:#fff;font-size:.68rem;font-weight:700;
  letter-spacing:.05em;text-transform:uppercase;padding:.22rem .62rem;
  border-radius:999px;margin-bottom:.55rem}
.card h2{font-size:1rem;margin:0 0 .35rem;line-height:1.35}
.card h2 a{color:var(--text);text-decoration:none}
.card h2 a:hover{color:var(--accent);text-decoration:underline}
.meta{color:var(--muted);font-size:.82rem;margin:0 0 .35rem;line-height:1.4}
.extra{font-size:.88rem;margin:.35rem 0 0;line-height:1.5}
.notice{background:var(--card);border:1px solid var(--border);
  border-left:4px solid #d4a017;border-radius:8px;
  padding:.85rem 1.1rem;font-size:.9rem}
.notice a{color:var(--accent)}
#empty{display:none;text-align:center;color:var(--muted);padding:3.5rem 1rem}
#empty h3{color:var(--text)}
footer{color:var(--muted);font-size:.83rem;margin-top:2.5rem;
  border-top:1px solid var(--border);padding-top:1.25rem;line-height:1.6}
footer a{color:var(--accent)}
code{background:var(--codebg);padding:.1rem .35rem;border-radius:4px;font-size:.85em}
@media (max-width:640px){ h1{font-size:1.5rem} .count{margin-left:0;width:100%} }
</style>
</head>
<body>
<div class="wrap">
  <header class="top">
    <div>
      <h1>AI Regulation Tracker</h1>
      <p class="sub">US federal &amp; state AI bills &middot; AI lawsuits &middot; enacted AI laws worldwide</p>
      <p class="sub">Updated %%DATE%%</p>
    </div>
    <button class="theme-btn" id="themeBtn" aria-label="Toggle dark mode">&#9790; Dark</button>
  </header>

  <div class="stats">%%STATS%%</div>

  <div class="controls">
    <input class="search" id="search" type="search" placeholder="Search bills, cases, laws&hellip;" aria-label="Search">
    <div class="tabs" id="tabs">%%TABS%%</div>
    <select class="status-sel" id="statusSel" aria-label="Filter by status">
      <option value="">All statuses</option>
      %%OPTS%%
    </select>
    <span class="count" id="count"></span>
  </div>

  %%SECTIONS%%

  <div id="empty">
    <h3>No matches</h3>
    <p>Try a different search term or clear the filters.</p>
  </div>

  <footer>
    <p>Sources: Congress.gov API (federal bills) &middot; OpenStates API v3 (state bills) &middot;
       CourtListener (lawsuits) &middot; hand-curated list (enacted laws).
       API keys are read from environment variables or local caches at build time and are never committed.
       Re-run <code>tracker.py</code> to refresh.</p>
  </footer>
</div>
<script>
(function(){
  var themeBtn = document.getElementById('themeBtn');
  function setTheme(t){
    document.documentElement.setAttribute('data-theme', t);
    try{ localStorage.setItem('ai-tracker-theme', t); }catch(e){}
    themeBtn.innerHTML = t === 'dark' ? '&#9788; Light' : '&#9790; Dark';
  }
  var saved = null;
  try{ saved = localStorage.getItem('ai-tracker-theme'); }catch(e){}
  setTheme(saved || (window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'));
  themeBtn.addEventListener('click', function(){
    setTheme(document.documentElement.getAttribute('data-theme') === 'dark' ? 'light' : 'dark');
  });

  var state = { tab:'all', q:'', status:'' };
  var searchEl = document.getElementById('search');
  var statusEl = document.getElementById('statusSel');
  var countEl = document.getElementById('count');
  var emptyEl = document.getElementById('empty');
  var totalCards = document.querySelectorAll('.card').length;

  document.getElementById('tabs').addEventListener('click', function(e){
    var b = e.target.closest('.tab');
    if(!b) return;
    document.querySelectorAll('.tab').forEach(function(t){ t.classList.remove('active'); });
    b.classList.add('active');
    state.tab = b.getAttribute('data-tab');
    apply();
  });
  searchEl.addEventListener('input', function(){ state.q = searchEl.value.trim().toLowerCase(); apply(); });
  statusEl.addEventListener('change', function(){ state.status = statusEl.value; apply(); });

  function apply(){
    var shown = 0;
    document.querySelectorAll('.sec').forEach(function(sec){
      var key = sec.getAttribute('data-section');
      var secMatch = state.tab === 'all' || state.tab === key;
      var vis = 0;
      sec.querySelectorAll('.card').forEach(function(card){
        var ok = (state.tab === 'all' || card.getAttribute('data-section') === state.tab)
          && (!state.q || card.getAttribute('data-search').indexOf(state.q) !== -1)
          && (!state.status || card.getAttribute('data-badge') === state.status);
        card.style.display = ok ? '' : 'none';
        if(ok){ vis++; shown++; }
      });
      var notice = sec.querySelector('.notice');
      var showSec = secMatch && (vis > 0 || (notice && !state.q && !state.status));
      sec.style.display = showSec ? '' : 'none';
    });
    emptyEl.style.display = shown === 0 ? '' : 'none';
    countEl.textContent = 'Showing ' + shown + ' of ' + totalCards;
  }
  apply();
})();
</script>
</body>
</html>
"""


def render_page(sections_html, stats, badges, generated_at):
    stat_html = "".join(
        f'<div class="stat"><div class="num">{n}</div>'
        f'<div class="lbl">{esc(label)}</div></div>'
        for label, n in stats
    )
    tabs_html = "".join(
        f'<button class="tab{" active" if key == "all" else ""}" '
        f'data-tab="{key}">{esc(label)}</button>'
        for key, label in TABS
    )
    opts_html = "".join(
        f'<option value="{esc(b)}">{esc(b)}</option>' for b in badges
    )
    page = PAGE_TEMPLATE
    page = page.replace("%%DATE%%", generated_at)
    page = page.replace("%%STATS%%", stat_html)
    page = page.replace("%%TABS%%", tabs_html)
    page = page.replace("%%OPTS%%", opts_html)
    page = page.replace("%%SECTIONS%%", sections_html)
    return page


def main():
    now = datetime.now(LOCAL_TZ)
    generated_at = f"{now.strftime('%B')} {now.day}, {now.year}"

    fed, fed_err = safe_run(federal_bills, "federal bills")
    st, st_err = safe_run(state_bills, "state bills")
    suits, suits_err = safe_run(lawsuits, "lawsuits")
    glob, glob_err = safe_run(global_laws, "global laws")

    print(f"[federal] {len(fed) if fed else 0} bills")
    print(f"[states]  {len(st) if st else 0} bills")
    print(f"[lawsuits] {len(suits) if suits else 0} cases")
    print(f"[global]  {len(glob) if glob else 0} laws")

    sections = "".join([
        build_section("federal", "US Federal Bills",
                      f"AI-related bills in the {CONGRESS}th Congress, newest action first.",
                      fed, fed_err,
                      ("Congress.gov", "https://api.congress.gov/sign-up", "CONGRESS_API_KEY")),
        build_section("states", "US State Bills",
                      "AI bills across all state legislatures, current sessions. Enacted and recently-active bills first.",
                      st, st_err,
                      ("OpenStates", "https://open.pluralpolicy.com/accounts/signup", "OPENSTATES_API_KEY")),
        build_section("lawsuits", "US AI Lawsuits",
                      "Recently filed federal cases and published opinions mentioning artificial intelligence. "
                      "Coverage is federal dockets (via RECAP) plus published opinions — "
                      "county and most state trial courts are not in any free database.",
                      suits, suits_err),
        build_section("global", "Enacted AI Laws Worldwide",
                      "Hand-curated, verified list of AI laws actually in force. Maintained in "
                      "<code>data/global_laws.json</code> — edit it directly to add new laws.",
                      glob, glob_err),
    ])

    all_items = [i for items in (fed, st, suits, glob) if items for i in items]
    badges = sorted({i["badge"] for i in all_items})
    stats = [
        ("Federal bills", len(fed) if fed else 0),
        ("State bills", len(st) if st else 0),
        ("Lawsuits", len(suits) if suits else 0),
        ("Enacted laws", len(glob) if glob else 0),
    ]

    page = render_page(sections, stats, badges, generated_at)
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
