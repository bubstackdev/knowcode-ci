#!/usr/bin/env python3
"""Posts a review's markdown as one pull request comment (GitHub) or merge request note (GitLab), updated in place.

    post.py github --repo OWNER/NAME --pr N --body FILE        (token: GH_TOKEN)
    post.py gitlab --api URL --project ID --mr IID --body FILE  (token: KNOWCODE_GITLAB_TOKEN)

The comment is found again by the marker the review's first line carries (kc_ci.MARKER): a later run edits it
rather than adding another. A body past the platform's limit is cut at a line, saying so. Standard library only;
the token is the platform's own, given by the workflow, and KnowCode never sees it.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import urllib.parse
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parent))
from kc_ci import MARKER  # noqa: E402

# GitHub refuses a comment body over 65536 characters; GitLab a note over 1,000,000.
LIMITS = {"github": 65536, "gitlab": 1_000_000}


def fit(body, limit):
    """`body` cut at a line to fit `limit` characters, with a last line saying it was cut."""
    if len(body) <= limit:
        return body
    note = "\n\n_The review was cut here to fit the comment; the job's summary and artifacts have all of it._\n"
    cut = body[: limit - len(note)]
    return cut[: cut.rfind("\n") + 1] + note


def request(method, url, headers, data=None):
    body = json.dumps(data).encode() if data is not None else None
    req = urllib.request.Request(url, data=body, method=method, headers={**headers, "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read() or b"null")


def pages(url, headers):
    """Every item of a paged list."""
    page = 1
    while True:
        sep = "&" if "?" in url else "?"
        items = request("GET", f"{url}{sep}per_page=100&page={page}", headers)
        if not items:
            return
        yield from items
        page += 1


def github(args, body):
    headers = {"Authorization": f"Bearer {os.environ['GH_TOKEN']}", "Accept": "application/vnd.github+json"}
    api = f"https://api.github.com/repos/{args.repo}"
    mine = next((c for c in pages(f"{api}/issues/{args.pr}/comments", headers) if (c.get("body") or "").startswith(MARKER)), None)
    if mine:
        request("PATCH", f"{api}/issues/comments/{mine['id']}", headers, {"body": body})
    else:
        request("POST", f"{api}/issues/{args.pr}/comments", headers, {"body": body})


def gitlab(args, body):
    headers = {"PRIVATE-TOKEN": os.environ["KNOWCODE_GITLAB_TOKEN"]}
    api = f"{args.api}/projects/{urllib.parse.quote(str(args.project), safe='')}/merge_requests/{args.mr}/notes"
    mine = next((n for n in pages(api, headers) if (n.get("body") or "").startswith(MARKER)), None)
    if mine:
        request("PUT", f"{api}/{mine['id']}", headers, {"body": body})
    else:
        request("POST", api, headers, {"body": body})


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="platform", required=True)
    g = sub.add_parser("github")
    g.add_argument("--repo", required=True)
    g.add_argument("--pr", required=True)
    g.add_argument("--body", required=True)
    gl = sub.add_parser("gitlab")
    gl.add_argument("--api", required=True)
    gl.add_argument("--project", required=True)
    gl.add_argument("--mr", required=True)
    gl.add_argument("--body", required=True)
    args = ap.parse_args(argv)
    body = fit(Path(args.body).read_text(), LIMITS[args.platform])
    (github if args.platform == "github" else gitlab)(args, body)
    return 0


if __name__ == "__main__":
    sys.exit(main())
