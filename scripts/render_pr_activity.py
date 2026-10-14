#!/usr/bin/env python3
"""Generate a static SVG of a user's public PR activity over the last 12 weeks."""
from __future__ import annotations
import html
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
        title url createdAt mergedAt additions deletions changedFiles
        repository { nameWithOwner }
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

def shortened(s: str, max_chars: int) -> str:
    return s if len(s) <= max_chars else s[:max_chars - 1] + "…"

def make_svg(user: str, opened: list[dict[str, Any]],
             merged: list[dict[str, Any]], start: date, now: datetime) -> str:
    weeks = [start + timedelta(weeks=i) for i in range(12)]
    new: dict[date, int] = defaultdict(int)
    done: dict[date, int] = defaultdict(int)
    for p in opened:
        d = day(p["createdAt"])
        w = d - timedelta(days=d.weekday())
        if w in weeks:
            new[w] += 1
    for p in merged:
        if p.get("mergedAt"):
            d = day(p["mergedAt"])
            w = d - timedelta(days=d.weekday())
            if w in weeks:
                done[w] += 1
    max_y = max([1] + list(new.values()) + list(done.values()))
    files = sum(int(p.get("changedFiles") or 0) for p in opened)
    plus = sum(int(p.get("additions") or 0) for p in opened)
    minus = sum(int(p.get("deletions") or 0) for p in opened)
    recent = sorted(opened, key=lambda p: p["createdAt"], reverse=True)[:5]
    lines = [
        '<svg xmlns="http://www.w3.org/2000/svg" width="960" height="714" viewBox="0 0 960 714" role="img" aria-label="Public GitHub PR activity, last 12 weeks">',
        '<rect width="960" height="714" rx="18" fill="#1A1B27"/>',
        '<rect x="1" y="1" width="958" height="712" rx="17" fill="none" stroke="#30364C"/>',
        '<g font-family="Inter, Noto Sans TC, Arial, sans-serif">',
        '<text x="34" y="50" font-size="26" font-weight="700" fill="#E8ECF7">Pull Request Activity</text>',
        f'<text x="34" y="76" font-size="13" fill="#9DA8C4">{html.escape(user)} · Last 12 weeks · Public PRs · UTC</text>'
    ]
    for i, (label, val, color) in enumerate([
        ("OPENED PRS", f"{sum(new.values()):,}", "#A9FEF7"),
        ("MERGED PRS", f"{sum(done.values()):,}", "#819CFF"),
        ("FILES CHANGED", f"{files:,}", "#DDC18F"),
        ("DIFF LINES", f"+{plus:,} / −{minus:,}", "#D8E0F6"),
    ]):
        x = 34 + 227 * i
        lines.extend([
            f'<rect x="{x}" y="101" width="212" height="83" rx="10" fill="#24273B"/>',
            f'<text x="{x+15}" y="125" font-size="11" letter-spacing="1" fill="#ACB7CD">{label}</text>',
            f'<text x="{x+15}" y="162" font-size="{22 if i == 3 else 30}" font-weight="700" fill="{color}">{val}</text>'
        ])
    lines.extend([
        '<text x="34" y="224" font-size="18" font-weight="650" fill="#E8ECF7">Weekly trend</text>',
        '<rect x="662" y="212" width="13" height="13" rx="3" fill="#62C4CE"/>',
        '<text x="681" y="223" font-size="12" fill="#BAC4D8">Opened</text>',
        '<rect x="782" y="212" width="13" height="13" rx="3" fill="#819CFF"/>',
        '<text x="801" y="223" font-size="12" fill="#BAC4D8">Merged</text>'
    ])
    y0, y1 = 254, 401
    for fraction in (0.0, 0.5, 1.0):
        y = y1 - (y1-y0)*fraction
        lines.extend([
            f'<line x1="49" y1="{y:.1f}" x2="920" y2="{y:.1f}" stroke="#343B53"/>',
            f'<text x="43" y="{y+4:.1f}" font-size="11" text-anchor="end" fill="#8795AD">{round(max_y*fraction)}</text>'
        ])
    for i, w in enumerate(weeks):
        x = 66 + i*71
        for dx, n, c in ((0, new[w], "#62C4CE"), (20, done[w], "#819CFF")):
            h = n * (y1-y0) / max_y
            if n:
                lines.append(f'<rect x="{x+dx}" y="{y1-h:.1f}" width="16" height="{h:.1f}" rx="3" fill="{c}"/>')
        lines.append(f'<text x="{x+18}" y="422" font-size="11" text-anchor="middle" fill="#ABB7CC">{w:%m/%d}</text>')
    lines.extend([
        '<line x1="34" y1="443" x2="926" y2="443" stroke="#343B53"/>',
        '<text x="34" y="476" font-size="18" font-weight="650" fill="#E8ECF7">Latest opened PRs</text>',
        '<text x="925" y="476" font-size="11" text-anchor="end" fill="#A5B2C7">Changed files · +additions / −deletions</text>'
    ])
    if not recent:
        lines.append('<text x="34" y="528" font-size="15" fill="#ACB7CD">No public PRs opened in this period.</text>')
    for i, p in enumerate(recent):
        y = 506 + i*36
        repo = html.escape(shortened(p["repository"]["nameWithOwner"], 30))
        title = html.escape(shortened(p["title"], 40))
        n = int(p.get("changedFiles") or 0)
        a = int(p.get("additions") or 0)
        d = int(p.get("deletions") or 0)
        lines.extend([
            f'<text x="35" y="{y}" font-size="12" fill="#9FAAC2">{repo}</text>',
            f'<text x="35" y="{y+17}" font-size="12" fill="#E4EDF8">{title}</text>',
            f'<text x="923" y="{y+9}" text-anchor="end" font-size="12" fill="#A9FEF7">{n} files   +{a} / −{d}</text>'
        ])
    lines.extend([
        '<line x1="34" y1="691" x2="926" y2="691" stroke="#343B53"/>',
        f'<text x="34" y="705" font-size="10" fill="#8795AD">Updated {now:%Y-%m-%d %H:%M} UTC · Current PR diff size, not effort · Current week may be partial</text>',
        '</g></svg>'
    ])
    return "\n".join(lines) + "\n"

def main() -> None:
    token = os.environ["GITHUB_TOKEN"]
    user = os.getenv("GITHUB_USER", "Zenobia000")
    now = datetime.now(timezone.utc)
    monday = now.date() - timedelta(days=now.weekday())
    start = monday - timedelta(weeks=11)
    opened = fetch_prs(token, f"is:pr is:public author:{user} created:>={start}")
    merged = fetch_prs(token, f"is:pr is:public is:merged author:{user} merged:>={start}")
    output = Path("profile/pr-activity.svg")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(make_svg(user, opened, merged, start, now), encoding="utf-8")
    print(f"Generated {output} (opened={len(opened)}, merged={len(merged)})")

if __name__ == "__main__":
    main()
