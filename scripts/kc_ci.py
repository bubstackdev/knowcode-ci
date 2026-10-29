#!/usr/bin/env python3
"""Runs `knowcode review` for a pull or merge request, in restricted mode, and checks the run left the repo alone.

    kc_ci.py review --knowcode BIN --repo DIR --base REF --out DIR [--cache DIR]
    kc_ci.py codequality SARIF OUT

`review` starts `BIN serve --restricted`, bound to the checked-out repo alone, with only the review ops allowed
(`review`, `more`) and its own cache and config directories, and talks to it over MCP. Before asking anything it checks
the scope the server states: the one repo, no discovery, no update checks, git off the network. It checks that the
server refuses an op it wasn't given and a path outside the repo. It then asks for the review of the change since
REF as markdown and as SARIF, writes OUT/review.md and OUT/review.sarif, and finally checks that the repo's files and
its git state (HEAD, refs, index, status) are what they were before. Any failed check exits 1 and says why, in
OUT/checks.json too.

`codequality` turns a SARIF file into GitLab's code quality report (a JSON list of issues).

KnowCode only prints: posting the markdown and uploading the SARIF are the workflow's steps, with the platform's own
token. Standard library only.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import select
import subprocess
import sys
import time

MARKER = "<!-- knowcode-review -->"
OPS = ("review", "more")


class Server:
    """`knowcode serve` over MCP's stdio transport: one JSON-RPC message per line."""

    def __init__(self, argv, env, cwd, log):
        # Its log goes to a file: a pipe nobody reads would stop the server once full.
        self.log = log
        self.process = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=open(log, "wb"),
                                        env=env, cwd=cwd)
        self.next_id = 0
        self.buffer = b""
        self.init = self.request("initialize", {"protocolVersion": "2025-03-26", "capabilities": {},
                                                "clientInfo": {"name": "knowcode-ci", "version": "1"}}, 300)
        self.send({"jsonrpc": "2.0", "method": "notifications/initialized"})

    def send(self, msg):
        self.process.stdin.write((json.dumps(msg) + "\n").encode())
        self.process.stdin.flush()

    def request(self, method, params, timeout):
        self.next_id += 1
        want = self.next_id
        self.send({"jsonrpc": "2.0", "id": want, "method": method, "params": params})
        deadline = time.monotonic() + timeout
        while True:
            while b"\n" in self.buffer:
                line, self.buffer = self.buffer.split(b"\n", 1)
                if not line.strip():
                    continue
                msg = json.loads(line)
                if msg.get("id") == want:
                    return msg
            left = deadline - time.monotonic()
            if left <= 0:
                raise TimeoutError(f"no reply to {method} within {timeout}s")
            ready, _, _ = select.select([self.process.stdout], [], [], left)
            if ready:
                chunk = os.read(self.process.stdout.fileno(), 1 << 16)
                if not chunk:
                    raise RuntimeError(f"knowcode exited: {Path(self.log).read_text(errors='replace')[-2000:]}")
                self.buffer += chunk

    def call(self, args, timeout=900):
        """(text, error code or None) of one `kc` call."""
        reply = self.request("tools/call", {"name": "kc", "arguments": args}, timeout)
        if "error" in reply:
            return json.dumps(reply["error"]), "protocol"
        result = reply.get("result") or {}
        text = "\n".join(p.get("text", "") for p in result.get("content") or [] if p.get("type") == "text")
        if result.get("isError"):
            err = (result.get("structuredContent") or {}).get("error") or {}
            return text, err.get("code") or "error"
        return text, None

    def close(self):
        try:
            self.process.stdin.close()
            self.process.wait(timeout=10)
        except (OSError, subprocess.TimeoutExpired):
            self.process.kill()


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True).stdout


def state(repo):
    """What a run must leave as it found it: every file of the working tree (outside .git) with its content hash, and
    git's HEAD, refs, index, config and status."""
    repo = Path(repo)
    files = {}
    for dirpath, dirnames, filenames in os.walk(repo):
        d = Path(dirpath)
        dirnames[:] = [n for n in dirnames if not (d == repo and n == ".git")]
        for n in filenames:
            p = d / n
            h = "link:" + os.readlink(p) if p.is_symlink() else hashlib.sha256(p.read_bytes()).hexdigest()
            files[str(p.relative_to(repo))] = h
    gitdir = Path(git(repo, "rev-parse", "--absolute-git-dir").decode().strip())
    meta = {name: hashlib.sha256((gitdir / name).read_bytes()).hexdigest() for name in ("index", "config", "HEAD")
            if (gitdir / name).is_file()}
    return {
        "files": files,
        "git": meta,
        "head": git(repo, "rev-parse", "HEAD").decode().strip(),
        "refs": git(repo, "for-each-ref", "--format=%(refname) %(objectname)").decode(),
        "status": git(repo, "--no-optional-locks", "status", "--porcelain=v2", "--untracked-files=all", "--ignored").decode(),
    }


def differences(before, after):
    out = []
    changed = sorted(k for k in set(before["files"]) | set(after["files"]) if before["files"].get(k) != after["files"].get(k))
    if changed:
        out.append(f"files changed: {', '.join(changed[:20])}")
    for key in ("git", "head", "refs", "status"):
        if before[key] != after[key]:
            out.append(f"git state changed: {key}")
    return out


def scope_problems(init, repo, ops=OPS):
    """What is wrong with the scope the server states for a run bound to `repo` with only `ops`."""
    scope = (((init.get("result") or {}).get("capabilities") or {}).get("experimental") or {}).get("knowcode/scope")
    if not isinstance(scope, dict):
        return ["the server states no scope (capabilities.experimental[\"knowcode/scope\"])"]
    out = []
    repos = [str(Path(r["path"] if isinstance(r, dict) else r).resolve()) for r in scope.get("repos") or []]
    if repos != [str(Path(repo).resolve())]:
        out.append(f"bound to {repos}, not only {Path(repo).resolve()}")
    stated = sorted(set(scope.get("ops") or []) - {"capabilities"})
    if stated != sorted(ops):
        out.append(f"ops {stated}, not {sorted(ops)}")
    if scope.get("restricted") is not True:
        out.append("not restricted")
    for flag in ("discovery", "update_checks", "plugin_refresh", "git_network"):
        if scope.get(flag) is not False:
            out.append(f"{flag} is {scope.get(flag)!r}, not false")
    return out


def review(args):
    repo = Path(args.repo).resolve()
    out = Path(args.out).resolve()
    cache = Path(args.cache).resolve() if args.cache else out / "kc-cache"
    for d in (out, cache):
        if d == repo or repo in d.parents:
            sys.exit(f"knowcode-ci: {d} is inside the repo; KnowCode writes nothing into it, so put it elsewhere")
    out.mkdir(parents=True, exist_ok=True)
    config, tmp = cache.parent / (cache.name + "-config"), cache / "tmp"
    for d in (cache, config, tmp):
        d.mkdir(parents=True, exist_ok=True)
    env = {"HOME": str(cache), "PATH": os.environ.get("PATH", "/usr/bin:/bin"), "TMPDIR": str(tmp),
           "KNOWCODE_UPDATE_CHECK": "0", "LANG": "C.UTF-8"}
    argv = [args.knowcode, "serve", "--restricted", "--repo", str(repo), "--ops", ",".join(args.ops),
            "--cache-dir", str(cache), "--config-dir", str(config)]
    before = state(repo)
    checks = {"scope": [], "refused": [], "unchanged": [], "review": []}
    server = Server(argv, env, str(tmp), out / "knowcode.log")
    try:
        checks["scope"] = scope_problems(server.init, repo, args.ops)
        # An op not given and a path outside the repo are refused.
        for ask in ({"op": "search", "q": "TODO"}, {"op": args.ops[0], "diff": args.base, "repo": "/"}):
            _, code = server.call(ask, timeout=120)
            if code != "not_allowed":
                checks["refused"].append(f"{json.dumps(ask)}: {code or 'answered'}, expected not_allowed")
        if not checks["scope"]:
            for fmt, name in (("markdown", "review.md"), ("sarif", "review.sarif")):
                text, code = server.call({"op": args.ops[0], "diff": args.base, "format": fmt})
                if code:
                    checks["review"].append(f"review as {fmt}: {code}: {text[:300]}")
                    continue
                if fmt == "markdown":
                    text = f"{MARKER}\n{text}"
                (out / name).write_text(text)
    finally:
        server.close()
    checks["unchanged"] = differences(before, state(repo))
    (out / "checks.json").write_text(json.dumps(checks, indent=2) + "\n")
    failed = [f"{k}: {p}" for k, v in checks.items() for p in v]
    for f in failed:
        print(f"knowcode-ci: check failed: {f}", file=sys.stderr)
    return 1 if failed else 0


SEVERITY = {"error": "critical", "warning": "major", "note": "minor", "none": "info"}


def codequality(sarif):
    """GitLab code quality issues for a SARIF log's results: one per result location."""
    issues = []
    for run in sarif.get("runs") or []:
        for r in run.get("results") or []:
            message = (r.get("message") or {}).get("text", "")
            for loc in r.get("locations") or [{}]:
                phys = loc.get("physicalLocation") or {}
                path = (phys.get("artifactLocation") or {}).get("uri", "")
                line = (phys.get("region") or {}).get("startLine", 1)
                fingerprint = hashlib.sha256(f"{r.get('ruleId')}\0{path}\0{line}\0{message}".encode()).hexdigest()
                issues.append({
                    "description": message,
                    "check_name": r.get("ruleId", "knowcode"),
                    "fingerprint": fingerprint,
                    "severity": SEVERITY.get(r.get("level", "warning"), "major"),
                    "location": {"path": path, "lines": {"begin": line}},
                })
    return issues


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("review")
    r.add_argument("--knowcode", required=True)
    r.add_argument("--repo", required=True)
    r.add_argument("--base", required=True)
    r.add_argument("--out", required=True)
    r.add_argument("--cache")
    # The ops the server is given, the first being the one asked: `review` and `more` unless testing.
    r.add_argument("--ops", type=lambda s: tuple(s.split(",")), default=OPS, help=argparse.SUPPRESS)
    c = sub.add_parser("codequality")
    c.add_argument("sarif")
    c.add_argument("out")
    args = ap.parse_args(argv)
    if args.cmd == "review":
        return review(args)
    Path(args.out).write_text(json.dumps(codequality(json.loads(Path(args.sarif).read_text())), indent=2) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
