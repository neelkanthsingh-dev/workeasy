#!/usr/bin/env python3
"""
ai_decipher.py — Extract structured India compensation data from LeetCode posts.

Strategy:
  - Chunk posts into groups of 10
  - Fire all chunks in parallel via ThreadPoolExecutor
  - Rate limit: 20 AI calls per 60 seconds (sliding window)
  - Wait for all futures, then merge + save results

Usage:
    python3 ai_decipher.py           # process all lc_raw_page_*.json
    python3 ai_decipher.py --pages 2
"""
import argparse
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from openai import OpenAI

OUT_DIR = Path(__file__).parent
API_KEY = "ak-MlyGOJqhrv6OX979jUBTLxlqyCmi"
BASE_URL = "https://api.fuelix.ai/v1"
MODEL = "gpt-5.4"

CHUNK_SIZE = 10           # posts per AI call
MAX_CALLS = 20            # max AI calls per window
RATE_WINDOW = 60.0        # seconds
MAX_WORKERS = 10          # max parallel AI calls

client = OpenAI(api_key=API_KEY, base_url=BASE_URL)

# ── Rate limiter: 20 calls / 60 seconds ─────────────────────────────────────
_rl_lock = threading.Lock()
_rl_timestamps: list[float] = []


def _rate_limit():
    """Block until we're below 20 calls/60s."""
    while True:
        with _rl_lock:
            now = time.monotonic()
            _rl_timestamps[:] = [t for t in _rl_timestamps if now - t < RATE_WINDOW]
            if len(_rl_timestamps) < MAX_CALLS:
                _rl_timestamps.append(now)
                return
            wait = RATE_WINDOW - (now - _rl_timestamps[0]) + 0.5
        print(f"    ⏳ Rate limit ({len(_rl_timestamps)}/60s): sleeping {wait:.1f}s...")
        time.sleep(wait)


# ── Prompts ──────────────────────────────────────────────────────────────────
SYSTEM_PROMPT = """You are a compensation data analyst specializing in Indian tech industry salaries.
You will be given a batch of LeetCode discussion posts (title + full content) from the Compensation section.
Your job is to extract structured salary information.

## Title parsing
Post titles often follow patterns like:
  "Company | Role | City | Month Year"
  "Company | Level | City"
  "Company Name SDE-2 Bangalore"
Extract company from the FIRST segment before | or the first recognizable company name.

## What to extract
- Focus ONLY on India-based roles (keywords: INR, LPA, lakhs, L, Bangalore, Hyderabad, Pune, Mumbai, Delhi, Gurgaon, Noida, Chennai, Bengaluru, India, remote India)
- Skip posts about non-India roles (USD salary without India mention = skip)
- If a post COMPARES multiple offers, create ONE entry per company mentioned
- CTC = total annual comp: base + bonus + annualized stocks/RSUs/ESOPs
- Salary formats to normalize to LPA: "55 LPA", "55L", "55 lakhs", "₹55,00,000", "5500000 INR" → all = 55.0
- If Year 1 / Year 2 breakdown given, use Year 1
- If range given (e.g. "50-60 LPA"), use lower bound
- level: job level/grade e.g. SDE-1, SDE-2, L4, L5, L6, IC3, IC4, P40, Senior, Staff, Lead (null if unclear)
- yoe: years of experience as number. Infer if possible: "fresher"→0, "3 years"→3. Null only if truly unmentionable
- notes: detailed note covering role, city, comp breakdown, key context (e.g. "SDE-2 Chennai; base 45L + 15L stocks Y1; first FAANG offer; ESOPs vest 4yr")

## Output format
Return ONLY a JSON array, no markdown, no explanation:
[
  {
    "company": "Company Name",
    "post_title": "exact post title",
    "level": "SDE-2",
    "yoe": 3,
    "ctc_lpa": 55.0,
    "source_post_number": 3,
    "notes": "detailed note about role, city, comp breakdown, context"
  }
]

- source_post_number: the POST number (1-based) from the batch that this entry came from. Required.

If no valid India compensation data found, return: []
"""


def build_user_prompt(posts: list[dict]) -> str:
    lines = [f"Analyze these {len(posts)} LeetCode compensation discussion posts and extract India CTC data:\n"]
    for i, p in enumerate(posts, 1):
        lines.append(f"--- POST {i} ---")
        lines.append(f"Title: {p['title']}")
        lines.append(f"Tags: {', '.join(p.get('tags', []))}")
        lines.append(f"URL: {p['url']}")
        content = p.get("content", "")
        if len(content) > 1500:
            content = content[:1500] + "... [truncated]"
        lines.append(f"Content: {content}")
        lines.append("")
    return "\n".join(lines)


def call_ai(chunk_id: str, posts: list[dict]) -> list[dict]:
    """Send one AI call for a chunk of posts. Rate-limited.
    Injects authoritative URL from raw posts using source_post_number.
    """
    _rate_limit()

    user_prompt = build_user_prompt(posts)
    print(f"  🤖 [{chunk_id}] Calling {MODEL} ({len(posts)} posts)...", end=" ", flush=True)

    for attempt in range(3):
        try:
            response = client.chat.completions.create(
                model=MODEL,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.1,
                max_tokens=4096,
            )
            raw = response.choices[0].message.content.strip()

            # Strip markdown code fences if present
            if raw.startswith("```"):
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]
                raw = raw.strip()

            results = json.loads(raw)

            # Inject authoritative URL from raw posts via source_post_number
            for entry in results:
                src_num = entry.pop("source_post_number", None)
                if src_num and 1 <= int(src_num) <= len(posts):
                    entry["url"] = posts[int(src_num) - 1]["url"]
                elif not entry.get("url"):
                    entry["url"] = ""

            print(f"✅ {len(results)} entries")
            return results

        except json.JSONDecodeError as e:
            print(f"\n    ⚠️  [{chunk_id}] JSON error (attempt {attempt+1}): {e}")
            if attempt == 2:
                return []
            time.sleep(3)
        except Exception as e:
            print(f"\n    ❌ [{chunk_id}] API error (attempt {attempt+1}): {e}")
            if attempt == 2:
                return []
            time.sleep(5 * (attempt + 1))

    return []


def main():
    parser = argparse.ArgumentParser(description="AI-powered LeetCode compensation decipherer (parallel)")
    parser.add_argument("--pages", type=int, default=None, help="Number of pages to process (default: all)")
    parser.add_argument("--prefix", default="lc",
                        help="Raw file prefix to process (default: lc → lc_raw_page_*.json)")
    args = parser.parse_args()

    page_files = sorted(OUT_DIR.glob(f"{args.prefix}_raw_page_*.json"))
    if not page_files:
        print(f"❌ No {args.prefix}_raw_page_*.json files found. Run fetch_lc.py first.")
        return

    if args.pages:
        page_files = page_files[: args.pages]

    # Load all posts from all pages
    all_posts: list[dict] = []
    page_post_counts: dict[int, int] = {}
    for pf in page_files:
        page_num = int(pf.stem.split("_")[-1])
        posts = json.loads(pf.read_text(encoding="utf-8"))
        page_post_counts[page_num] = len(posts)
        all_posts.extend(posts)

    total_posts = len(all_posts)
    # Split into chunks of CHUNK_SIZE
    chunks = [all_posts[i: i + CHUNK_SIZE] for i in range(0, total_posts, CHUNK_SIZE)]
    total_chunks = len(chunks)

    print(f"🧠 ai_decipher.py [{args.prefix}] — {total_posts} posts across {len(page_files)} page(s)")
    print(f"   Chunks: {total_chunks} × {CHUNK_SIZE} posts | Workers: {MAX_WORKERS} | Rate: {MAX_CALLS}/{int(RATE_WINDOW)}s\n")

    # Fire all chunks in parallel
    chunk_results: dict[int, list[dict]] = {}

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        future_to_idx = {
            executor.submit(call_ai, f"chunk-{i+1:02d}/{total_chunks}", chunk): i
            for i, chunk in enumerate(chunks)
        }
        for future in as_completed(future_to_idx):
            idx = future_to_idx[future]
            try:
                chunk_results[idx] = future.result()
            except Exception as e:
                print(f"  ❌ chunk-{idx+1} failed: {e}")
                chunk_results[idx] = []

    # Merge in original chunk order
    all_results: list[dict] = []
    for i in range(total_chunks):
        all_results.extend(chunk_results.get(i, []))

    # Save merged results
    results_file = OUT_DIR / f"{args.prefix}_results.json"
    results_file.write_text(json.dumps(all_results, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n  💾 Merged results saved → {results_file.name} ({len(all_results)} total entries)\n")

    # Also save per-page result files (for compatibility with run_all.py)
    offset = 0
    for pf in page_files:
        page_num = int(pf.stem.split("_")[-1])
        count = page_post_counts[page_num]
        # Gather results that came from this page's posts
        page_slugs = {p["slug"] for p in json.loads(pf.read_text(encoding="utf-8"))}
        page_results = [r for r in all_results if any(
            s in (r.get("url") or "") for s in page_slugs
        )]
        per_page_out = OUT_DIR / f"{args.prefix}_results_page_{page_num}.json"
        per_page_out.write_text(json.dumps(page_results, indent=2, ensure_ascii=False), encoding="utf-8")
        offset += count

    if not all_results:
        print("⚠️  No India compensation data extracted.")
        return

    # Sort by CTC desc and print table
    all_results.sort(key=lambda x: x.get("ctc_lpa") or 0, reverse=True)

    W = 135
    print("=" * W)
    print(f"{'#':<4} {'COMPANY':<26} {'LEVEL':<10} {'YOE':>4}  {'CTC (LPA)':>10}  {'NOTES':<50}  TITLE")
    print("=" * W)
    for i, r in enumerate(all_results, 1):
        num = str(i)
        company = (r.get("company") or "Unknown")[:25]
        level = (r.get("level") or "")[:9]
        yoe = str(r.get("yoe") or "?")
        ctc = f"{r.get('ctc_lpa', 0):.1f}L" if r.get("ctc_lpa") else "?"
        notes = (r.get("notes") or "")[:50]
        title = (r.get("post_title") or "")[:33]
        print(f"  {num:<3} {company:<25} {level:<10} {yoe:>4}  {ctc:>10}  {notes:<50}  {title}")

    print("=" * W)
    print(f"\n✅ Done. {len(all_results)} India compensation entries from {total_posts} posts.")
    print(f"   Full data: {results_file.name}")


if __name__ == "__main__":
    main()
