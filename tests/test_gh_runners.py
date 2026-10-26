#!/usr/bin/env python3
"""Exercise routing, aliases, formatting and failures against a mock gh (no GitHub access)."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]

MOCK_GH = r'''import json, os, subprocess, sys
args = sys.argv[1:]
with open(os.environ["TEST_LOG"], "a") as log:
    log.write(json.dumps(args) + "\n")
scenario = os.environ.get("TEST_SCENARIO", "normal")

def jq(data):
    sys.exit(subprocess.run(["jq", "-r", args[args.index("--jq") + 1]],
                            input=json.dumps(data), text=True).returncode)

if args[:2] == ["repo", "view"]:
    if scenario == "no-repo":
        print("no git remotes found", file=sys.stderr)
        sys.exit(1)
    jq({"nameWithOwner": "cur/repo"})
if scenario == "failure" and any("forbidden/repo" in arg for arg in args):
    print("HTTP 403: forbidden", file=sys.stderr)
    sys.exit(1)
if args[0] == "api":
    assert "--method" in args and args[args.index("--method") + 1] == "GET"
    assert "--paginate" in args
    rows = [] if scenario == "empty" else [
        {"name": "runner-a", "status": "online", "busy": True,
         "labels": [{"name": "self-hosted"}, {"name": "macos"}]},
        {"name": "runner-b", "status": "offline", "busy": False, "labels": []}]
    # --paginate applies --jq to each page separately.
    out = subprocess.run(["jq", "-r", args[args.index("--jq") + 1]],
                         input=json.dumps({"runners": rows}), text=True)
    sys.exit(out.returncode)
elif args[:2] == ["run", "list"]:
    rows = [] if scenario == "empty" else [
        {"databaseId": 42, "status": "completed", "conclusion": "success",
         "workflowName": "CI", "displayTitle": "Build", "headBranch": "main",
         "createdAt": "2026-10-26T00:00:00Z", "url": "https://github.com/o/r/actions/runs/42"}]
    jq(rows)
else:
    raise AssertionError("Unexpected / mutating gh command: " + repr(args))
'''

CONFIG = """# test aliases
corp  example/corp  # inline comment
dots  example/dots
bad   forbidden/repo
"""


class GhRunnersTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name)
        gh = self.path / "gh"
        gh.write_text(f"#!{sys.executable}\n" + MOCK_GH)
        gh.chmod(0o755)
        self.config = self.path / "repos"
        self.config.write_text(CONFIG)
        self.log = self.path / "calls.jsonl"
        self.env = {key: value for key, value in os.environ.items()
                    if not key.startswith(("GH_", "TEST_"))}
        self.env.update(PATH=f"{self.path}:{os.environ['PATH']}", TEST_LOG=str(self.log),
                        GH_RUNNERS_CONFIG=str(self.config))

    def run_cli(self, *args, **env):
        return subprocess.run(["bash", str(ROOT / "gh-runners"), *args],
                              env=self.env | env, text=True, capture_output=True)

    def calls(self):
        return [json.loads(line) for line in self.log.read_text().splitlines()] if self.log.exists() else []

    def api_calls(self):
        return [call for call in self.calls() if call[0] == "api"]

    def test_current_repo_by_default(self):
        for args in [(), ("list",)]:
            self.log.unlink(missing_ok=True)
            result = self.run_cli(*args)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("== cur/repo ==", result.stdout)
            self.assertIn("runner-a\tonline,busy\tself-hosted,macos", result.stdout)
            self.assertIn("runner-b\toffline\t", result.stdout)
            self.assertIn("repos/cur/repo/actions/runners?per_page=100", self.api_calls()[0])

    def test_no_current_repo(self):
        result = self.run_cli("list", TEST_SCENARIO="no-repo")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Not in a GitHub repository", result.stderr)
        self.assertEqual(self.api_calls(), [])

    def test_alias_explicit_repo_and_shorthand(self):
        result = self.run_cli("list", "corp")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("repos/example/corp/actions/runners?per_page=100", self.api_calls()[-1])
        result = self.run_cli("other/repo")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("repos/other/repo/actions/runners?per_page=100", self.api_calls()[-1])

    def test_runs_limit(self):
        result = self.run_cli("runs", "example/other", "20")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("42\tsuccess\tCI\tBuild\tmain\t2026-10-26 00:00 UTC", result.stdout)
        self.assertIn("https://github.com/o/r/actions/runs/42", result.stdout)
        call = self.calls()[-1]
        self.assertEqual(call[call.index("--repo") + 1], "example/other")
        self.assertEqual(call[call.index("--limit") + 1], "20")
        result = self.run_cli("runs", "dots")
        call = self.calls()[-1]
        self.assertEqual(call[call.index("--repo") + 1], "example/dots")
        self.assertEqual(call[call.index("--limit") + 1], "10")

    def test_table_format_aligns_columns(self):
        result = self.run_cli("list", "corp", GH_RUNNERS_FORMAT="table")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("NAME      STATUS       LABELS", result.stdout)
        self.assertIn("runner-a  online,busy  self-hosted,macos", result.stdout)
        self.assertIn("runner-b  offline", result.stdout)
        result = self.run_cli("aliases", GH_RUNNERS_FORMAT="table")
        self.assertIn("corp  example/corp", result.stdout)
        result = self.run_cli("list", "corp", GH_RUNNERS_FORMAT="nope")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("must be table or tsv", result.stderr)

    def test_unknown_word_names_the_help(self):
        result = self.run_cli("lst")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Unknown command or alias: lst", result.stderr)

    def test_json(self):
        result = self.run_cli("list", "--json", "corp")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), [
            {"repository": "example/corp", "name": "runner-a", "status": "online", "busy": True,
             "labels": ["self-hosted", "macos"]},
            {"repository": "example/corp", "name": "runner-b", "status": "offline", "busy": False,
             "labels": []}])
        result = self.run_cli("runs", "dots", "5", "--json")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), [
            {"repository": "example/dots", "id": 42, "status": "completed", "conclusion": "success",
             "workflow": "CI", "title": "Build", "branch": "main", "createdAt": "2026-10-26T00:00:00Z",
             "url": "https://github.com/o/r/actions/runs/42"}])
        result = self.run_cli("aliases", "--json")
        self.assertEqual(json.loads(result.stdout)[0], {"alias": "corp", "repository": "example/corp"})
        result = self.run_cli("--json", "corp", TEST_SCENARIO="empty")
        self.assertEqual(json.loads(result.stdout), [])

    def test_json_with_a_failing_repo_is_still_one_array(self):
        result = self.run_cli("list", "all", "--json", TEST_SCENARIO="failure")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Cannot read forbidden/repo", result.stderr)
        rows = json.loads(result.stdout)
        self.assertEqual(sorted({r["repository"] for r in rows}), ["example/corp", "example/dots"])

    def test_json_rejected_by_other_commands(self):
        result = self.run_cli("add", "--json")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("--json works with", result.stderr)
        self.assertEqual(self.calls(), [])

    def test_all_uses_every_alias(self):
        result = self.run_cli("list", "all")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual([c[4] for c in self.api_calls()], [
            "repos/example/corp/actions/runners?per_page=100",
            "repos/example/dots/actions/runners?per_page=100",
            "repos/forbidden/repo/actions/runners?per_page=100"])

    def test_aliases_command(self):
        result = self.run_cli("aliases")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(),
                         ["corp\texample/corp", "dots\texample/dots", "bad\tforbidden/repo"])
        self.assertEqual(self.calls(), [])

    def test_empty_results(self):
        for mode, message in [("list", "no runners visible"), ("runs", "no workflow runs")]:
            result = self.run_cli(mode, "corp", TEST_SCENARIO="empty")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn(message, result.stdout)

    def test_failure_still_attempts_remaining_repos(self):
        for mode in ("list", "runs"):
            self.log.unlink(missing_ok=True)
            result = self.run_cli(mode, "all", TEST_SCENARIO="failure")
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("HTTP 403", result.stderr)
            self.assertIn("Cannot read forbidden/repo", result.stderr)
            self.assertNotIn("no runners visible", result.stdout)
            self.assertEqual(len(self.calls()), 3)

    def test_invalid_args_do_not_call_api(self):
        for args in [("list", "nope"), ("list", "corp", "1"), ("list", "../bad/path"),
                     ("runs", "corp", "0"), ("runs", "corp", "101"),
                     ("runs", "corp", "-1"), ("runs", "corp", "1", "extra"),
                     ("aliases", "x")]:
            result = self.run_cli(*args)
            self.assertNotEqual(result.returncode, 0, args)
        self.assertEqual(self.calls(), [])

    def test_invalid_config(self):
        self.config.write_text("corp ../bad/path\n")
        result = self.run_cli("list", "corp")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Invalid repository for alias corp", result.stderr)
        self.assertEqual(self.calls(), [])
        result = self.run_cli("list", "other/repo")  # an explicit repository ignores the config
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_missing_config_all(self):
        result = self.run_cli("list", "all", GH_RUNNERS_CONFIG=str(self.path / "none"))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("No aliases", result.stderr)

    def test_help_does_not_call_api(self):
        for args in [("--help",), ("list", "--help"), ("runs", "-h"), ("help",)]:
            result = self.run_cli(*args)
            self.assertEqual(result.returncode, 0, args)
            self.assertIn("Usage:", result.stdout)
        self.assertEqual(self.calls(), [])

    def test_setup_refuses_off_macos(self):
        if os.uname().sysname == "Darwin":
            self.skipTest("only meaningful off macOS")
        result = self.run_cli("setup", "--repo", "corp")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("macOS only", result.stderr)
        self.assertEqual(self.calls(), [])


if __name__ == "__main__":
    unittest.main()
