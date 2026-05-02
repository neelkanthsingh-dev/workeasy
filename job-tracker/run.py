#!/usr/bin/env python3
"""
Job Tracker — Daily Runner
===========================
Single entrypoint. Does everything:
  1. Loads companies from companies.json
  2. Auto-resolves any missing LinkedIn company IDs via typeahead API
  3. Scrapes LinkedIn for jobs posted in the last 48 hours
  4. Skips jobs already seen in previous runs (deduplication via seen_jobs.json)
  5. Writes today's results to data/runs/YYYY-MM-DD.md
  6. Exports a PDF to              data/runs/YYYY-MM-DD.pdf
  7. Updates seen_jobs.json with all newly seen job IDs

Run daily with:
    python3 run.py

To add a new company: edit companies.json — no code changes needed.
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import shutil
import subprocess
import time
import warnings
from datetime import date, datetime
from pathlib import Path

import requests

warnings.filterwarnings("ignore")
logging.basicConfig(level=logging.WARNING)

# ── Paths ─────────────────────────────────────────────────────────────────────
ROOT         = Path(__file__).parent
COMPANIES_F  = ROOT / "companies.json"
IDS_F        = ROOT / "data" / "company_ids.json"
SEEN_F       = ROOT / "data" / "seen_jobs.json"
RUNS_DIR     = ROOT / "data" / "runs"

TODAY        = date.today().isoformat()          # e.g. "2026-03-22"
OUT_MD       = RUNS_DIR / f"{TODAY}.md"
OUT_HTML     = RUNS_DIR / f"{TODAY}.html"
OUT_PDF      = RUNS_DIR / f"{TODAY}.pdf"

# ── Settings ──────────────────────────────────────────────────────────────────
DEFAULT_HOURS = 48     # default lookback window (overridable via --hours)
MAX_PER_CO   = 5       # max jobs to include per company per run
SLEEP_SECS   = 2.0     # polite delay between companies
TYPEAHEAD_URL = "https://www.linkedin.com/jobs-guest/api/typeaheadHits"

# ── Helpers ───────────────────────────────────────────────────────────────────

def ensure_dirs():
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    IDS_F.parent.mkdir(parents=True, exist_ok=True)


def load_json(path: Path, default):
    try:
        return json.loads(path.read_text())
    except Exception:
        return default


def save_json(path: Path, data):
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False))


# ── Step 1: Load company list ─────────────────────────────────────────────────

def load_companies() -> list[dict]:
    companies = load_json(COMPANIES_F, [])
    if not companies:
        raise SystemExit(f"❌ {COMPANIES_F} is empty or missing. Add companies first.")
    return companies


# ── Step 2: Resolve LinkedIn company IDs ─────────────────────────────────────

def _linkedin_headers() -> dict:
    """Minimal headers that LinkedIn's guest API accepts."""
    return {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/122.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "en-US,en;q=0.9",
    }


def resolve_company_id(name: str, search_term: str) -> int | None:
    """
    Query LinkedIn typeahead and return the best matching numeric company ID.
    Matching priority:
      1. Exact display name match (case-insensitive)
      2. Display name starts with the first word of search_term
      3. First result as fallback
    """
    try:
        r = requests.get(
            TYPEAHEAD_URL,
            params={"query": name, "typeaheadType": "COMPANY"},
            headers=_linkedin_headers(),
            timeout=10,
        )
        if r.status_code != 200:
            return None
        hits = r.json()
        if not hits:
            return None

        name_lower = name.lower()
        for hit in hits:
            if hit.get("displayName", "").lower() == name_lower:
                return int(hit["id"])
        first_word = name_lower.split()[0]
        for hit in hits:
            if hit.get("displayName", "").lower().startswith(first_word):
                return int(hit["id"])
        return int(hits[0]["id"])
    except Exception:
        return None


def resolve_all_ids(companies: list[dict]) -> dict[str, int]:
    """
    Load cached IDs, resolve any that are missing, and save back.
    Returns: {company_name: linkedin_id}
    """
    ids: dict[str, int] = load_json(IDS_F, {})
    changed = False

    for co in companies:
        name = co["name"]
        if name not in ids or ids[name] is None:
            print(f"  Resolving ID for '{name}'...", end=" ", flush=True)
            cid = resolve_company_id(name, co.get("search", name))
            if cid:
                ids[name] = cid
                print(f"✓ {cid}")
            else:
                ids[name] = None
                print("✗ not found (will search by keyword only)")
            changed = True
            time.sleep(0.5)

    if changed:
        save_json(IDS_F, ids)

    return ids


# ── Step 3: Scrape LinkedIn ───────────────────────────────────────────────────

def scrape_company(name: str, search: str, company_id: int | None, hours_old: int) -> list[dict]:
    """
    Scrape LinkedIn for jobs at this company posted in the last hours_old hours.
    Returns a list of job dicts: {job_id, title, company, location, url}
    """
    try:
        from jobspy import scrape_jobs

        kwargs: dict = dict(
            site_name=["linkedin"],
            search_term=search,
            location="India",
            results_wanted=20,          # fetch more, we'll dedup client-side
            hours_old=hours_old,
            linkedin_fetch_description=False,
        )
        if company_id:
            kwargs["linkedin_company_ids"] = [company_id]

        df = scrape_jobs(**kwargs)
        if df is None or df.empty:
            return []

        results = []
        for _, row in df.iterrows():
            url = str(row.get("job_url", "") or "")
            m = re.search(r"/jobs/view/(\d+)", url)
            job_id = m.group(1) if m else None
            if not job_id:
                continue

            results.append({
                "job_id":   job_id,
                "title":    str(row.get("title", "N/A")),
                "company":  str(row.get("company", name)),
                "location": str(row.get("location", "India")),
                "url":      url,
            })
        return results

    except Exception as e:
        return [{"error": str(e), "job_id": None}]


# ── Step 4: Deduplication ─────────────────────────────────────────────────────

def load_seen() -> set[str]:
    return set(load_json(SEEN_F, []))


def save_seen(seen: set[str]):
    save_json(SEEN_F, sorted(seen))


def archive_seen():
    """
    Move seen_jobs.json → seen_jobs_YYYY-MM-DD_HH-MM.json and start fresh.
    Safe to call even if seen_jobs.json doesn't exist yet.
    """
    if SEEN_F.exists():
        ts = datetime.now().strftime("%Y-%m-%d_%H-%M")
        archive_path = SEEN_F.parent / f"seen_jobs_{ts}.json"
        SEEN_F.rename(archive_path)
        print(f"  📦 Archived seen_jobs.json → {archive_path.name}")
    # Create a fresh empty file
    save_seen(set())
    print("  🆕 seen_jobs.json reset to empty")


# ── Step 5: Markdown formatting ───────────────────────────────────────────────

def format_company_md(name: str, new_jobs: list[dict]) -> str:
    lines = [f"\n## {name}\n"]
    if not new_jobs:
        lines.append("_No new listings in the last 48 hours._\n")
    elif "error" in new_jobs[0]:
        lines.append(f"_Search error: {new_jobs[0]['error']}_\n")
    else:
        lines.append("| Role | Location | Job ID | Link |")
        lines.append("|------|----------|--------|------|")
        for j in new_jobs:
            title = j["title"].replace("|", "\\|")
            loc   = j["location"].replace("|", "\\|")
            link  = f"[Apply]({j['url']})" if j["url"] else "—"
            lines.append(f"| {title} | {loc} | {j['job_id']} | {link} |")
    lines.append("")
    return "\n".join(lines)


# ── Step 6: PDF export ────────────────────────────────────────────────────────

def export_pdf():
    """Convert today's markdown → HTML → PDF via Chrome headless."""
    # Step A: pandoc MD → HTML
    pandoc = shutil.which("pandoc")
    if not pandoc:
        print("  ⚠️  pandoc not found — skipping PDF. Install with: brew install pandoc")
        return

    subprocess.run([
        pandoc, str(OUT_MD),
        "-o", str(OUT_HTML),
        "--standalone",
        f"--metadata=title:Job Hunt — {TODAY}",
    ], check=True, capture_output=True)

    # Step B: Chrome headless HTML → PDF
    chrome_paths = [
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/Applications/Chromium.app/Contents/MacOS/Chromium",
        shutil.which("google-chrome"),
        shutil.which("chromium"),
    ]
    chrome = next((p for p in chrome_paths if p and Path(p).exists()), None)
    if not chrome:
        print("  ⚠️  Chrome/Chromium not found — skipping PDF.")
        return

    subprocess.run([
        chrome,
        "--headless", "--no-sandbox", "--disable-gpu",
        f"--print-to-pdf={OUT_PDF}",
        "--no-pdf-header-footer",
        f"file://{OUT_HTML}",
    ], check=True, capture_output=True)

    size_kb = OUT_PDF.stat().st_size // 1024
    print(f"\n  📕 PDF saved: {OUT_PDF} ({size_kb} KB)")


# ── Main ──────────────────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Job Tracker — scrape LinkedIn for new SWE jobs in India.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python3 run.py                    # normal daily run (48h window)
  python3 run.py --hours 72         # look back 72 hours instead
  python3 run.py --reset-seen       # archive seen_jobs.json, start fresh
  python3 run.py --reset-seen --hours 168   # full reset + 7-day window
        """,
    )
    p.add_argument(
        "--hours",
        type=int,
        default=DEFAULT_HOURS,
        metavar="N",
        help=f"Look back N hours for jobs (default: {DEFAULT_HOURS})",
    )
    p.add_argument(
        "--reset-seen",
        action="store_true",
        help="Archive seen_jobs.json and start fresh (all jobs will appear new)",
    )
    return p.parse_args()


def main():
    args = parse_args()
    hours_old = args.hours

    ensure_dirs()

    print(f"🗓  Job Tracker — {TODAY}  (last {hours_old}h window)\n")

    # 1. Load companies
    companies = load_companies()
    total = len(companies)
    print(f"📋 {total} companies loaded from companies.json")

    # 2. Resolve IDs
    print("\n🔍 Resolving LinkedIn company IDs (new companies only)...")
    ids = resolve_all_ids(companies)

    # 3. Handle --reset-seen before loading
    if args.reset_seen:
        print("⚠️  --reset-seen: archiving seen_jobs.json...")
        archive_seen()
        print()

    # 4. Load seen jobs
    seen: set[str] = load_seen()
    print(f"\n🧠 {len(seen)} job IDs already seen in previous runs\n")

    # 5. Scrape + dedup
    all_new_jobs: list[dict] = []
    md_sections: list[str] = []

    for i, co in enumerate(companies, 1):
        name   = co["name"]
        search = co.get("search", "Software Engineer backend")
        cid    = ids.get(name)

        print(f"[{i}/{total}] {name} (id={cid})...", end=" ", flush=True)

        raw = scrape_company(name, search, cid, hours_old)

        # Filter out already-seen job IDs
        new_jobs = [
            j for j in raw
            if j.get("job_id") and j["job_id"] not in seen
            and "error" not in j
        ][:MAX_PER_CO]

        # Track errors separately
        errors = [j for j in raw if "error" in j]
        display_jobs = new_jobs if new_jobs else (errors[:1] if errors else [])

        print(f"✓ {len(new_jobs)} new job(s)  (fetched {len(raw)}, skipped {len(raw)-len(new_jobs)-len(errors)})")

        md_sections.append(format_company_md(name, display_jobs))
        all_new_jobs.extend(new_jobs)

        # Mark as seen immediately
        for j in new_jobs:
            seen.add(j["job_id"])

        time.sleep(SLEEP_SECS)

    # 6. Write markdown
    header = (
        f"# Job Hunt — {TODAY}\n\n"
        f"_Window: last {hours_old} hours | Companies: {total} | New jobs found: {len(all_new_jobs)}_\n\n"
        "---\n"
    )
    OUT_MD.write_text(header + "\n".join(md_sections), encoding="utf-8")
    print(f"\n  📄 Markdown saved: {OUT_MD}")

    # 7. Update seen jobs
    save_seen(seen)
    print(f"  🧠 seen_jobs.json updated ({len(seen)} total IDs)")

    # 8. Export PDF
    try:
        export_pdf()
    except Exception as e:
        print(f"  ⚠️  PDF export failed: {e}")

    print(f"\n✅ Done! {len(all_new_jobs)} new jobs across {total} companies.")
    print(f"   Output: {OUT_PDF}")


if __name__ == "__main__":
    main()
