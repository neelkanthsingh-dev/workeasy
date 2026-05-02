#!/usr/bin/env python3
"""
run_all.py — One command to fetch, decipher, and export a PDF report.

Usage:
    python3 run_all.py --pages 2
    python3 run_all.py --pages 10
"""
import argparse
import json
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

OUT_DIR = Path(__file__).parent
PYTHON = sys.executable


def run_fetch(pages: int, per_page: int, tags: list[str], prefix: str):
    tag_str = ", ".join(tags)
    print(f"\n{'='*60}")
    print(f"  STEP: Fetching {pages} page(s) [{tag_str}] → {prefix}_raw_page_*.json")
    print(f"{'='*60}\n")
    result = subprocess.run(
        [PYTHON, str(OUT_DIR / "fetch_lc.py"),
         "--pages", str(pages), "--per-page", str(per_page),
         "--tags", *tags, "--prefix", prefix],
        cwd=OUT_DIR,
    )
    if result.returncode != 0:
        print(f"❌ fetch_lc.py failed (prefix={prefix}).")
        sys.exit(1)


def run_decipher(pages: int, prefix: str):
    print(f"\n{'='*60}")
    print(f"  STEP: AI deciphering {pages} page(s) [{prefix}]")
    print(f"{'='*60}\n")
    result = subprocess.run(
        [PYTHON, str(OUT_DIR / "ai_decipher.py"), "--pages", str(pages), "--prefix", prefix],
        cwd=OUT_DIR,
    )
    if result.returncode != 0:
        print(f"❌ ai_decipher.py failed (prefix={prefix}).")
        sys.exit(1)


def merge_results(prefixes: list[str]) -> list[dict]:
    """Load and deduplicate results from multiple prefix sources."""
    seen_urls: set[str] = set()
    merged: list[dict] = []
    for prefix in prefixes:
        f = OUT_DIR / f"{prefix}_results.json"
        if not f.exists():
            print(f"  ⚠️  {f.name} not found, skipping.")
            continue
        entries = json.loads(f.read_text(encoding="utf-8"))
        added = 0
        for entry in entries:
            url = entry.get("url") or ""
            if url and url in seen_urls:
                continue
            if url:
                seen_urls.add(url)
            merged.append(entry)
            added += 1
        print(f"  📂 {f.name}: {len(entries)} entries ({added} new after dedup)")
    return merged


def _sources_label(sources: list[str] | None) -> str:
    labels = {"lc": "Compensation", "ic": "Interview & Career"}
    if not sources:
        return "Compensation"
    return " + ".join(labels.get(s, s) for s in sources)


def build_pdf(results: list[dict], pages: int, sources: list[str] | None = None):
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.platypus import (
        SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
    )

    results = sorted(results, key=lambda x: x.get("ctc_lpa") or 0, reverse=True)
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    pdf_path = OUT_DIR / f"compensation_report_{datetime.now().strftime('%Y%m%d_%H%M')}.pdf"

    doc = SimpleDocTemplate(
        str(pdf_path),
        pagesize=landscape(A4),
        leftMargin=1.5*cm, rightMargin=1.5*cm,
        topMargin=1.5*cm, bottomMargin=1.5*cm,
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle("title", parent=styles["Heading1"], fontSize=16, spaceAfter=4)
    sub_style = ParagraphStyle("sub", parent=styles["Normal"], fontSize=9, textColor=colors.grey, spaceAfter=12)
    cell_style = ParagraphStyle("cell", parent=styles["Normal"], fontSize=8, leading=10)
    link_style = ParagraphStyle("link", parent=styles["Normal"], fontSize=7, textColor=colors.blue, leading=9)

    story = [
        Paragraph("🇮🇳 India Tech Compensation Report", title_style),
        Paragraph(f"Source: LeetCode Discuss → {_sources_label(sources)} | Fetched: {timestamp} | Pages: {pages} | Entries: {len(results)}", sub_style),
        Spacer(1, 0.3*cm),
    ]

    # Table header
    header = ["#", "Company", "Level", "YOE", "CTC (LPA)", "Notes", "Post Title", "Link"]
    col_widths = [1.2*cm, 4*cm, 2*cm, 1.2*cm, 2.2*cm, 7*cm, 5.5*cm, 2.5*cm]

    table_data = [[Paragraph(f"<b>{h}</b>", cell_style) for h in header]]

    for i, r in enumerate(results, 1):
        company = r.get("company") or "Unknown"
        level = r.get("level") or ""
        yoe = str(r.get("yoe") or "?")
        ctc = f"{r.get('ctc_lpa', 0):.1f} L" if r.get("ctc_lpa") else "?"
        notes = r.get("notes") or ""
        title = r.get("post_title") or ""
        url = r.get("url") or ""
        short_url = "link" if url else ""

        row = [
            Paragraph(str(i), cell_style),
            Paragraph(company, cell_style),
            Paragraph(level, cell_style),
            Paragraph(yoe, cell_style),
            Paragraph(f"<b>{ctc}</b>", cell_style),
            Paragraph(notes, cell_style),
            Paragraph(title[:80], cell_style),
            Paragraph(f'<a href="{url}" color="blue">{short_url}</a>' if url else "", link_style),
        ]
        table_data.append(row)

    table = Table(table_data, colWidths=col_widths, repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1a1a2e")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 9),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f0f4ff")]),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#cccccc")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
    ]))

    story.append(table)
    doc.build(story)
    return pdf_path


def main():
    parser = argparse.ArgumentParser(description="Fetch + Decipher + PDF in one shot")
    parser.add_argument("--pages", type=int, default=2, help="Number of pages to fetch (default: 2)")
    parser.add_argument("--per-page", type=int, default=15, help="Posts per page (default: 15)")
    parser.add_argument("--skip-fetch", action="store_true", help="Skip fetching, reuse existing raw files")
    parser.add_argument("--include-ic", action="store_true",
                        help="Also fetch and decipher Interview+Career posts")
    args = parser.parse_args()

    sources = ["lc"]
    if args.include_ic:
        sources.append("ic")

    if not args.skip_fetch:
        print(f"\n{'='*60}")
        print(f"  STEP 1: Fetching posts from LeetCode")
        print(f"{'='*60}")
        run_fetch(args.pages, args.per_page, tags=["compensation"], prefix="lc")
        if args.include_ic:
            run_fetch(args.pages, args.per_page, tags=["interview", "career"], prefix="ic")

    print(f"\n{'='*60}")
    print(f"  STEP 2: AI Deciphering")
    print(f"{'='*60}")
    for prefix in sources:
        run_decipher(args.pages, prefix=prefix)

    print(f"\n{'='*60}")
    print(f"  STEP 3: Merging results ({', '.join(sources)})")
    print(f"{'='*60}\n")
    results = merge_results(sources)
    results.sort(key=lambda x: x.get("ctc_lpa") or 0, reverse=True)

    results_file = OUT_DIR / "results.json"
    results_file.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"  💾 results.json saved ({len(results)} total entries)\n")

    print(f"\n{'='*60}")
    print(f"  STEP 4: Generating PDF ({len(results)} entries)")
    print(f"{'='*60}\n")

    try:
        pdf_path = build_pdf(results, args.pages, sources=sources)
        print(f"  ✅ PDF saved → {pdf_path}")
    except Exception as e:
        print(f"  ❌ PDF generation failed: {e}")
        sys.exit(1)

    print(f"\n✅ All done! {len(results)} India compensation entries.")


if __name__ == "__main__":
    main()
