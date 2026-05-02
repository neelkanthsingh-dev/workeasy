# launchd Jobs

All personal macOS launchd agents live here. These are the jobs that run automatically on this machine.

---

## Active Jobs

| Label | Plist file | Schedule | What it does |
|---|---|---|---|
| `com.naukri.refresh` | `com.naukri.refresh.plist` | Daily at **22:00 IST** + on login | Uploads resume to Naukri |
| `com.daily.reports` | `com.daily.reports.plist` | Daily at **18:00 IST** + on login | Runs job-tracker + compensations → emails PDFs |

---

## Installing on a new machine (one-time setup)

Copy the plist files to `~/Library/LaunchAgents/` and load them:

```bash
cp ~/workeasy/launchd/com.naukri.refresh.plist ~/Library/LaunchAgents/
cp ~/workeasy/launchd/com.daily.reports.plist ~/Library/LaunchAgents/

launchctl load ~/Library/LaunchAgents/com.naukri.refresh.plist
launchctl load ~/Library/LaunchAgents/com.daily.reports.plist
```

> **Note:** The plist files reference absolute paths like `/Users/n02/dsa/Naukri/...`.
> If your username or project layout is different, update the paths inside the plist before loading.

---

## Verifying jobs are loaded

```bash
launchctl list | grep -E "naukri|daily.reports"
```

You should see both labels listed. A `-` in the PID column means the job is not currently running (normal between scheduled runs).

---

## Manually triggering a job

```bash
# Trigger Naukri resume refresh now
launchctl start com.naukri.refresh

# Trigger daily reports now
launchctl start com.daily.reports
```

---

## Disabling / unloading a job

```bash
launchctl unload ~/Library/LaunchAgents/com.naukri.refresh.plist
launchctl unload ~/Library/LaunchAgents/com.daily.reports.plist
```

---

## Re-enabling after a macOS update

Sometimes macOS updates unload agents. Re-enable with:

```bash
launchctl load ~/Library/LaunchAgents/com.naukri.refresh.plist
launchctl load ~/Library/LaunchAgents/com.daily.reports.plist
```

---

## Log files

Logs are written to the project directories (not committed to git):

| Job | Logs location |
|---|---|
| `com.naukri.refresh` | `~/dsa/Naukri/logs/launchd.log` + `launchd.err.log` |
| `com.daily.reports` | `~/dsa/Naukri/logs/reports_launchd.log` + `reports_launchd.err.log` |
