#!/usr/bin/env python3
"""
browser_apply.py — use Browser Use + Claude to apply on a careers page.

Uses browser-use's native ChatAnthropic (browser_use.llm.anthropic.chat),
which is the correct LLM class for browser-use — it has the .provider
attribute that browser-use requires internally.

Examples:
    # Dry-run (stop before submitting):
    python3 browser_apply.py \
      --career-url "https://jobs.example.com/job/123" \
      --job-title "Software Engineer" \
      --resume /Users/n02/Downloads/Resume.pdf \
      --email you@example.com \
      --password "YourP@ss1" \
      --dry-run

    # Full submit:
    python3 browser_apply.py \
      --career-url "https://jobs.example.com/job/123" \
      --job-title "Software Engineer" \
      --resume /Users/n02/Downloads/Resume.pdf \
      --email you@example.com \
      --password "YourP@ss1" \
      --candidate-notes "Notice period: 30 days. Work auth: Indian citizen."

Environment:
    ANTHROPIC_API_KEY or ANTHROPIC_AUTH_TOKEN must be set.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

from browser_use import Agent
from browser_use.llm.anthropic.chat import ChatAnthropic


def build_task(
    career_url: str,
    job_title: str,
    resume_path: Path,
    candidate_notes: str | None,
    location_hint: str | None,
    email: str | None,
    password: str | None,
    dry_run: bool,
) -> str:
    mode = (
        "Do not submit the final application. Stop at the final review/submit step and summarize what remains."
        if dry_run
        else "Submit the application only if all required fields are completed confidently and truthfully."
    )

    notes = candidate_notes.strip() if candidate_notes else "No extra candidate notes provided."
    location = location_hint.strip() if location_hint else "No location preference provided."
    account_info = (
        f"Login email: {email}\nPassword: {password}"
        if email and password
        else "No account credentials provided — stop if an account login/sign-up is required and report it as a blocker."
    )

    return f"""
Go to the career page: {career_url}

Find the most relevant open role matching this title: {job_title}

Use this resume file when a resume upload is requested: {resume_path}

Candidate notes for application answers:
{notes}

Preferred location / hint:
{location}

Account credentials (use these if a login or account creation form appears):
{account_info}

Instructions:
1. Navigate through the careers site and open the best matching role.
2. Start the application flow.
3. If a login or account creation form appears, use the provided credentials to sign in or create an account.
4. Fill fields using the resume and the candidate notes.
5. Upload the resume when requested.
6. If a question cannot be answered truthfully from the available information, stop and report the missing field.
7. {mode}
8. At the end, provide a concise summary of actions taken, fields filled, and any blockers.
""".strip()


async def run_agent(task: str, model: str, api_key: str) -> str:
    llm = ChatAnthropic(model=model, api_key=api_key)
    agent = Agent(task=task, llm=llm)
    result = await agent.run()
    return str(result)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Apply to a job on a careers page using Browser Use + Claude"
    )
    parser.add_argument("--career-url", required=True, help="Company careers page URL")
    parser.add_argument("--job-title", required=True, help="Target job title to search for")
    parser.add_argument(
        "--resume",
        required=True,
        help="Absolute path to the resume file to upload",
    )
    parser.add_argument(
        "--email",
        default="",
        help="Email address for account login/creation on the careers portal",
    )
    parser.add_argument(
        "--password",
        default="",
        help="Password for account login/creation on the careers portal",
    )
    parser.add_argument(
        "--candidate-notes",
        default="",
        help="Extra details for form answers, work authorization, notice period, links, etc.",
    )
    parser.add_argument(
        "--location-hint",
        default="",
        help="Preferred location or keyword to guide job search on the portal",
    )
    parser.add_argument(
        "--model",
        default="claude-sonnet-4-6",
        help="Anthropic model name (default: claude-3-7-sonnet-20250219)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Open and fill the application flow, but stop before final submission",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    api_key = os.getenv("ANTHROPIC_API_KEY") or os.getenv("ANTHROPIC_AUTH_TOKEN")
    if not api_key:
        print("❌ Missing ANTHROPIC_API_KEY (or ANTHROPIC_AUTH_TOKEN) environment variable.")
        return 1

    resume_path = Path(args.resume).expanduser().resolve()
    if not resume_path.exists():
        print(f"❌ Resume file not found: {resume_path}")
        return 1

    task = build_task(
        career_url=args.career_url,
        job_title=args.job_title,
        resume_path=resume_path,
        candidate_notes=args.candidate_notes,
        location_hint=args.location_hint,
        email=args.email or None,
        password=args.password or None,
        dry_run=args.dry_run,
    )

    print("🚀 Starting Browser Use agent...")
    print(f"   Career page: {args.career_url}")
    print(f"   Job title:   {args.job_title}")
    print(f"   Resume:      {resume_path}")
    print(f"   Email:       {args.email or '(not provided)'}")
    print(f"   Mode:        {'dry-run' if args.dry_run else 'submit-if-confident'}")

    try:
        result = asyncio.run(run_agent(task=task, model=args.model, api_key=api_key))
    except KeyboardInterrupt:
        print("\n⚠️ Interrupted by user.")
        return 130
    except Exception as exc:
        print(f"❌ Browser Use run failed: {exc}")
        return 1

    print("\n✅ Agent finished. Summary:\n")
    print(result)
    return 0


if __name__ == "__main__":
    sys.exit(main())
