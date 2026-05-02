# workeasy

A central repository for all personal automation scripts, scheduled jobs, and launchd agents.

Everything that runs automatically on my machine lives here — organized, documented, and ready to be set up on any new device.

---

## What's in here

| Folder | What it does | Runs via |
|---|---|---|
| [`naukri/`](./naukri/) | Daily Naukri resume upload + daily digest email (job tracker + comp data) | launchd (2 jobs) |
| [`job-tracker/`](./job-tracker/) | Scrapes LinkedIn for new backend SWE jobs at target companies → daily PDF | called by `naukri/run_reports.py` |
| [`compensations/`](./compensations/) | Scrapes LeetCode Discuss comp posts, AI-extracts data → PDF report | called by `naukri/run_reports.py` |
| [`launchd/`](./launchd/) | All macOS launchd plist files + install/manage instructions | macOS launchd |

---

## How the daily automation works

```
Every day at 22:00 IST
  └── launchd: com.naukri.refresh
        └── naukri/run_daily.py
              └── naukri_resume_refresh.py  →  uploads Resume.pdf to Naukri

Every day at 18:00 IST
  └── launchd: com.daily.reports
        └── naukri/run_reports.py
              ├── job-tracker/run.py        →  scrapes LinkedIn → data/runs/YYYY-MM-DD.pdf
              └── compensations/run_all.py  →  scrapes LeetCode → compensation_report_*.pdf
              └── emails both PDFs to you
```

Both jobs also run at login/startup as a catch-up mechanism (if the machine was off at the scheduled time).

---

## Setting up on a new machine

### 1. Clone this repo

```bash
cd ~
git clone https://github.com/NeelkanthSingh/workeasy.git
```

### 2. Clone / restore the actual project directories

The scripts here reference these absolute paths on the machine:

| Project | Expected path |
|---|---|
| Naukri suite | `~/dsa/Naukri/` |
| Job tracker | `~/job-tracker/` |
| Compensations | `~/Compensations/` |

Copy the source files from this repo into those locations, then set up each project's Python venv:

```bash
# Naukri
mkdir -p ~/dsa/Naukri && cp ~/workeasy/naukri/* ~/dsa/Naukri/
cd ~/dsa/Naukri && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env  # then fill in real values

# Job tracker
mkdir -p ~/job-tracker && cp ~/workeasy/job-tracker/* ~/job-tracker/
cd ~/job-tracker && python3 -m venv venv && source venv/bin/activate && pip install -r requirements.txt

# Compensations
mkdir -p ~/Compensations && cp ~/workeasy/compensations/* ~/Compensations/
cd ~/Compensations && python3 -m venv venv && source venv/bin/activate && pip install -r requirements.txt
```

### 3. Add your secrets

Each project needs a `.env` file. Use the provided `.env.example` as a template:

```bash
cp ~/dsa/Naukri/.env.example ~/dsa/Naukri/.env
# Edit ~/dsa/Naukri/.env with real SMTP credentials, email address, etc.
```

### 4. Seed the Naukri session

Follow the instructions in [`naukri/README.md`](./naukri/README.md) to seed your Naukri session cookie.

### 5. Install launchd jobs

```bash
cp ~/workeasy/launchd/com.naukri.refresh.plist ~/Library/LaunchAgents/
cp ~/workeasy/launchd/com.daily.reports.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.naukri.refresh.plist
launchctl load ~/Library/LaunchAgents/com.daily.reports.plist
```

See [`launchd/README.md`](./launchd/README.md) for full launchd management instructions.

---

## What is NOT in this repo

| Item | Why excluded |
|---|---|
| `.env` files | Contain real SMTP credentials, API keys |
| `.session.json` | Contains live Naukri auth cookies |
| `Resume.pdf` | Personal document |
| `data/`, `logs/` | Runtime output — not source code |
| `venv/`, `.venv/` | Regenerated on each machine |
| Raw JSON / PDF outputs | Generated on each run |

---

## Projects at a glance

### naukri/ — Naukri Resume Refresh + Daily Digest

Keeps your Naukri profile fresh and emails you a daily digest of job opportunities.

- **Resume upload:** `run_daily.py` → `naukri_resume_refresh.py` — uploads `Resume.pdf` daily
- **Daily digest:** `run_reports.py` — runs job-tracker and compensations, emails both PDFs
- **Self-renewing auth:** the script replicates browser cookie renewal, so it runs without manual intervention
- **Failure emails:** if anything breaks, you get a failure email automatically

→ Full details: [`naukri/README.md`](./naukri/README.md)

---

### job-tracker/ — LinkedIn Job Scraper

Scrapes LinkedIn daily for new Software Engineer backend jobs at a list of target India-hiring companies.

- Tracks seen job IDs to avoid duplicates across runs
- Auto-resolves LinkedIn company IDs (cached, no manual work)
- Outputs a dated PDF: `data/runs/YYYY-MM-DD.pdf`
- Called automatically by `naukri/run_reports.py` every day at 18:00 IST

→ Full details: [`job-tracker/README.md`](./job-tracker/README.md)

---

### compensations/ — India Tech Compensation Tracker

Scrapes LeetCode Discuss for India compensation posts, extracts structured data with AI, and generates a sorted PDF.

- Fetches posts via LeetCode's public GraphQL API
- AI extraction: company, level, YOE, CTC (LPA), notes
- Generates a landscape PDF sorted by CTC descending
- Also includes `browser_apply.py`: a Browser Use script for programmatic job applications on career portals (Workday, Greenhouse, Lever, etc.)
- Called automatically by `naukri/run_reports.py` every day at 18:00 IST

→ Full details: [`compensations/README.md`](./compensations/README.md)

---

### launchd/ — macOS Scheduled Jobs

All plist files for launchd agents, with full install/unload/manage instructions.

| Job | Schedule |
|---|---|
| `com.naukri.refresh` | Daily 22:00 IST + on login |
| `com.daily.reports` | Daily 18:00 IST + on login |

→ Full details: [`launchd/README.md`](./launchd/README.md)
