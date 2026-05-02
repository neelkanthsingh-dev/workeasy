"""
run_reports.py
Daily 6 PM IST automation for Job Tracker and Compensation reports.

Scheduling model (time-window gating):
  - launchd fires this script at 18:00 IST daily AND on every login/startup
    (RunAtLoad=true).
  - On each trigger we compute the "eligible scheduled date":
      * If local IST time is BEFORE 18:00 → eligible date = yesterday
        (today's window has not opened yet; do not run early)
      * If local IST time is AT or AFTER 18:00 → eligible date = today
  - If the eligible date already has a recorded success → exit silently.
  - If a run is already in progress (lock file exists) → exit silently.
  - Otherwise → acquire lock, run pipelines, write state, release lock.

Practical effect:
  - Laptop open at 4 PM  → eligible = yesterday → already done → exits
  - launchd fires at 6 PM → eligible = today → runs once, sends email
  - Machine was off at 6 PM, opened at 8 PM → eligible = today → runs once
  - Reopened at 9 PM after success → eligible = today → already done → exits

Pipelines:
  - Job Tracker: /Users/n02/job-tracker/run.py --hours 24 --reset-seen
    (--reset-seen ensures the daily report always shows ALL jobs from the last
     24h, regardless of any earlier runs on the same day)
  - Compensations: /Users/n02/Compensations/run_all.py --pages 2 --per-page 10

SMTP credentials are shared from Naukri/.env
"""

import json
import os
import smtplib
import subprocess
import sys
import time
from datetime import date, datetime, timedelta, timezone
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from zoneinfo import ZoneInfo

# ── Paths ──────────────────────────────────────────────────────────────────────
SCRIPT_DIR = Path(__file__).parent
STATE_FILE = SCRIPT_DIR / "logs" / "reports_state.json"
LOG_FILE   = SCRIPT_DIR / "logs" / "reports.log"
ERR_FILE   = SCRIPT_DIR / "logs" / "reports.err.log"

JOB_TRACKER_DIR    = Path("/Users/n02/job-tracker")
JOB_TRACKER_PY     = JOB_TRACKER_DIR / "venv" / "bin" / "python"
JOB_TRACKER_SCRIPT = JOB_TRACKER_DIR / "run.py"

COMP_DIR    = Path("/Users/n02/Compensations")
COMP_PY     = COMP_DIR / "venv" / "bin" / "python"
COMP_SCRIPT = COMP_DIR / "run_all.py"

MAX_RETRIES = 1    # one retry per pipeline after initial failure
RETRY_WAIT  = 30   # seconds to wait before retrying a failed pipeline

# ── Scheduling constants ───────────────────────────────────────────────────────
IST            = ZoneInfo("Asia/Kolkata")
SCHEDULE_HOUR  = 18   # 6 PM IST — the window opens at this hour
LOCK_FILE      = SCRIPT_DIR / "logs" / "reports.lock"

# ── Subprocess environment ─────────────────────────────────────────────────────
# launchd provides a minimal PATH that excludes /opt/homebrew/bin (where pandoc lives).
# We extend PATH explicitly so child processes can find pandoc, chrome, etc.
_SUBPROCESS_ENV = {
    **os.environ,
    "PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:" + os.environ.get("PATH", ""),
}


# ── Logging ────────────────────────────────────────────────────────────────────
def _ts() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def log(msg: str) -> None:
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    LOG_FILE.open("a").write(f"[{_ts()}] {msg}\n")
    print(msg)


def log_err(msg: str) -> None:
    ERR_FILE.parent.mkdir(parents=True, exist_ok=True)
    ERR_FILE.open("a").write(f"[{_ts()}] {msg}\n")
    print(msg, file=sys.stderr)


# ── Env / State ────────────────────────────────────────────────────────────────
def load_env() -> dict:
    env_file = SCRIPT_DIR / ".env"
    env: dict = {}
    if not env_file.exists():
        return env
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        env[k.strip()] = v.strip()
    return env


def eligible_scheduled_date() -> date:
    """
    Return the date for which reports should run right now.

    The 6 PM IST window gates execution:
      - Before 18:00 IST → eligible date is yesterday
        (today's window hasn't opened; a RunAtLoad trigger should not run early)
      - At/after 18:00 IST → eligible date is today
    """
    now_ist = datetime.now(IST)
    if now_ist.hour < SCHEDULE_HOUR:
        return (now_ist - timedelta(days=1)).date()
    return now_ist.date()


def already_ran(target_date: date) -> bool:
    """Return True if we already have a recorded success for target_date."""
    try:
        data = json.loads(STATE_FILE.read_text())
        return data.get("last_success_date") == target_date.isoformat()
    except Exception:
        return False


def write_state(status: str, scheduled_date: date) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps({
        "last_success_date": scheduled_date.isoformat() if status == "success" else None,
        "scheduled_date": scheduled_date.isoformat(),
        "last_attempt_at": datetime.now(timezone.utc).isoformat(),
        "last_status": status,
    }, indent=2))


def acquire_lock() -> bool:
    """
    Create a lock file containing this process's PID.
    Returns True if the lock was acquired, False if another run is in progress.

    Stale locks (PID no longer running) are automatically cleared.
    """
    LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
    if LOCK_FILE.exists():
        try:
            pid = int(LOCK_FILE.read_text().strip())
            # Check if PID is still alive (signal 0 = no-op, just checks existence)
            os.kill(pid, 0)
            return False   # process is alive → another run is in progress
        except (ValueError, ProcessLookupError, PermissionError):
            # PID file is corrupt or process is gone → stale lock, clear it
            LOCK_FILE.unlink(missing_ok=True)
    LOCK_FILE.write_text(str(os.getpid()))
    return True


def release_lock() -> None:
    LOCK_FILE.unlink(missing_ok=True)


# ── Email helpers ───────────────────────────────────────────────────────────────
def _smtp_cfg(env: dict) -> tuple[str, int, str, str, str, str]:
    host     = env.get("SMTP_HOST", "smtp.gmail.com")
    port     = int(env.get("SMTP_PORT", "587"))
    username = env.get("SMTP_USERNAME", "")
    password = env.get("SMTP_PASSWORD", "")
    from_    = env.get("SMTP_FROM", username)
    to_      = env.get("ALERT_EMAIL_TO", username)
    return host, port, username, password, from_, to_


def send_success_email(pdf_paths: list[Path], env: dict) -> None:
    host, port, username, password, from_, to_ = _smtp_cfg(env)

    if not username or not password or not to_:
        log_err("SMTP not configured — skipping success email.")
        return

    today = date.today().strftime("%d %b %Y")
    msg = MIMEMultipart()
    msg["Subject"] = f"Daily Reports — {today}"
    msg["From"]    = from_
    msg["To"]      = to_

    body_lines = [
        "Hi,\n",
        f"Here are your daily automated reports for {today}:\n",
    ]
    for p in pdf_paths:
        body_lines.append(f"  • {p.name}")
    body_lines += [
        "",
        "Both PDFs are attached.",
        "",
        "— Daily Reports Bot",
    ]
    msg.attach(MIMEText("\n".join(body_lines), "plain", "utf-8"))

    for pdf in pdf_paths:
        if not pdf.exists():
            log_err(f"PDF not found, skipping attachment: {pdf}")
            continue
        part = MIMEBase("application", "octet-stream")
        part.set_payload(pdf.read_bytes())
        encoders.encode_base64(part)
        part.add_header("Content-Disposition", f'attachment; filename="{pdf.name}"')
        msg.attach(part)

    try:
        with smtplib.SMTP(host, port, timeout=30) as smtp:
            smtp.ehlo()
            smtp.starttls()
            smtp.ehlo()
            smtp.login(username, password)
            smtp.sendmail(from_, [to_], msg.as_string())
        log(f"Success email sent to {to_} with {len(pdf_paths)} attachment(s).")
    except Exception as e:
        log_err(f"Could not send success email: {e}")


def send_failure_email(error_details: str, env: dict) -> None:
    host, port, username, password, from_, to_ = _smtp_cfg(env)

    if not username or not password or not to_:
        log_err("SMTP not configured — skipping failure email.")
        return

    today = date.today().strftime("%d %b %Y")
    body = (
        f"Daily reports run FAILED on {today} at {_ts()}\n\n"
        f"All retries exhausted.\n\n"
        f"--- Error details ---\n{error_details.strip()}\n\n"
        f"--- What to do ---\n"
        f"Check the logs:\n"
        f"  {LOG_FILE}\n"
        f"  {ERR_FILE}\n\n"
        f"To re-run manually:\n"
        f"  cd {SCRIPT_DIR}\n"
        f"  .venv/bin/python run_reports.py\n"
    )

    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = f"Daily Reports FAILED — {today}"
    msg["From"]    = from_
    msg["To"]      = to_

    try:
        with smtplib.SMTP(host, port, timeout=30) as smtp:
            smtp.ehlo()
            smtp.starttls()
            smtp.ehlo()
            smtp.login(username, password)
            smtp.sendmail(from_, [to_], msg.as_string())
        log(f"Failure email sent to {to_}")
    except Exception as e:
        log_err(f"Could not send failure email: {e}")


# ── Pipeline runners ────────────────────────────────────────────────────────────
def _run_job_tracker() -> tuple[bool, str, Path | None]:
    """
    Run job tracker for last 24 hours with --reset-seen.

    --reset-seen archives today's seen_jobs.json and starts fresh so the daily
    report always shows ALL jobs from the past 24 hours, regardless of any
    earlier runs on the same day (e.g. manual or debugging runs).
    """
    result = subprocess.run(
        [str(JOB_TRACKER_PY), str(JOB_TRACKER_SCRIPT), "--hours", "24", "--reset-seen"],
        capture_output=True,
        text=True,
        cwd=str(JOB_TRACKER_DIR),
        env=_SUBPROCESS_ENV,
    )
    output = result.stdout + result.stderr
    if result.returncode != 0:
        return False, output, None

    today_pdf = JOB_TRACKER_DIR / "data" / "runs" / f"{date.today().isoformat()}.pdf"
    if not today_pdf.exists():
        return False, output + f"\nPDF not found at: {today_pdf}", None

    return True, output, today_pdf


def _run_compensations() -> tuple[bool, str, Path | None]:
    """Run compensation pipeline (2 pages x 10). Returns (success, output, pdf_path)."""
    before = datetime.now().timestamp()

    result = subprocess.run(
        [str(COMP_PY), str(COMP_SCRIPT), "--pages", "2", "--per-page", "10"],
        capture_output=True,
        text=True,
        cwd=str(COMP_DIR),
        env=_SUBPROCESS_ENV,
    )
    output = result.stdout + result.stderr
    if result.returncode != 0:
        return False, output, None

    # Find newest compensation_report_*.pdf created after this run started
    candidates = sorted(
        (p for p in COMP_DIR.glob("compensation_report_*.pdf")
         if p.stat().st_mtime >= before),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if not candidates:
        return False, output + "\nNo compensation PDF found after run.", None

    return True, output, candidates[0]


def run_pipeline_with_retry(
    name: str,
    runner_fn,
) -> tuple[bool, str, Path | None]:
    """
    Run a pipeline function with up to MAX_RETRIES retries.
    Returns (success, last_output, pdf_path_or_None).
    """
    last_output = ""
    for attempt in range(1, MAX_RETRIES + 2):   # 1, 2
        if attempt > 1:
            log(f"  [{name}] Retry {attempt - 1}/{MAX_RETRIES} — waiting {RETRY_WAIT}s …")
            time.sleep(RETRY_WAIT)

        log(f"  [{name}] Attempt {attempt} …")
        ok, output, pdf = runner_fn()
        last_output = output

        for line in output.strip().splitlines():
            log(f"    [{name}] {line}")

        if ok:
            log(f"  [{name}] ✓ Succeeded on attempt {attempt}.")
            return True, output, pdf

        log_err(f"  [{name}] ✗ Attempt {attempt} failed.")

    return False, last_output, None


# ── Main ────────────────────────────────────────────────────────────────────────
def main() -> None:
    log("=== Daily reports triggered ===")

    # ── Time-window gate ────────────────────────────────────────────────────────
    now_ist = datetime.now(IST)
    target  = eligible_scheduled_date()
    log(f"IST now: {now_ist.strftime('%Y-%m-%d %H:%M')} | eligible date: {target} | window opens at {SCHEDULE_HOUR:02d}:00 IST")

    if now_ist.hour < SCHEDULE_HOUR:
        log(f"Before {SCHEDULE_HOUR:02d}:00 IST — window not open yet for today. "
            f"Checking eligible date ({target}) instead.")

    # ── Already succeeded for this date? ───────────────────────────────────────
    if already_ran(target):
        log(f"Reports for {target} already sent successfully. Skipping (no duplicate).")
        return

    # ── Lock guard (prevent parallel runs from RunAtLoad + scheduled trigger) ──
    if not acquire_lock():
        log("Another run is already in progress (lock file active). Exiting.")
        return

    env = load_env()
    errors: list[str] = []
    pdfs: list[Path] = []

    try:
        # ── Job Tracker ─────────────────────────────────────────────────────────
        log("--- Job Tracker (--hours 24) ---")
        jt_ok, jt_out, jt_pdf = run_pipeline_with_retry("job-tracker", _run_job_tracker)
        if jt_ok and jt_pdf:
            pdfs.append(jt_pdf)
        else:
            errors.append(f"[job-tracker]\n{jt_out.strip()}")

        # ── Compensation Tracker ─────────────────────────────────────────────────
        log("--- Compensation Tracker (--pages 2 --per-page 10) ---")
        comp_ok, comp_out, comp_pdf = run_pipeline_with_retry("compensations", _run_compensations)
        if comp_ok and comp_pdf:
            pdfs.append(comp_pdf)
        else:
            errors.append(f"[compensations]\n{comp_out.strip()}")

        # ── Outcome ──────────────────────────────────────────────────────────────
        if jt_ok and comp_ok:
            write_state("success", target)
            log(f"Both pipelines succeeded. Sending email with {len(pdfs)} PDF(s).")
            send_success_email(pdfs, env)
        else:
            write_state("failure", target)
            log_err("One or more pipelines failed after all retries. Sending failure email.")
            send_failure_email("\n\n".join(errors), env)
            sys.exit(1)

    finally:
        release_lock()


if __name__ == "__main__":
    main()
