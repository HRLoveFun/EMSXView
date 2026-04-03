#!/usr/bin/env python3
"""
Collect CI status for a given commit via the GitHub check-runs API.

Outputs a JSON summary with overall_conclusion (success/failure/pending)
and individual check run details.

Requires GITHUB_TOKEN env var (or runs in a GitHub Actions context).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from typing import Any


def get_check_runs(owner: str, repo: str, commit_sha: str, token: str | None = None) -> dict[str, Any]:
    """Fetch check runs for a commit from GitHub API."""
    url = f"https://api.github.com/repos/{owner}/{repo}/commits/{commit_sha}/check-runs"
    headers = {"Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return {"error": f"HTTP {e.code}: {e.reason}", "total_count": 0, "check_runs": []}
    except urllib.error.URLError as e:
        return {"error": str(e), "total_count": 0, "check_runs": []}


def summarize(check_data: dict[str, Any]) -> dict[str, Any]:
    """Build a summary from raw check-runs response."""
    runs = check_data.get("check_runs", [])
    if not runs:
        return {
            "overall_conclusion": "pending",
            "total_checks": 0,
            "checks": [],
            "error": check_data.get("error"),
        }

    checks = []
    all_done = True
    any_failure = False
    for run in runs:
        status = run.get("status", "queued")
        conclusion = run.get("conclusion")
        name = run.get("name", "unknown")

        if status != "completed":
            all_done = False
        elif conclusion not in ("success", "skipped", "neutral"):
            any_failure = True

        checks.append({
            "name": name,
            "status": status,
            "conclusion": conclusion,
        })

    if any_failure:
        overall = "failure"
    elif all_done:
        overall = "success"
    else:
        overall = "pending"

    return {
        "overall_conclusion": overall,
        "total_checks": len(runs),
        "checks": checks,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Collect CI check-run status for a commit.")
    parser.add_argument("--commit", required=True, help="Git commit SHA")
    parser.add_argument("--owner", default=None, help="GitHub repo owner (default: from GITHUB_REPOSITORY)")
    parser.add_argument("--repo", default=None, help="GitHub repo name (default: from GITHUB_REPOSITORY)")
    parser.add_argument("--output-json", default=None, help="Output file (use '-' for stdout)")
    args = parser.parse_args()

    owner = args.owner
    repo = args.repo
    if not owner or not repo:
        gh_repo = os.environ.get("GITHUB_REPOSITORY", "")
        if "/" in gh_repo:
            owner = owner or gh_repo.split("/")[0]
            repo = repo or gh_repo.split("/")[1]
        else:
            print("ERROR: --owner/--repo or GITHUB_REPOSITORY env var required", file=sys.stderr)
            return 1

    token = os.environ.get("GITHUB_TOKEN")
    raw = get_check_runs(owner, repo, args.commit, token)
    summary = summarize(raw)
    summary["commit"] = args.commit

    output = json.dumps(summary, indent=2)
    if args.output_json and args.output_json != "-":
        from pathlib import Path
        p = Path(args.output_json)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(output + "\n", encoding="utf-8")
    else:
        print(output)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
