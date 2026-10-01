# AI Regulation Tracker

A tiny Python tool that tracks **real AI legislation and litigation** — US federal
bills, US state bills, AI-related lawsuits, and enacted AI laws worldwide — and
builds a one-page digest you can publish free with GitHub Pages.

**Why it exists:** I work in compliance and policy, and I wanted a single page that
keeps me current on AI regulation without doomscrolling five news sites. Built
with Python's standard library only — no dependencies to install.

## Run it

```bash
python3 tracker.py
```

This pulls the four sources below and writes `docs/index.html`. Re-run any time
to refresh. It works with no API keys at all — the two keyed sections simply
show a note explaining how to enable them.

## Data sources

| Section | Source | Key needed? |
|---|---|---|
| US Federal Bills | Congress.gov API (`api.congress.gov/v3/bill`) — 1,000 most recently updated bills of the 119th Congress (4 pages × 250), filtered client-side for AI relevance (Congress.gov offers no keyword search) | Yes — free at https://api.congress.gov/sign-up |
| US State Bills | OpenStates API v3 (`v3.openstates.org/bills`) — full-text search across all state legislatures; five queries (`"artificial intelligence"`, `deepfake`, `"algorithmic discrimination"`, `"automated decision"`, `"synthetic media"`) merged and deduped | Yes — free at https://open.pluralpolicy.com/accounts/signup |
| US AI Lawsuits | CourtListener search API (RECAP dockets filed after Apr 2025 + published opinions) | No |
| Enacted AI Laws Worldwide | Hand-curated `data/global_laws.json` | No — edit the file directly to add laws |

### Enabling the API keys

```bash
export CONGRESS_API_KEY="your-key-here"
export OPENSTATES_API_KEY="your-key-here"
python3 tracker.py
```

Keys are read from environment variables **at build time only** and are never
written to any file or committed to the repo. The generated `docs/index.html`
contains no keys.

### Maintainer refresh (key stored in secure vault)

If the Congress.gov key lives in secure storage instead of an env var:

```bash
~/workspace/skills/congress-gov/bin/congress_bills.py 119 > data/.congress_cache.json
~/workspace/skills/openstates/bin/openstates_bills.py '"artificial intelligence"' > data/.openstates_cache.json
python3 tracker.py
```

The CLIs fetch through the stored credentials and write local caches;
`tracker.py` uses the caches when the env vars are unset. Never commit
`data/.congress_cache.json` or `data/.openstates_cache.json` — they are local
build artifacts.

## Publish it (GitHub Pages)

1. Create a new public repo on GitHub (e.g. `ai-regulation-tracker`) and push these files.
2. In the repo: **Settings → Pages → Source: Deploy from a branch → Branch: main, folder: `/docs` → Save.**
3. Your tracker goes live at `https://<your-username>.github.io/ai-regulation-tracker/` — put that link on your resume and LinkedIn.

## How it works

- `tracker.py` queries Congress.gov and OpenStates for AI bills, CourtListener for
  recent AI dockets and opinions, and loads the curated global laws list.
- Bills are shown with status badges (Enacted / Passed chamber / Introduced /
  Active); lawsuits with Filed / Terminated / Decided.
- State bills are ranked with enacted and recently-active bills first.
- One bad source never kills a run — failures are logged and the section shows a
  retry note.
- The page is a dependency-free dashboard UI: stat cards per section, section tabs,
  full-text search, a status filter, a live result count, and a dark-mode toggle —
  all client-side JavaScript, so it runs on GitHub Pages with zero backend.
- The lawsuit section is honest about coverage: federal dockets (via RECAP) plus
  published opinions. County and most state trial courts are not in any free
  database.

## Ideas for later

- Track a specific bill's status over time (snapshot each run into a history file).
- Email yourself the digest weekly with a cron job.
- Add EU legislative tracking via EUR-Lex once the global list outgrows hand curation.
