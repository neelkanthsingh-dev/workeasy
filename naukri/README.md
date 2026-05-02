# Naukri Resume Refresh

Uploads your resume to Naukri every day so your profile stays fresh and visible to recruiters.

---

## How it works

- **launchd** runs `run_daily.py` every day at **22:00 IST** automatically.
- If your laptop was off at 22:00, it catches up on the next login or startup.
- No duplicate uploads — `logs/state.json` tracks today's run.
- If refresh fails for any reason, a failure email is sent to `neelkanthsingh.jr@gmail.com`.

The launchd job is already installed and the session is fully set up. **No action needed on normal days.**

> **How token renewal works:** Naukri's `nauk_at` access token expires every 1 hour.
> The script now replicates what the browser does — it sends all saved session cookies
> (`nauk_sid`, `nauk_rt`, `nauk_ps`) to a Naukri page, and the server issues a fresh `nauk_at`
> automatically. This means **the script is self-renewing and should run without manual intervention**.

---

## If you get a failure email

This means auto-renewal failed (usually Naukri invalidated the long-lived session — happens after
weeks/months, or after you log out and back in).

### Step 1 — Get fresh cookies
1. Open [https://www.naukri.com](https://www.naukri.com) in your browser — log in if needed
2. Open DevTools: `F12` or `Cmd + Option + I`
3. Go to **Application** → **Cookies** → `https://www.naukri.com`

### Step 2 — Reseed the access token
Copy the `nauk_at` row and run:

```bash
cd /Users/n02/dsa/Naukri
.venv/bin/python naukri_resume_refresh.py reseed --cookie-row "PASTE_nauk_at_ROW"
```

### Step 3 — Re-save the session cookies (for auto-renewal)
Copy these rows one by one and run `add-cookie` for each:

```bash
.venv/bin/python naukri_resume_refresh.py add-cookie --cookie-row "PASTE_nauk_sid_ROW"
.venv/bin/python naukri_resume_refresh.py add-cookie --cookie-row "PASTE_nauk_rt_ROW"
.venv/bin/python naukri_resume_refresh.py add-cookie --cookie-row "PASTE_nauk_ps_ROW"
```

That's it — the script will be self-renewing again.

---

## Manual daily run (optional)

```bash
cd /Users/n02/dsa/Naukri
.venv/bin/python naukri_resume_refresh.py refresh
```

---

## launchd job management

The job is already installed and active. Use these only if needed.

```bash
# Check it is loaded
launchctl list | grep naukri

# Trigger manually (for testing)
launchctl start com.naukri.refresh

# Disable
launchctl unload ~/Library/LaunchAgents/com.naukri.refresh.plist

# Re-enable (e.g. after a macOS update)
cp /Users/n02/dsa/Naukri/com.naukri.refresh.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.naukri.refresh.plist
```

> **Note:** The launchd job runs and exits quickly. It does not stay running in the background and uses no CPU or memory between runs.

---

## Logs

| File | Contents |
|---|---|
| `logs/refresh.log` | Normal run output |
| `logs/refresh.err.log` | Failures and errors |
| `logs/state.json` | Today's run state (prevents duplicate uploads) |
| `logs/launchd.log` | Raw launchd stdout |
| `logs/launchd.err.log` | Raw launchd stderr |

---

## Possible causes if it still fails after reseeding

| Symptom | Likely cause |
|---|---|
| `Session expired and could not be renewed` | nauk_sid / nauk_rt missing — run add-cookie for each |
| `Token is invalid or expired` | Stale cookie — log out/in and copy fresh rows |
| `Could not extract formKey` | Naukri updated their JS bundle — extraction regex needs updating |
| `Upload failed 403` | Backend session check failed — try reseeding again |
| `Resume update failed 4xx` | Profile API changed — check Naukri for breaking changes |
| Failure email not received | Check `Naukri/.env` SMTP config; verify Gmail App Password is correct |

---

## Files

| File | Purpose |
|---|---|
| `naukri_resume_refresh.py` | Core: refresh / reseed / add-cookie commands |
| `run_daily.py` | Scheduler wrapper: state, dedup, logs, failure email |
| `com.naukri.refresh.plist` | launchd job definition (22:00 IST Naukri refresh) |
| `run_reports.py` | Daily 6 PM IST report runner: job-tracker + compensations PDFs emailed |
| `com.daily.reports.plist` | launchd job definition (18:00 IST daily reports) |
| `.env` | SMTP credentials (gitignored) — shared by both jobs |
| `.env.example` | Template to recreate `.env` |
| `Resume.pdf` | Your resume — replace this file to change what gets uploaded |
| `.session.json` | Saved Naukri session + all renewal cookies (gitignored) |
| `logs/state.json` | Tracks last successful Naukri refresh date |
| `logs/reports_state.json` | Tracks last successful daily reports send date |
| `.venv/` | Python virtual environment |

---

## Daily Reports (6 PM IST)

A second automated job runs every day at **18:00 IST** and:

1. Runs **Job Tracker** (`/Users/n02/job-tracker`) with a **24-hour window** → produces `data/runs/YYYY-MM-DD.pdf`
2. Runs **Compensation Tracker** (`/Users/n02/Compensations`) with `--pages 2 --per-page 10` → produces `compensation_report_YYYYMMDD_HHMM.pdf`
3. Emails **both PDFs as attachments** to `ALERT_EMAIL_TO` in `.env`
4. Retries once on failure (30 s gap)
5. Sends a **failure email** if both attempts fail
6. **No duplicate sends** — `logs/reports_state.json` ensures each day's digest is sent at most once

### Scheduling model (time-window gating)

The job is fired by launchd both at **18:00 IST** (the scheduled time) and on every **login/startup** (`RunAtLoad=true`). A naive "already ran today?" check would let a login at 4 PM incorrectly trigger the job hours before the scheduled window. Instead, `run_reports.py` uses **time-window gating**:

| Current IST time | Eligible date | Behaviour |
|---|---|---|
| Before 18:00 | Yesterday | Window not open yet — exits if yesterday already succeeded |
| 18:00 or later | Today | Runs if today has not already succeeded |

Practical effect:
- **Open laptop at 4 PM** → eligible = yesterday → already done → exits immediately ✓
- **6 PM trigger (launchd)** → eligible = today → runs once, sends email ✓
- **Machine was off at 6 PM, opened at 8 PM** → eligible = today → runs once ✓
- **Reopened at 9 PM** after success → eligible = today → already done → exits ✓

A **lock file** (`logs/reports.lock`) prevents two concurrent instances (e.g. a `RunAtLoad` trigger racing with the scheduled 18:00 trigger). Stale locks are auto-cleared on startup.

### Log files

| File | Contents |
|---|---|
| `logs/reports.log` | Normal run output |
| `logs/reports.err.log` | Failures and errors |
| `logs/reports_state.json` | Today's send state (prevents duplicate emails) |
| `logs/reports_launchd.log` | Raw launchd stdout |
| `logs/reports_launchd.err.log` | Raw launchd stderr |

### launchd job management

The job is already installed and active. Use these only if needed.

```bash
# Check it is loaded
launchctl list | grep daily.reports

# Trigger manually (for testing — will skip if already sent today)
launchctl start com.daily.reports

# Manual run (bypasses dedup — useful for debugging)
cd /Users/n02/dsa/Naukri
.venv/bin/python run_reports.py

# Disable
launchctl unload ~/Library/LaunchAgents/com.daily.reports.plist

# Re-enable (e.g. after a macOS update)
cp /Users/n02/dsa/Naukri/com.daily.reports.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.daily.reports.plist
```

> **Note:** If you want to force a re-send for today (e.g. to test email delivery), delete or reset `logs/reports_state.json`, then run `launchctl start com.daily.reports`.
