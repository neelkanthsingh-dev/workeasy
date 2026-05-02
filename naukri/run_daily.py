"""
run_daily.py
Scheduler-safe wrapper around naukri_resume_refresh.py.

Behavior:
  - Called daily at 22:00 IST by launchd AND on every login/startup.
  - Checks logs/state.json to see if today's refresh already succeeded.
  - If yes → exits silently (no duplicate uploads).
  - If no  → runs refresh, logs output, updates state.
  - On failure → sends one plain SMTP email with the error.
  - Handles "laptop was off at 10pm" automatically: next login catches up.

Setup:
  1. Copy .env.example → .env and fill SMTP credentials.
  2. Load launchd job: launchctl load ~/Library/LaunchAgents/com.naukri.refresh.plist
"""

import json
import os
import smtplib
import subprocess
import sys
from datetime import date, datetime, timezone
from email.mime.text import MIMEText
from pathlib import Path

SCRIPT_DIR  = Path(__file__).parent
STATE_FILE  = SCRIPT_DIR / "logs" / "state.json"
LOG_FILE    = SCRIPT_DIR / "logs" / "refresh.log"
ERR_FILE    = SCRIPT_DIR / "logs" / "refresh.err.log"
VENV_PYTHON = SCRIPT_DIR / ".venv" / "bin" / "python"
REFRESH_SCRIPT = SCRIPT_DIR / "naukri_resume_refresh.py"


def load_env() -> dict:
    env_file = SCRIPT_DIR / ".env"
    env = {}
    if not env_file.exists():
        return env
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        env[k.strip()] = v.strip()
    return env


def already_ran_today() -> bool:
    try:
        data = json.loads(STATE_FILE.read_text())
        return data.get("last_success_date") == date.today().isoformat()
    except Exception:
        return False


def write_state(status: str) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps({
        "last_success_date": date.today().isoformat() if status == "success" else None,
        "last_attempt_at": datetime.now(timezone.utc).isoformat(),
        "last_status": status,
    }, indent=2))


def log(msg: str) -> None:
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}\n"
    LOG_FILE.open("a").write(line)
    print(msg)


def log_err(msg: str) -> None:
    ERR_FILE.parent.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    ERR_FILE.open("a").write(f"[{ts}] {msg}\n")
    print(msg, file=sys.stderr)


def send_failure_email(error_output: str, env: dict) -> None:
    host     = env.get("SMTP_HOST", "smtp.gmail.com")
    port     = int(env.get("SMTP_PORT", "587"))
    username = env.get("SMTP_USERNAME", "")
    password = env.get("SMTP_PASSWORD", "")
    from_    = env.get("SMTP_FROM", username)
    to_      = env.get("ALERT_EMAIL_TO", username)

    if not username or not password or not to_:
        log_err("SMTP not configured — skipping failure email.")
        return

    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    body = (
        f"Naukri resume refresh FAILED at {ts}\n\n"
        f"--- Output / Error ---\n{error_output.strip()}\n\n"
        f"--- What to do ---\n"
        f"If the session expired, copy the nauk_at cookie row from your browser\n"
        f"and run:\n\n"
        f"  cd {SCRIPT_DIR}\n"
        f'  .venv/bin/python naukri_resume_refresh.py reseed --cookie-row "PASTE_ROW"\n'
    )

    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = "Naukri refresh failed"
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


def run_refresh() -> tuple[bool, str]:
    result = subprocess.run(
        [str(VENV_PYTHON), str(REFRESH_SCRIPT), "refresh"],
        capture_output=True,
        text=True,
    )
    output = result.stdout + result.stderr
    return result.returncode == 0, output


def main() -> None:
    log("--- Naukri daily refresh triggered ---")

    if already_ran_today():
        log("Already refreshed today. Skipping.")
        return

    env = load_env()
    success, output = run_refresh()

    for line in output.strip().splitlines():
        log(f"  {line}")

    if success:
        write_state("success")
        log("Refresh succeeded.")
    else:
        write_state("failure")
        log_err("Refresh FAILED.")
        send_failure_email(output, env)
        sys.exit(1)


if __name__ == "__main__":
    main()
