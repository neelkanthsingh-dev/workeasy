import argparse
import json
import random
import re
import sys
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path

import requests

DASHBOARD_URL  = "https://www.naukri.com/cloudgateway-mynaukri/resman-aggregator-services/v0/users/self/dashboard"
PROFILE_URL    = "https://www.naukri.com/mnjuser/profile"
VALIDATION_URL = "https://filevalidation.naukri.com/file"
RESUME_URL_TPL = "https://www.naukri.com/cloudgateway-mynaukri/resman-aggregator-services/v0/users/self/profiles/{pid}/advResume"
# Naukri renews nauk_at silently when the browser loads any page with nauk_sid present.
# We replicate this by hitting the profile page with all saved session cookies.
TOKEN_RENEW_URL = "https://www.naukri.com/mnjuser/profile"

HEADERS = {
    "accept":           "application/json",
    "appid":            "105",
    "clientid":         "d3skt0p",
    "content-type":     "application/json",
    "systemid":         "Naukri",
    "user-agent":       "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "x-requested-with": "XMLHttpRequest",
}

SCRIPT_DIR = Path(__file__).parent


def load_session(path: str) -> dict | None:
    try:
        return json.loads(Path(path).read_text())
    except Exception:
        return None


def save_session(path: str, token: str, all_cookies: dict) -> None:
    payload = {
        "token": token,
        "cookies": all_cookies,
        "saved_at": datetime.now(timezone.utc).isoformat(),
    }
    Path(path).write_text(json.dumps(payload, indent=2))
    print(f"  Session saved → {path}")


def restore_session(session: requests.Session, saved: dict) -> str:
    for k, v in saved.get("cookies", {}).items():
        session.cookies.set(k, v, domain=".naukri.com")
    return saved.get("token", "")


def try_renew_via_page_load(session: requests.Session, saved: dict, session_path: str) -> str | None:
    """
    Replicate what the browser does: load a Naukri page with all session cookies.
    Naukri's server sees nauk_sid + nauk_rt + nauk_ps and issues a fresh nauk_at
    via Set-Cookie in the response. We capture it and save it.

    The browser has this advantage because it stores ALL cookies (nauk_sid, nauk_rt,
    nauk_ps, nauk_otl, PHPSESSID, etc.) and sends them all on every page load.
    That full cookie bundle is what triggers server-side token renewal.
    """
    # Check we have at least nauk_sid (the key session identifier)
    cookies = saved.get("cookies", {})
    if not any(k in cookies for k in ("nauk_sid", "nauk_rt", "PHPSESSID")):
        return None

    try:
        # Use a browser-like Accept header to look like a real page load
        browser_headers = {
            "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.6 Safari/605.1.15",
            "accept-language": "en-US,en;q=0.9",
        }
        res = session.get(TOKEN_RENEW_URL, headers=browser_headers, timeout=15, allow_redirects=True)
        new_token = session.cookies.get("nauk_at")

        if not new_token or not new_token.startswith("eyJ"):
            return None

        all_cookies = {**cookies}
        for k, v in session.cookies.items():
            all_cookies[k] = v  # capture any newly set cookies too

        save_session(session_path, new_token, all_cookies)
        print("  Access token renewed automatically via page load (browser-style).")
        return new_token

    except Exception:
        return None


def is_session_valid(session: requests.Session, token: str) -> bool:
    try:
        res = session.get(DASHBOARD_URL, headers={**HEADERS, "authorization": f"Bearer {token}"}, timeout=10)
        return res.status_code == 200
    except Exception:
        return False


def fetch_profile_id(session: requests.Session, token: str) -> str:
    res = session.get(DASHBOARD_URL, headers={**HEADERS, "authorization": f"Bearer {token}"})
    res.raise_for_status()
    data = res.json()
    pid = data.get("profileId") or data.get("dashBoard", {}).get("profileId")
    if not pid:
        sys.exit("Could not retrieve profile ID. Check your session.")
    return str(pid)


def fetch_form_key(session: requests.Session, token: str) -> str:
    res = session.get(PROFILE_URL, headers={**HEADERS, "authorization": f"Bearer {token}"})
    for url in re.findall(r'<script[^>]+src="([^"]*\.js[^"]*)"', res.text):
        if "mnj" not in url:
            continue
        full_url = ("https:" + url) if url.startswith("//") else url
        try:
            js = session.get(full_url, timeout=10).text
            key = _parse_form_key(js)
            if key:
                return key
        except Exception:
            continue
    try:
        js = session.get("https://static.naukimg.com/s/5/105/j/mnj_v299.min.js", timeout=10).text
        key = _parse_form_key(js)
        if key:
            return key
    except Exception:
        pass
    sys.exit("Could not extract formKey. Naukri JS bundle may have changed.")


def _parse_form_key(js: str) -> str | None:
    m = re.search(r'key:"initUploader".*?d\s*=\s*"([A-Za-z0-9]+)"', js, re.DOTALL)
    if m:
        return m.group(1)
    m = re.search(r'd\s*=\s*"([A-Za-z0-9]{10,})"', js)
    return m.group(1) if m else None


def upload_resume(session: requests.Session, token: str, resume_path: str) -> None:
    pdf_bytes = Path(resume_path).read_bytes()
    if pdf_bytes[:4] != b"%PDF":
        sys.exit(f"Not a valid PDF: {resume_path}")

    form_key = fetch_form_key(session, token)
    file_key = "U" + "".join(random.choices("0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ", k=13))
    filename  = f"resume_{datetime.now().strftime('%d_%b_%Y').lower()}.pdf"

    upload_headers = {
        "accept": "application/json", "appid": "105",
        "origin": "https://www.naukri.com", "referer": "https://www.naukri.com/",
        "systemid": "fileupload", "user-agent": HEADERS["user-agent"],
    }
    print("  Uploading resume …")
    val = session.post(
        VALIDATION_URL, headers=upload_headers,
        files={"file": (filename, BytesIO(pdf_bytes), "application/pdf")},
        data={"formKey": form_key, "fileName": filename, "uploadCallback": "true", "fileKey": file_key},
    )
    if not val.ok:
        sys.exit(f"Upload failed {val.status_code}: {val.text[:200]}")
    try:
        rj = val.json()
        if file_key not in rj:
            file_key = next(iter(rj))
    except Exception:
        pass

    pid = fetch_profile_id(session, token)
    resume_headers = {**HEADERS, "authorization": f"Bearer {token}",
                      "origin": "https://www.naukri.com", "referer": "https://www.naukri.com/mnjuser/profile",
                      "systemid": "105", "x-http-method-override": "PUT"}
    res = session.post(RESUME_URL_TPL.format(pid=pid), headers=resume_headers,
                       json={"textCV": {"formKey": form_key, "fileKey": file_key}})
    if not res.ok:
        sys.exit(f"Resume update failed {res.status_code}: {res.text[:200]}")
    print(f"  ✅ Resume refreshed at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")


def extract_token_from_row(row: str) -> str:
    row = row.strip()
    if row.startswith("eyJ"):
        return row
    parts = re.split(r"\t|\s{2,}", row)
    for p in parts:
        if p.strip().startswith("eyJ"):
            return p.strip()
    sys.exit("Could not find a JWT token in the pasted row. Make sure you copied the full nauk_at cookie row.")


def cmd_reseed(args) -> None:
    token = extract_token_from_row(args.cookie_row)
    print(f"  Token extracted ({len(token)} chars). Validating …")

    session = requests.Session()
    session.cookies.set("nauk_at", token, domain=".naukri.com")

    if not is_session_valid(session, token):
        sys.exit(
            "Token is invalid or expired.\n"
            "Log in to naukri.com in your browser, copy a fresh nauk_at row, and try again."
        )

    # Collect all naukri cookies that were set (includes nauk_rt if the browser sent it)
    all_cookies = {k: v for k, v in session.cookies.items()}
    all_cookies["nauk_at"] = token  # ensure access token is included

    # nauk_rt is not in the nauk_at row — remind user to also paste it if they can
    save_session(args.session, token, all_cookies)
    print("  Session saved. Running refresh …")
    upload_resume(session, token, args.resume)

    missing_renewal = [k for k in ("nauk_sid", "nauk_rt", "nauk_ps", "nauk_otl") if k not in all_cookies]
    if missing_renewal:
        print()
        print(f"  ⚠️  For automatic token renewal, also save these cookies from DevTools:")
        for k in missing_renewal:
            print(f"    .venv/bin/python naukri_resume_refresh.py add-cookie --cookie-row \"PASTE_{k}_ROW\"")
        print("  (Copy each row from DevTools → Application → Cookies → naukri.com)")


def extract_plain_value_from_row(row: str) -> tuple[str, str]:
    """
    Parse a browser cookie row into (name, value).
    Accepts a full tab-separated DevTools row or just a plain value.
    Returns (name, value).
    """
    row = row.strip()
    parts = re.split(r"\t|\s{2,}", row)
    if len(parts) >= 2:
        return parts[0].strip(), parts[1].strip()
    # If only one part, treat the whole thing as the value with unknown name
    return "unknown", row


def cmd_add_cookie(args) -> None:
    """
    Save one or more session cookies (nauk_sid, nauk_rt, nauk_ps, nauk_otl)
    into the existing session file to enable browser-style auto-renewal.

    Each --cookie-row is a full row copied from DevTools, e.g.:
      nauk_sid   abc123   .naukri.com   ...
    or just the value if --name is provided.
    """
    saved = load_session(args.session)
    if not saved:
        sys.exit("No session file found. Run reseed first.")

    name, value = extract_plain_value_from_row(args.cookie_row)

    # If user passed --name explicitly, use that
    if args.name:
        name = args.name

    if name == "unknown":
        sys.exit(
            "Could not determine cookie name from the pasted row.\n"
            "Use --name to specify it, e.g.: --name nauk_sid --cookie-row \"VALUE\""
        )

    saved.setdefault("cookies", {})[name] = value
    Path(args.session).write_text(json.dumps(saved, indent=2))
    print(f"  Cookie '{name}' saved → session file updated.")

    # Show which session-renewal cookies are now present
    have = [k for k in ("nauk_sid", "nauk_rt", "nauk_ps", "nauk_otl") if k in saved["cookies"]]
    missing = [k for k in ("nauk_sid", "nauk_rt", "nauk_ps", "nauk_otl") if k not in saved["cookies"]]
    if have:
        print(f"  Present  : {', '.join(have)}")
    if missing:
        print(f"  Still missing (optional but helpful): {', '.join(missing)}")
    else:
        print("  All session renewal cookies saved — auto-renewal should work.")


def cmd_refresh(args) -> None:
    saved = load_session(args.session)
    if not saved:
        sys.exit(
            "No saved session found.\n"
            'Run:  python naukri_resume_refresh.py reseed --cookie-row "PASTE_ROW"'
        )

    session = requests.Session()
    token = restore_session(session, saved)

    print("Checking session …")
    if not is_session_valid(session, token):
        # Try to renew the way the browser does: send all session cookies to a Naukri page
        print("  Access token expired. Attempting browser-style renewal …")
        token = try_renew_via_page_load(session, saved, args.session)

        if not token:
            sys.exit(
                "Session expired and could not be renewed automatically.\n"
                "This usually means nauk_sid is missing from the saved session.\n"
                'Run:  python naukri_resume_refresh.py reseed --cookie-row "PASTE_ROW"\n'
                "Then also copy and save these additional cookie rows from DevTools:\n"
                "  nauk_sid, nauk_rt, nauk_ps, nauk_otl"
            )

        session.cookies.set("nauk_at", token, domain=".naukri.com")

        if not is_session_valid(session, token):
            sys.exit(
                "Session could not be renewed.\n"
                'Run:  python naukri_resume_refresh.py reseed --cookie-row "PASTE_ROW"'
            )

    print("Session valid. Refreshing …")
    upload_resume(session, token, args.resume)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Naukri daily resume refresh")
    p.add_argument("--resume",  default=str(SCRIPT_DIR / "Resume.pdf"),    help="Path to PDF resume")
    p.add_argument("--session", default=str(SCRIPT_DIR / ".session.json"), help="Path to session file")

    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("refresh", help="Refresh resume using saved session (auto-renews if expired)")

    rs = sub.add_parser("reseed", help="Save a new session from a copied nauk_at browser cookie row")
    rs.add_argument("--cookie-row", required=True,
                    help="Full nauk_at cookie row from browser DevTools (or just the JWT value)")

    ac = sub.add_parser("add-cookie",
                        help="Save a session cookie (nauk_sid/nauk_rt/nauk_ps/nauk_otl) for auto-renewal")
    ac.add_argument("--cookie-row", required=True,
                    help="Full cookie row from DevTools, or just the value with --name")
    ac.add_argument("--name", default=None,
                    help="Cookie name (e.g. nauk_sid) — only needed if pasting a bare value")
    return p


def main() -> None:
    args = build_parser().parse_args()

    if not Path(args.resume).exists():
        sys.exit(f"Resume not found: {args.resume}")

    if args.command == "refresh":
        cmd_refresh(args)
    elif args.command == "reseed":
        cmd_reseed(args)
    elif args.command == "add-cookie":
        cmd_add_cookie(args)


if __name__ == "__main__":
    main()
