#!/usr/bin/env python3
"""
AI Regulation Tracker
=====================
Fetches AI-regulation news from Google News RSS feeds, removes duplicates,
and renders a simple static digest page at docs/index.html.

The page is designed to be published with GitHub Pages (free static hosting),
so the tracker doubles as a public portfolio piece.

Run it with:
    python3 tracker.py

No third-party packages needed — standard library only.
"""

import html
import os
import re
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

# Each feed is a (label, Google News RSS URL) pair. Add or remove topics here.
FEEDS = [
    ("AI regulation", "https://news.google.com/rss/search?q=artificial%20intelligence%20regulation%20law&hl=en-US&gl=US&ceid=US%3Aen"),
    ("Colorado AI Act", "https://news.google.com/rss/search?q=%22Colorado%20AI%20Act%22&hl=en-US&gl=US&ceid=US%3Aen"),
    ("EU AI Act", "https://news.google.com/rss/search?q=%22EU%20AI%20Act%22&hl=en-US&gl=US&ceid=US%3Aen"),
    ("US state AI bills", "https://news.google.com/rss/search?q=state%20%22AI%20bill%22%20OR%20%22algorithmic%20discrimination%22%20law&hl=en-US&gl=US&ceid=US%3Aen"),
]

MAX_ITEMS = 25          # max stories in the digest
REQUEST_TIMEOUT = 20    # seconds per feed


def fetch_feed(url):
    """Download one RSS feed and return a list of item dicts."""
    req = urllib.request.Request(url, headers={"User-Agent": "AI-Regulation-Tracker/1.0"})
    with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
        xml_bytes = resp.read()
    root = ET.fromstring(xml_bytes)
    items = []
    for item in root.iter("item"):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        source_el = item.find("source")
        source = (source_el.text or "").strip() if source_el is not None else ""
        pub_raw = (item.findtext("pubDate") or "").strip()
        try:
            published = parsedate_to_datetime(pub_raw)
        except (TypeError, ValueError):
            published = None
        # Description is HTML; strip tags down to plain text.
        desc_html = item.findtext("description") or ""
        desc_text = re.sub(r"<[^>]+>", "", desc_html).strip()
        desc_text = html.unescape(desc_text)
        if len(desc_text) > 280:
            desc_text = desc_text[:277].rstrip() + "..."
        if title and link:
            items.append({
                "title": title,
                "link": link,
                "source": source,
                "published": published,
                "summary": desc_text,
            })
    return items


def dedupe(items):
    """Drop stories we've already seen (same headline, case-insensitive)."""
    seen, unique = set(), []
    for item in items:
        key = item["title"].lower()
        if key not in seen:
            seen.add(key)
            unique.append(item)
    return unique


def render_html(items, generated_at):
    """Build the digest page. Everything user-visible is HTML-escaped."""
    cards = []
    for item in items:
        date_str = item["published"].strftime("%b %d, %Y") if item["published"] else "date unknown"
        cards.append(f"""
        <article class="card">
          <h2><a href="{html.escape(item['link'])}">{html.escape(item['title'])}</a></h2>
          <p class="meta">{html.escape(item['source'])} &middot; {date_str}</p>
          <p>{html.escape(item['summary'])}</p>
        </article>""")
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>AI Regulation Tracker</title>
<style>
  body {{ font-family: -apple-system, Helvetica, Arial, sans-serif; max-width: 720px;
         margin: 0 auto; padding: 2rem 1rem; color: #1a1a1a; background: #fafafa; }}
  header {{ border-bottom: 2px solid #1a1a1a; margin-bottom: 1.5rem; padding-bottom: 1rem; }}
  h1 {{ margin: 0 0 .25rem; }}
  .sub {{ color: #555; margin: 0; }}
  .card {{ background: #fff; border: 1px solid #e3e3e3; border-radius: 8px;
           padding: 1rem 1.25rem; margin-bottom: 1rem; }}
  .card h2 {{ font-size: 1.05rem; margin: 0 0 .3rem; }}
  .card h2 a {{ color: #1a1a1a; text-decoration: none; }}
  .card h2 a:hover {{ text-decoration: underline; }}
  .meta {{ color: #777; font-size: .85rem; margin: 0 0 .5rem; }}
  footer {{ color: #777; font-size: .85rem; margin-top: 2rem; }}
</style>
</head>
<body>
<header>
  <h1>AI Regulation Tracker</h1>
  <p class="sub">Colorado AI Act &middot; EU AI Act &middot; US state AI bills &middot; AI regulation news</p>
  <p class="sub">Updated {generated_at}</p>
</header>
{''.join(cards) if cards else '<p>No stories found this run.</p>'}
<footer>
  <p>Built with Python (standard library only). Sources: Google News RSS.
     Re-run <code>tracker.py</code> to refresh.</p>
</footer>
</body>
</html>
"""


def main():
    all_items = []
    for label, url in FEEDS:
        try:
            found = fetch_feed(url)
            print(f"[{label}] {len(found)} stories")
            all_items.extend(found)
        except Exception as exc:  # one bad feed shouldn't kill the run
            print(f"[{label}] skipped ({exc})")
    all_items = dedupe(all_items)
    # Newest first; undated items sink to the bottom.
    all_items.sort(key=lambda i: i["published"] or datetime.min.replace(tzinfo=timezone.utc),
                   reverse=True)
    digest = all_items[:MAX_ITEMS]
    generated_at = datetime.now(timezone.utc).strftime("%B %d, %Y")
    page = render_html(digest, generated_at)
    os.makedirs("docs", exist_ok=True)
    with open("docs/index.html", "w", encoding="utf-8") as f:
        f.write(page)
    print(f"Wrote docs/index.html with {len(digest)} stories.")


if __name__ == "__main__":
    main()
