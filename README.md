# knowcode-ci

CI integrations for [KnowCode](https://github.com/bubstackdev/know-code): a GitHub Action and a GitLab CI template
that run `knowcode review` on a pull or merge request. They report the change's impact, the tests to run, breaking
changes across repos and rule matches, with no model call and no hosted service.

Work in progress. It arrives with KnowCode 0.8. The plan is
[docs/plans/0.8.md](https://github.com/bubstackdev/know-code/blob/integration/0.8/docs/plans/0.8.md).

## What a run does

1. Installs a pinned KnowCode release: the archive for the runner, checked against the release's SHA-256 and its
   build provenance attestation ([scripts/install.sh](scripts/install.sh)).
2. Runs KnowCode in restricted mode ([scripts/kc_ci.py](scripts/kc_ci.py)): `knowcode serve --restricted`, bound to
   the checked-out repo alone, allowed only the review ops, with its own cache and config outside the checkout. Before
   asking anything it checks the scope the server states, and that an op it wasn't given and a path outside the repo
   are refused.
3. Asks for the review of the change against its base, as markdown and as SARIF.
4. Checks that the checkout's files and git state (HEAD, refs, index, config, status) are as they were. Any check
   failing fails the job.
5. Posts: the workflow, not KnowCode, posts the markdown as one comment (updated in place on later runs) and uploads
   the SARIF, with the platform's own token. KnowCode only prints and never sees a token.

## GitHub

```yaml
on: pull_request
permissions:
  contents: read
  pull-requests: write
  security-events: write
jobs:
  review:
    runs-on: ubuntu-24.04
    steps:
      - uses: actions/checkout@v7
        with:
          fetch-depth: 0
      - uses: bubstackdev/knowcode-ci@v0
```

Inputs: `version` (the KnowCode release; each release of this action pins one), `base` (default: the pull request's
base commit), `comment`, `sarif` and `cache` (each `true` by default) and `token` (default: the workflow's
`GITHUB_TOKEN`). Runners need glibc 2.39 or later (Ubuntu 24.04) or macOS on Apple silicon.

## GitLab

```yaml
include:
  - remote: https://raw.githubusercontent.com/bubstackdev/knowcode-ci/v0/gitlab/knowcode-review.gitlab-ci.yml
```

The `knowcode-review` job runs on merge request pipelines. It posts the review as a merge request note when the
CI/CD variable `KNOWCODE_GITLAB_TOKEN` holds a project access token (`api` scope, Reporter role), and always reports
the findings as a code quality report and keeps the review in the job's artifacts.

## Versions

Releases follow KnowCode's: `v0.8.0` runs KnowCode 0.8.0. The `v0` tag follows the latest `v0.x.y`; only this
repository's release workflow moves it. Pin a full version, or a commit, to stay on one.

Licensed under either of Apache License 2.0 ([LICENSE-APACHE](LICENSE-APACHE)) or MIT ([LICENSE-MIT](LICENSE-MIT)),
at your option, as KnowCode is.
