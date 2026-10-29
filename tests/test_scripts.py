"""Tests for the action's and the template's scripts: the scope check, the unchanged-repo check, the code quality
report and the comment's fit. Standard library only: python3 -m unittest discover -s tests"""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import kc_ci  # noqa: E402
import post  # noqa: E402


def init(scope):
    return {"result": {"capabilities": {"experimental": {"knowcode/scope": scope}}}}


class ScopeTest(unittest.TestCase):
    def scope(self, repo, **over):
        s = {"restricted": True, "repos": [{"name": "shop", "path": str(repo)}], "ops": ["capabilities", "more", "review"],
             "discovery": False, "update_checks": False, "plugin_refresh": False, "git_network": False}
        s.update(over)
        return s

    def test_the_bound_repo_and_the_review_ops_pass(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(kc_ci.scope_problems(init(self.scope(d)), d), [])

    def test_another_repo_more_ops_or_discovery_fail(self):
        with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as other:
            self.assertTrue(kc_ci.scope_problems(init(self.scope(other)), d))
            self.assertTrue(kc_ci.scope_problems(init(self.scope(d, ops=["review", "more", "search"])), d))
            self.assertTrue(kc_ci.scope_problems(init(self.scope(d, discovery=True)), d))
            self.assertTrue(kc_ci.scope_problems(init(self.scope(d, restricted=False)), d))
            self.assertTrue(kc_ci.scope_problems({"result": {}}, d))


class UnchangedTest(unittest.TestCase):
    def test_an_edit_an_index_change_or_a_new_ref_is_seen(self):
        with tempfile.TemporaryDirectory() as d:
            git = lambda *a: subprocess.run(["git", "-C", d, "-c", "user.name=t", "-c", "user.email=t@example.com", *a],
                                            check=True, capture_output=True)
            git("init", "-q")
            Path(d, "a.txt").write_text("a\n")
            git("add", "a.txt")
            git("commit", "-q", "-m", "a")
            before = kc_ci.state(d)
            self.assertEqual(kc_ci.differences(before, kc_ci.state(d)), [])
            Path(d, "a.txt").write_text("b\n")
            self.assertTrue(any("a.txt" in x for x in kc_ci.differences(before, kc_ci.state(d))))
            Path(d, "a.txt").write_text("a\n")
            git("tag", "t")
            self.assertTrue(any("refs" in x for x in kc_ci.differences(before, kc_ci.state(d))))


class RulesConfigTest(unittest.TestCase):
    def test_only_relative_paths_present_in_the_repo_are_configured(self):
        with tempfile.TemporaryDirectory() as d:
            Path(d, ".knowcode/rules").mkdir(parents=True)
            Path(d, "lint.yml").write_text("id: x\n")
            got = kc_ci.rules_config(d, [".knowcode/rules", "lint.yml", "missing", "../outside", "/etc"])
            self.assertEqual(got, '[rules]\npaths = [".knowcode/rules", "lint.yml"]\n')
            self.assertEqual(kc_ci.rules_config(d, ["missing"]), "")


class CodeQualityTest(unittest.TestCase):
    def test_each_result_location_is_an_issue(self):
        sarif = {"runs": [{"results": [
            {"ruleId": "contract-break", "level": "error", "message": {"text": "route removed"},
             "locations": [{"physicalLocation": {"artifactLocation": {"uri": "src/A.cs"}, "region": {"startLine": 4}}}]},
            {"ruleId": "possible-break", "level": "warning", "message": {"text": "maybe"},
             "locations": [{"physicalLocation": {"artifactLocation": {"uri": "src/B.cs"}, "region": {"startLine": 9}}}]},
        ]}]}
        issues = kc_ci.codequality(sarif)
        self.assertEqual([(i["check_name"], i["severity"], i["location"]) for i in issues], [
            ("contract-break", "critical", {"path": "src/A.cs", "lines": {"begin": 4}}),
            ("possible-break", "major", {"path": "src/B.cs", "lines": {"begin": 9}}),
        ])
        self.assertEqual(len({i["fingerprint"] for i in issues}), 2)
        json.dumps(issues)


class FitTest(unittest.TestCase):
    def test_a_long_body_is_cut_at_a_line_and_says_so(self):
        body = "".join(f"line {i}\n" for i in range(1000))
        cut = post.fit(body, 500)
        self.assertLessEqual(len(cut), 500)
        self.assertIn("cut here", cut)
        self.assertTrue(cut.split("\n\n_The")[0].endswith("\n"))
        self.assertEqual(post.fit("short\n", 500), "short\n")


if __name__ == "__main__":
    unittest.main()
