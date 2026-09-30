# AI Regulation Tracker

A tiny Python tool that watches AI-regulation news — the Colorado AI Act, the EU AI Act,
US state AI bills, and general AI regulation coverage — and builds a one-page digest you
can publish free with GitHub Pages.

**Why it exists:** I work in compliance and policy, and I wanted a single page that keeps
me current on AI regulation without doomscrolling five news sites. Built with Python's
standard library only — no dependencies to install.

## Run it

```bash
python3 tracker.py
```

This fetches the latest stories from Google News RSS feeds and writes `docs/index.html`.
Re-run any time to refresh the digest.

## Publish it (GitHub Pages)

1. Create a new public repo on GitHub (e.g. `ai-regulation-tracker`) and push these files.
2. In the repo: **Settings → Pages → Source: Deploy from a branch → Branch: main, folder: `/docs` → Save.**
3. Your digest goes live at `https://<your-username>.github.io/ai-regulation-tracker/` — put that link on your resume and LinkedIn.

## How it works

- `tracker.py` pulls four Google News RSS searches (AI regulation, Colorado AI Act, EU AI Act, US state AI bills).
- It dedupes stories by headline, sorts newest-first, and renders the top 25 into a styled static page.
- One bad feed never kills a run — failures are logged and skipped.

## Ideas for later

- Add a feed (edit the `FEEDS` list — e.g. `"Texas AI bill"`, `"NIST AI"`).
- Email yourself the digest weekly with a cron job.
- Track a bill's status over time instead of just headlines.
