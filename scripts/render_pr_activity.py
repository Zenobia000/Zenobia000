#!/usr/bin/env python3
"""Generate an anonymous daily PR count SVG for the last 30 days."""
from __future__ import annotations
import json
import os
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

QUERY = """
query($query: String!, $after: String) {
  search(query: $query, type: ISSUE, first: 100, after: $after) {
    issueCount
    pageInfo { hasNextPage endCursor }
    nodes {
      ... on PullRequest {
        createdAt mergedAt
      }
    }
  }
}
"""

def fetch_prs(token: str, query: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    after: str | None = None
    while True:
        payload = json.dumps({"query": QUERY, "variables": {"query": query, "after": after}}).encode("utf-8")
        req = Request("https://api.github.com/graphql", data=payload,
                      headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json",
                               "Accept": "application/vnd.github+json", "User-Agent": "profile-pr-trends"},
                      method="POST")
        try:
            with urlopen(req, timeout=30) as response:
                result = json.load(response)
        except (HTTPError, URLError, TimeoutError) as e:
            raise RuntimeError(f"GitHub GraphQL request failed: {e}") from e
        if result.get("errors"):
            raise RuntimeError(f"GitHub GraphQL errors: {result['errors']}")
        search = result["data"]["search"]
        if search["issueCount"] > 1000:
            raise RuntimeError("Over 1,000 PR results; narrow the window to avoid truncated data.")
        rows.extend(n for n in search["nodes"] if n and n.get("createdAt"))
        if not search["pageInfo"]["hasNextPage"]:
            return rows
        after = search["pageInfo"]["endCursor"]
        if not after:
            raise RuntimeError("Missing GraphQL pagination cursor.")

def day(s: str) -> date:
    return datetime.fromisoformat(s.replace("Z", "+00:00")).date()

def make_svg(user: str, opened: list[dict[str, Any]],
             merged: list[dict[str, Any]], start: date, now: datetime) -> str:
    days = [start + timedelta(days=i) for i in range(30)]
    created: dict[date, int] = defaultdict(int)
    completed: dict[date, int] = defaultdict(int)
    for pr in opened:
        d = day(pr["createdAt"])
        if d in days:
            created[d] += 1
    for pr in merged:
        if pr.get("mergedAt"):
            d = day(pr["mergedAt"])
            if d in days:
                completed[d] += 1
    high = max([1, *created.values(), *completed.values()])
    today = now.date()
    rows = [
        '<svg xmlns="http://www.w3.org/2000/svg" width="960" height="450" viewBox="0 0 960 450" role="img" aria-label="Number of pull requests created and merged per day during the last 30 days">',
        '<rect width="960" height="450" rx="18" fill="#1A1B27"/>',
        '<rect x="1" y="1" width="958" height="448" rx="17" stroke="#30364C" fill="none"/>',
        '<g font-family="Inter, Arial, sans-serif">',
        '<text x="32" y="45" font-size="24" font-weight="700" fill="#E8ECF7">Daily Pull Request Activity</text>',
        '<text x="32" y="67" font-size="12" fill="#9DA8C4">Last 30 days · Public PR counts only · UTC</text>',
    ]
    metrics = [
        ("TODAY OPENED", created[today], "#A9FEF7"),
        ("30-DAY OPENED", sum(created.values()), "#62C4CE"),
        ("30-DAY MERGED", sum(completed.values()), "#819CFF"),
    ]
    for i, (label, amount, color) in enumerate(metrics):
        x = 32 + i * 302
        rows.extend([
            f'<rect x="{x}" y="85" width="286" height="73" rx="9" fill="#24273B"/>',
            f'<text x="{x+14}" y="106" fill="#ACB7CD" font-size="11">{label}</text>',
            f'<text x="{x+14}" y="141" fill="{color}" font-size="28" font-weight="700">{amount}</text>'
        ])
    rows.extend([
        '<rect x="715" y="174" width="12" height="12" rx="2" fill="#62C4CE"/>',
        '<text x="734" y="185" font-size="12" fill="#CAD3E5">Created</text>',
        '<rect x="816" y="174" width="12" height="12" rx="2" fill="#819CFF"/>',
        '<text x="835" y="185" font-size="12" fill="#CAD3E5">Merged</text>'
    ])
    baseline = 385
    top = 205
    for frac in (0, 0.5, 1):
        y = baseline - (baseline-top)*frac
        rows.append(f'<line x1="45" y1="{y:.1f}" x2="930" y2="{y:.1f}" stroke="#343B53"/>')
        rows.append(f'<text x="39" y="{y+4:.1f}" font-size="10" fill="#9DA8C4" text-anchor="end">{high*frac:.1f}</text>')
    for i, d in enumerate(days):
        x = 53 + i * 29
        for offset, n, color in ((0, created[d], "#62C4CE"), (10, completed[d], "#819CFF")):
            height = (baseline-top) * n / high
            if n:
                rows.append(f'<rect x="{x+offset}" y="{baseline-height:.1f}" width="8" height="{height:.1f}" rx="2" fill="{color}"/>')
        if i % 5 == 0 or i == 29:
            rows.append(f'<text x="{x+8}" y="404" font-size="10" fill="#ABB7CC" text-anchor="middle">{d:%m/%d}</text>')
    rows.extend([
        f'<text x="32" y="432" font-size="11" fill="#8795AD">Refreshed {now:%Y-%m-%d %H:%M} UTC · No repository details</text>',
        '</g></svg>'
    ])
    return "\n".join(rows) + "\n"

def main() -> None:
    token = os.environ["GITHUB_TOKEN"]
    user = os.getenv("GITHUB_USER", "Zenobia000")
    now = datetime.now(timezone.utc)
    start = now.date() - timedelta(days=29)
    opened = fetch_prs(token, f"is:pr is:public author:{user} created:>={start}")
    merged = fetch_prs(token, f"is:pr is:public is:merged author:{user} merged:>={start}")
    output = Path("profile/pr-activity.svg")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(make_svg(user, opened, merged, start, now), encoding="utf-8")
    print(f"Generated {output} (opened={len(opened)}, merged={len(merged)})")

if __name__ == "__main__":
    main()
