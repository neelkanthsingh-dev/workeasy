#!/usr/bin/env python3
"""
fetch_lc.py — Scrape LeetCode Discuss Compensation posts (newest first).
Uses ugcArticleDiscussionArticles for listing + ugcArticleDiscussionArticle
for full content.

Parallel: 5 concurrent detail fetches, capped at 5 req/s → ~10s per 50 posts.

Usage:
    python3 fetch_lc.py --pages 2 --per-page 50
"""
import argparse
import json
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests

OUT_DIR = Path(__file__).parent
GRAPHQL = "https://leetcode.com/graphql/"
HEADERS = {
    "Content-Type": "application/json",
    "Accept": "*/*",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.6 Safari/605.1.15"
    ),
    "Referer": "https://leetcode.com/discuss/",
    "Origin": "https://leetcode.com",
}

# ── Rate limiter: 5 requests per second ─────────────────────────────────────
_rl_lock = threading.Lock()
_rl_timestamps: list[float] = []
MAX_RPS = 5
RPS_WINDOW = 1.0  # seconds


def _rate_limit():
    """Block until we're allowed to make another request (≤5/sec)."""
    while True:
        with _rl_lock:
            now = time.monotonic()
            _rl_timestamps[:] = [t for t in _rl_timestamps if now - t < RPS_WINDOW]
            if len(_rl_timestamps) < MAX_RPS:
                _rl_timestamps.append(now)
                return
        time.sleep(0.05)


# ── GraphQL queries ──────────────────────────────────────────────────────────
LIST_QUERY = """
query discussPostItems($orderBy: ArticleOrderByEnum, $keywords: [String]!, $tagSlugs: [String!], $skip: Int, $first: Int) {
  ugcArticleDiscussionArticles(
    orderBy: $orderBy
    keywords: $keywords
    tagSlugs: $tagSlugs
    skip: $skip
    first: $first
  ) {
    totalNum
    pageInfo { hasNextPage }
    edges {
      node {
        uuid title slug summary createdAt topicId
        tags { name slug tagType }
        topic { id topLevelCommentCount }
      }
    }
  }
}
"""

DETAIL_QUERY = """
query ugcArticleDetail($slug: String!) {
  ugcArticleDiscussionArticle(slug: $slug) {
    content
    summary
  }
}
"""


def clean_html(text: str) -> str:
    text = re.sub(r"<[^>]+>", " ", text or "")
    return re.sub(r"\s+", " ", text).strip()


def fetch_content(slug: str) -> str:
    """Fetch full post content. Rate-limited to 5/s. No auth needed."""
    _rate_limit()
    payload = {
        "query": DETAIL_QUERY,
        "variables": {"slug": slug},
        "operationName": "ugcArticleDetail",
    }
    try:
        r = requests.post(GRAPHQL, headers=HEADERS, json=payload, timeout=15)
        r.raise_for_status()
        d = r.json()
        article = (d.get("data") or {}).get("ugcArticleDiscussionArticle") or {}
        return clean_html(article.get("content") or article.get("summary") or "")
    except Exception:
        return ""


def fetch_page_list(skip: int, first: int, tag_slugs: list[str]) -> dict:
    payload = {
        "query": LIST_QUERY,
        "variables": {
            "orderBy": "MOST_RECENT",
            "keywords": [""],
            "tagSlugs": tag_slugs,
            "skip": skip,
            "first": first,
        },
        "operationName": "discussPostItems",
    }
    r = requests.post(GRAPHQL, headers=HEADERS, json=payload, timeout=15)
    r.raise_for_status()
    return r.json()


def main():
    parser = argparse.ArgumentParser(description="Fetch LeetCode compensation posts (parallel)")
    parser.add_argument("--pages", type=int, default=2)
    parser.add_argument("--per-page", type=int, default=50)
    parser.add_argument("--tags", nargs="+", default=["compensation"],
                        help="Tag slugs to filter by (default: compensation)")
    parser.add_argument("--prefix", default="lc",
                        help="Output filename prefix (default: lc → lc_raw_page_N.json)")
    args = parser.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    print(f"📥 Fetching {args.pages} page(s) × {args.per_page} posts — tags={args.tags} prefix={args.prefix} — parallel 5 req/s\n")

    for page_num in range(1, args.pages + 1):
        skip = (page_num - 1) * args.per_page
        print(f"  Page {page_num}/{args.pages} (skip={skip})...", end=" ", flush=True)

        try:
            data = fetch_page_list(skip=skip, first=args.per_page, tag_slugs=args.tags)
        except Exception as e:
            print(f"❌ List fetch failed: {e}")
            continue

        result = (data.get("data") or {}).get("ugcArticleDiscussionArticles", {})
        edges = result.get("edges", [])
        total = result.get("totalNum", "?")
        has_next = result.get("pageInfo", {}).get("hasNextPage", False)

        if not edges:
            print(f"❌ No edges. errors={data.get('errors')}")
            continue

        print(f"{len(edges)} posts (total={total}, hasNext={has_next})")
        print(f"  ⚡ Fetching full content in parallel (5 workers)...")

        # Build stubs first (preserve order)
        stubs = []
        for edge in edges:
            node = edge["node"]
            stubs.append({
                "slug": node.get("slug", ""),
                "title": node.get("title", ""),
                "tags": [t["name"] for t in node.get("tags", [])],
                "id": str(node.get("topicId") or (node.get("topic") or {}).get("id", "")),
                "created_ts": node.get("createdAt", ""),
            })

        # Parallel content fetch — 5 workers, rate limited to 5/s internally
        content_map: dict[str, str] = {}
        done_count = 0
        lock = threading.Lock()

        def fetch_one(stub):
            nonlocal done_count
            slug = stub["slug"]
            content = fetch_content(slug)
            with lock:
                content_map[slug] = content
                done_count += 1
                print(f"    [{done_count:2d}/{len(stubs)}] {stub['title'][:60]} ({len(content)} chars)")
            return slug

        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = [executor.submit(fetch_one, s) for s in stubs]
            for f in as_completed(futures):
                f.result()  # surface exceptions

        # Assemble in original order
        page_posts = []
        for stub in stubs:
            page_posts.append({
                "id": stub["id"],
                "slug": stub["slug"],
                "title": stub["title"],
                "tags": stub["tags"],
                "created_ts": stub["created_ts"],
                "content": content_map.get(stub["slug"], ""),
                "url": f"https://leetcode.com/discuss/post/{stub['id']}/",
            })

        out_file = OUT_DIR / f"{args.prefix}_raw_page_{page_num}.json"
        out_file.write_text(json.dumps(page_posts, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"  ✅ Saved {len(page_posts)} posts → {out_file.name}\n")

        time.sleep(0.3)

    print("✅ fetch_lc.py done. Now run: python3 ai_decipher.py")


if __name__ == "__main__":
    main()
