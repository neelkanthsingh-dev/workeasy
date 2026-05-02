# Job Tracker

Scrapes LinkedIn daily for new Software Engineer backend jobs at target India-hiring companies.
Outputs a dated PDF for each run. Only shows jobs posted in the last **48 hours** that haven't been seen in any previous run.

---

## Folder Structure

```
job-tracker/
├── README.md              ← You are here
├── run.py                 ← Single entrypoint — run this daily
├── companies.json         ← List of companies to track (edit this to add/remove)
├── requirements.txt       ← Python dependencies
└── data/
    ├── company_ids.json   ← Auto-managed: LinkedIn numeric IDs (do not edit manually)
    ├── seen_jobs.json     ← Auto-managed: all job IDs ever seen (deduplication store)
    └── runs/
        ├── 2026-03-22.md  ← Daily markdown output
        ├── 2026-03-22.pdf ← Daily PDF output
        └── ...
```

---

## One-Time Setup

These steps are done once. After that, just run `run.py` daily.

### 1. Prerequisites (macOS)

```bash
# Install pandoc (for Markdown → HTML conversion)
brew install pandoc

# Google Chrome must be installed at the default path:
# /Applications/Google Chrome.app/
# (Used for HTML → PDF via headless Chrome)
```

### 2. Create Python virtual environment

```bash
cd /Users/n02/job-tracker
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

> **Note:** The venv is named `venv/` and lives inside this folder. It is not committed to git.

---

## Daily Usage

```bash
cd /Users/n02/job-tracker
source venv/bin/activate
python3 run.py
```

That's it. The script will:
1. Load all companies from `companies.json`
2. Auto-resolve any new LinkedIn company IDs (cached in `data/company_ids.json`)
3. Scrape LinkedIn for jobs posted in the last **48 hours**
4. Skip any job already seen in a previous run
5. Write `data/runs/YYYY-MM-DD.md` and `data/runs/YYYY-MM-DD.pdf`
6. Update `data/seen_jobs.json` with newly seen job IDs

**The PDF is the final output.** Open it with:
```bash
open data/runs/$(date +%Y-%m-%d).pdf
```

### CLI Arguments

```
python3 run.py [--hours N] [--reset-seen]
```

| Argument | Default | Description |
|---|---|---|
| `--hours N` | `48` | Look back N hours for jobs. Overrides the default for this run only. |
| `--reset-seen` | off | Archive `seen_jobs.json` → `seen_jobs_YYYY-MM-DD_HH-MM.json`, then start fresh. All jobs will appear new. |

**Examples:**
```bash
# Normal daily run (48h window)
python3 run.py

# Look back 7 days — useful for a catch-up run after a gap
python3 run.py --hours 168

# Archive seen jobs and do a full reset (all jobs appear new again)
python3 run.py --reset-seen

# Full reset with a 3-day window
python3 run.py --reset-seen --hours 72
```

---

## Adding a New Company

Edit `companies.json`. Each entry is a JSON object with two fields:

```json
{ "name": "Razorpay", "search": "Software Engineer backend Python Java" }
```

| Field    | Required | Description |
|----------|----------|-------------|
| `name`   | ✅       | Display name. Must be unique. Used to resolve LinkedIn ID. |
| `search` | ✅       | Keyword string used when searching inside the company's LinkedIn page. |

**Example — adding Flipkart:**
```json
[
  ...existing entries...,
  { "name": "Flipkart", "search": "Software Engineer backend Java Python" }
]
```

On the next run, the script will automatically resolve Flipkart's LinkedIn ID and cache it.

---

## How Deduplication Works

- Every job has a unique LinkedIn job ID (a number in the URL like `/jobs/view/4379428681`).
- After each run, all new job IDs are saved to `data/seen_jobs.json`.
- On the next run, any job ID already in `seen_jobs.json` is silently skipped.
- Result: each daily PDF only contains jobs you haven't seen before.

**To reset and see all jobs again** (e.g. if you want a full refresh):
```bash
rm data/seen_jobs.json
```

---

## How Company IDs Work

LinkedIn has numeric company IDs (e.g. Google = `1441`). Using these IDs pins the search to the exact company page, giving far more accurate results than keyword search alone.

- IDs are auto-resolved on first encounter via LinkedIn's typeahead API.
- Cached permanently in `data/company_ids.json`.
- You never need to edit `company_ids.json` manually.

**To force re-resolve an ID** (e.g. if a company rebranded):
```bash
# Remove the company's entry from company_ids.json
# The next run will re-resolve it automatically
```

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| `ModuleNotFoundError: No module named 'jobspy'` | Run `source venv/bin/activate` first, then retry |
| `pandoc not found` | `brew install pandoc` |
| `Chrome not found` | Install Google Chrome from https://www.google.com/chrome |
| PDF is blank / missing | Check that `data/runs/YYYY-MM-DD.md` was created; open the `.html` version manually |
| 0 jobs for every company | LinkedIn may be rate-limiting; wait 30 min and retry |
| A company returns wrong jobs | Delete its entry from `data/company_ids.json` and re-run; it will re-resolve |

---

## Instructions for an AI Agent Running This

If you are an AI agent tasked with running this and producing a PDF, follow these steps exactly:

```bash
# 1. Navigate to the folder
cd /Users/n02/job-tracker

# 2. Activate the virtual environment
source venv/bin/activate

# 3. Run the tracker (normal daily run)
python3 run.py

# 4. The PDF is at:
#    data/runs/YYYY-MM-DD.pdf   (where YYYY-MM-DD is today's date)

# 5. Open it
open data/runs/$(date +%Y-%m-%d).pdf
```

If the venv doesn't exist yet (first time):
```bash
cd /Users/n02/job-tracker
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python3 run.py
```

**Optional flags you can pass:**
```bash
# Look back further than 48 hours
python3 run.py --hours 72

# Reset seen-jobs history (archive old list, treat everything as new)
python3 run.py --reset-seen

# Both together
python3 run.py --reset-seen --hours 168
```

The script is fully self-contained. It handles everything automatically. You only need to run it.

---

## Settings (in run.py)

| Variable     | Default | Description |
|--------------|---------|-------------|
| `HOURS_OLD`  | `48`    | How far back to look for jobs (hours) |
| `MAX_PER_CO` | `5`     | Max jobs to include per company per run |
| `SLEEP_SECS` | `2.0`   | Delay between company searches (be polite to LinkedIn) |

To change a setting, edit the constant at the top of `run.py`.
