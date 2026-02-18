# Darkhorse Press Top Story RSS Scraper

Production-ready Python scraper that monitors only the Darkhorse Press "Top Story" category and publishes an RSS 2.0 feed for downstream automation.

## Source

- Category: `https://darkhorsepressnow.com/category/news/top-story/`

## What it does

- Scans category listing pages (`page 1..N`) for post URLs.
- Keeps incremental state in `darkhorse-top-story.seen.json` so only new posts are fetched.
- Extracts per post:
  - title
  - canonical link
  - publish date
  - author (if available)
  - summary/excerpt
  - featured image (`og:image` first, then common WordPress selectors)
- Builds RSS 2.0 at `docs/darkhorse-top-story.xml` (newest first, stable ordering).
- Embeds image HTML in `<description>` and includes `media:content` image tags.
- Runs every 15 minutes via GitHub Actions (plus manual trigger).

## Files

- `darkhorse_topstory_to_rss.py`: scraper + RSS generator.
- `darkhorse-top-story.seen.json`: incremental state.
- `docs/darkhorse-top-story.xml`: published RSS feed for GitHub Pages.
- `.github/workflows/scrape.yml`: scheduled automation.

## Local run

```bash
python -m venv .venv
. .venv/bin/activate  # Windows: .venv\Scripts\activate
python -m pip install -r requirements.txt
python darkhorse_topstory_to_rss.py
```

Dry run:

```bash
python darkhorse_topstory_to_rss.py --dry-run
```

## Script config

The script has top-level defaults you can edit:

- `MAX_PAGES_TO_SCAN`
- `RECENT_TO_INCLUDE`
- `OUTPUT_PATH` (default `docs/darkhorse-top-story.xml`)
- `STATE_PATH` (default `darkhorse-top-story.seen.json`)

CLI overrides:

- `--max-pages`
- `--recent`
- `--output`
- `--state`
- `--dry-run`

## GitHub Actions behavior

- Workflow: `.github/workflows/scrape.yml`
- Triggers:
  - every 15 minutes (`cron: */15 * * * *`)
  - manual (`workflow_dispatch`)
- Uses `permissions: contents: write` and commits only when files changed.
- Concurrency guard prevents overlap:
  - `group: darkhorse-top-story-scrape`
  - `cancel-in-progress: false`

Note: GitHub scheduled workflows are best-effort. Runs can be delayed or occasionally skipped by GitHub.

## Enable GitHub Pages (exact UI steps)

1. Push this repository to GitHub on branch `main`.
2. Open the repo in GitHub.
3. Go to `Settings` -> `Pages`.
4. Under `Build and deployment`:
   - `Source`: `Deploy from a branch`
   - `Branch`: `main`
   - `Folder`: `/docs`
5. Click `Save`.
6. Wait for Pages to publish (can take a few minutes).
7. Open the feed URL and confirm XML renders.

## Final RSS URL template

`https://<username>.github.io/<repo>/darkhorse-top-story.xml`

## Optional first-run checks

1. `Actions` tab -> run `Scrape Darkhorse Top Story` manually once.
2. Confirm commit updated:
   - `docs/darkhorse-top-story.xml`
   - `darkhorse-top-story.seen.json`
3. Validate feed URL in a feed reader.
