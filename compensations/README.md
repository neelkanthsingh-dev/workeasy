# 🇮🇳 India Tech Compensation Tracker

Scrapes **LeetCode Discuss** posts, extracts structured India compensation data with AI, merges results across sources, and generates a sorted PDF report.

---

## How it works

```text
fetch_lc.py  →  <prefix>_raw_page_*.json  →  ai_decipher.py  →  <prefix>_results*.json  →  run_all.py  →  results.json + PDF
```

| Step | Script           | What it does                                                                                               |
| ---- | ---------------- | ---------------------------------------------------------------------------------------------------------- |
| 1    | `fetch_lc.py`    | Fetches LeetCode Discuss posts via public GraphQL API and downloads full post content in parallel          |
| 2    | `ai_decipher.py` | Sends post batches to the AI model, extracts India compensation entries, and saves per-prefix result files |
| 3    | `run_all.py`     | Orchestrates fetch + AI extraction, merges/deduplicates outputs, and generates a PDF report                |

---

## Current supported sources

By default, the pipeline uses:

- **Compensation** posts (`prefix=lc`, tag: `compensation`)

Optionally, you can also include:

- **Interview + Career** posts (`prefix=ic`, tags: `interview career`)

When both are enabled, `run_all.py` merges the result sets and deduplicates entries by post URL.

---

## Quick start

### 1) Install dependencies

Recommended:

```bash
cd /Users/n02/Compensations
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
pip install reportlab
```

> Note: `reportlab` is required for PDF generation but is not currently listed in `requirements.txt`.

### 2) Run the full pipeline

```bash
# Compensation posts only
python3 run_all.py --pages 2 --per-page 15

# Compensation + Interview/Career posts
python3 run_all.py --pages 2 --per-page 15 --include-ic

# Reuse existing raw files and only re-run AI + merge + PDF
python3 run_all.py --pages 2 --skip-fetch
```

Generated outputs:

- `results.json` → merged final results across selected sources
- `compensation_report_YYYYMMDD_HHMM.pdf` → sorted PDF report

On macOS, the generated PDF is auto-opened.

---

## Script usage

### `fetch_lc.py`

Fetch posts from LeetCode and save raw JSON pages.

```bash
python3 fetch_lc.py --pages 2 --per-page 15

# Custom source prefix
python3 fetch_lc.py --pages 2 --per-page 15 --tags compensation --prefix lc

# Interview + Career source
python3 fetch_lc.py --pages 2 --per-page 15 --tags interview career --prefix ic
```

What it does:

- Uses LeetCode public GraphQL endpoints
- Fetches listing pages newest-first
- Fetches full post content in parallel with **5 workers**
- Applies an internal **5 requests/sec** rate limit

Output files:

- `<prefix>_raw_page_1.json`
- `<prefix>_raw_page_2.json`
- ...

Each raw file contains a list of posts like:

```json
{
  "id": "1234567",
  "slug": "google-l5-sse-india-verbal-offer-abc123",
  "title": "Google L5 SSE India Verbal Offer",
  "tags": ["Compensation"],
  "created_ts": "2026-03-22T10:00:00.000Z",
  "content": "Full cleaned post text...",
  "url": "https://leetcode.com/discuss/post/1234567/"
}
```

### `ai_decipher.py`

Extract structured India compensation data from fetched post files.

```bash
# Process all lc_raw_page_*.json files
python3 ai_decipher.py

# Only process the first 2 pages for prefix=lc
python3 ai_decipher.py --pages 2 --prefix lc

# Process interview/career raw files
python3 ai_decipher.py --pages 2 --prefix ic
```

What it does:

- Reads `<prefix>_raw_page_*.json`
- Batches posts into chunks of **10**
- Executes AI calls in parallel using up to **10 workers**
- Applies a **20 calls / 60 seconds** sliding-window rate limit
- Writes both merged and per-page result files

Output files:

- `<prefix>_results.json`
- `<prefix>_results_page_1.json`
- `<prefix>_results_page_2.json`
- ...

Each extracted entry looks like:

```json
{
  "company": "Google",
  "post_title": "Google L5 SSE India Verbal Offer",
  "level": "L5",
  "yoe": 6.5,
  "ctc_lpa": 102.0,
  "notes": "Bangalore verbal offer for L5. Base 60L + RSU 35L + bonus 7L. Negotiating.",
  "url": "https://leetcode.com/discuss/post/1234567/"
}
```

### `run_all.py`

Run the end-to-end workflow.

```bash
python3 run_all.py --pages 2 --per-page 15
python3 run_all.py --pages 10 --per-page 15
python3 run_all.py --pages 2 --per-page 15 --include-ic
python3 run_all.py --pages 2 --skip-fetch
```

What it does:

1. Fetches raw posts unless `--skip-fetch` is used
2. Runs AI extraction for each selected source prefix
3. Merges and deduplicates results by URL
4. Saves merged output to `results.json`
5. Generates a landscape A4 PDF sorted by `ctc_lpa` descending

CLI options:

- `--pages` → number of pages to fetch/process (default: `2`)
- `--per-page` → posts per page to fetch (default: `15`)
- `--skip-fetch` → reuse existing raw files
- `--include-ic` → also include Interview + Career posts

---

## Output files

### Final merged JSON

`results.json`

Contains the merged result set across all selected sources.

### Per-source intermediate files

- `lc_raw_page_*.json`
- `lc_results.json`
- `lc_results_page_*.json`
- `ic_raw_page_*.json` _(only when `--include-ic` / custom prefix is used)_
- `ic_results.json` _(only when `--include-ic` / custom prefix is used)_
- `ic_results_page_*.json` _(only when `--include-ic` / custom prefix is used)_

### PDF report

The PDF report is generated as:

`compensation_report_YYYYMMDD_HHMM.pdf`

Format:

- Landscape A4
- Sorted by CTC descending
- Columns: `# | Company | Level | YOE | CTC (LPA) | Notes | Post Title | Link`

---

## Configuration

### `fetch_lc.py`

| Setting      | Default | Description                      |
| ------------ | ------- | -------------------------------- |
| `MAX_RPS`    | `5`     | Max LeetCode requests per second |
| worker count | `5`     | Parallel content fetch workers   |

### `ai_decipher.py`

| Setting       | Default                    | Description                     |
| ------------- | -------------------------- | ------------------------------- |
| `CHUNK_SIZE`  | `10`                       | Posts per AI call               |
| `MAX_CALLS`   | `20`                       | Max AI calls per rate window    |
| `RATE_WINDOW` | `60.0`                     | AI rate-limit window in seconds |
| `MAX_WORKERS` | `10`                       | Parallel AI worker count        |
| `MODEL`       | `gpt-5.4`                  | AI model                        |
| `BASE_URL`    | `https://api.fuelix.ai/v1` | AI API base URL                 |

---

## Notes and caveats

- The extractor is tuned for **India-based compensation data** and ignores clearly non-India posts where possible.
- If a post compares multiple offers, the AI may emit multiple entries from a single source post.
- `run_all.py` deduplicates merged output by `url`.
- API credentials are currently embedded in `ai_decipher.py`; moving them to environment variables would be safer.
- `requirements.txt` currently does **not** include `reportlab`, even though `run_all.py` requires it to generate PDFs.

---

## Minimal dependency install

If you prefer a one-liner instead of `requirements.txt`:

```bash
pip install requests openai reportlab
```

---

## Browser-based job application automation

This repo now also includes a standalone Browser Use script for programmatic job applications on career portals.

Why this approach:

- **Browser Use** is a good fit for Python-based automation with LLM browser control
- Works well for dynamic portals such as Workday / Greenhouse / Lever
- Keeps this separate from the compensation pipeline, so the existing scraper flow stays stable

### Files

- `browser_apply.py` → opens a browser, finds a target role on a careers page, fills the application flow, uploads your resume, and either stops before submit or submits if confident

### Install dependencies

```bash
cd /Users/n02/Compensations
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python3 -m playwright install
```

### Required environment variable

Set your Anthropic API key before running:

```bash
export ANTHROPIC_API_KEY="your_anthropic_key_here"
```

### Example usage

Dry run first (recommended):

```bash
python3 browser_apply.py \
  --career-url "https://jobs.ashbyhq.com/company" \
  --job-title "Software Engineer" \
  --resume /Users/n02/Documents/resume.pdf \
  --candidate-notes "LinkedIn: https://linkedin.com/in/yourname; Notice period: 30 days; Work authorization: India" \
  --location-hint "Bengaluru" \
  --dry-run
```

Attempt full submission:

```bash
python3 browser_apply.py \
  --career-url "https://jobs.ashbyhq.com/company" \
  --job-title "Software Engineer" \
  --resume /Users/n02/Documents/resume.pdf \
  --candidate-notes "LinkedIn: https://linkedin.com/in/yourname; Notice period: 30 days; Work authorization: India"
```

### How it works

The script:

1. Opens the supplied career page
2. Finds the best matching job title
3. Starts the application flow
4. Uploads your resume
5. Fills known fields from your resume + `--candidate-notes`
6. Stops and reports blockers if a field cannot be answered truthfully
7. In `--dry-run` mode, stops at the final submit/review step

### Recommended usage pattern

- Start with `--dry-run` for every new company portal
- Add structured details in `--candidate-notes` such as:
  - LinkedIn URL
  - GitHub / portfolio
  - notice period
  - work authorization
  - current location
  - salary expectation
- Only allow final submission after verifying the portal behavior on that site

### Notes / caveats

- Some sites add CAPTCHAs or anti-bot checks that may require manual intervention
- Success rate varies by portal structure and validation rules
- The script is intentionally standalone and does **not** yet batch-apply across many companies
- For safety, `--dry-run` is the recommended default workflow

### Assumptions made

- You want a minimal integration into the current Python repo, not a full desktop app flow
- Anthropic is your preferred LLM provider for this browser automation step
- Resume path will be provided explicitly as an absolute file path

### Troubleshooting

- If you see `ModuleNotFoundError: No module named 'browser_use'`, make sure you installed dependencies from the same Python environment you are using to run the script.
- The correct package name is `browser-use` in `requirements.txt`, while the import remains `from browser_use import Agent`.
