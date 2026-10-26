#!/usr/bin/env python3
"""Exercise the commands that manage runners on this Mac, with mock gh / launchctl / runner scripts."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
LATEST = "2.400.0"

# One mock for every external command; it logs [name, *args] and acts by name.
MOCK = r'''import json, os, subprocess, sys
name = os.path.basename(sys.argv[0])
args = sys.argv[1:]
with open(os.environ["TEST_LOG"], "a") as log:
    log.write(json.dumps([name, os.getcwd()] + args) + "\n")
latest = os.environ["TEST_LATEST"]
if name == "uname":
    print("Darwin" if args == ["-s"] else "arm64")
elif name == "scutil":
    print("host")
elif name == "launchctl":
    # "list LABEL": running when the label is in TEST_RUNNING
    if args[0] == "list":
        if args[1] not in os.environ.get("TEST_RUNNING", "").split(","):
            sys.exit(113)
        print('{\n\t"Label" = "%s";\n\t"PID" = 42;\n};' % args[1])
elif name == "curl":
    open(args[args.index("-o") + 1], "w").close()
elif name == "tar":
    # Unpacking the release writes the runner scripts of the latest version.
    exec(open(os.environ["TEST_MAKE_RUNNER"]).read())
    make_scripts(os.getcwd(), latest)
elif name == "gh":
    if args[:2] == ["auth", "status"]:
        pass
    elif "repos/actions/runner/releases/latest" in args:
        print(latest)
    elif args[:3] == ["api", "-X", "POST"]:
        if os.environ.get("TEST_SCENARIO") == "token-failure":
            print("HTTP 403", file=sys.stderr)
            sys.exit(1)
        print("TOKEN")
    elif args[0] == "api":
        if os.environ.get("TEST_SCENARIO") == "api-failure":
            print("HTTP 403", file=sys.stderr)
            sys.exit(1)
        rows = [{"name": "host-dotfiles", "status": "online", "busy": True},
                {"name": "host-app", "status": "offline", "busy": False}]
        sys.exit(subprocess.run(["jq", "-r", args[args.index("--jq") + 1]],
                                input=json.dumps({"runners": rows}), text=True).returncode)
    else:
        raise AssertionError("Unexpected gh command: " + repr(args))
'''

# Shared with the tar mock: fake runner scripts that log their calls.
MAKE_RUNNER = r'''import os, stat
def make_scripts(d, version, log=None):
    os.makedirs(os.path.join(d, "bin"), exist_ok=True)
    log = log or os.environ["TEST_LOG"]
    for rel, body in [
        ("config.sh", 'printf "%s\\n" "[\\"config.sh\\", \\"$PWD\\", \\"$1\\"]" >> ' + log + '\n'
                      '[ "$1" = remove ] && [ "$TEST_SCENARIO" = config-failure ] && exit 1\n'
                      '[ "$1" = remove ] && rm -f .runner\n'
                      '[ "$1" = --unattended ] && printf "{\\"agentName\\": \\"new\\", \\"gitHubUrl\\": \\"https://github.com/x/y\\"}" > .runner\n'
                      'exit 0\n'),
        ("svc.sh", 'printf "%s\\n" "[\\"svc.sh\\", \\"$PWD\\", \\"$1\\"]" >> ' + log + '\n'
                   '[ "$1" = install ] && echo "$PWD/x.plist" > .service\nexit 0\n'),
        ("bin/Runner.Listener", "echo " + version + "\n"),
    ]:
        p = os.path.join(d, rel)
        with open(p, "w") as f:
            f.write("#!/bin/sh\n" + body)
        os.chmod(p, os.stat(p).st_mode | stat.S_IXUSR)
'''


class LocalTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name)
        self.home = self.path / "home"
        self.home.mkdir()
        bin_dir = self.path / "bin"
        bin_dir.mkdir()
        for name in ("gh", "uname", "scutil", "launchctl", "curl", "tar"):
            p = bin_dir / name
            p.write_text(f"#!{sys.executable}\n" + MOCK)
            p.chmod(0o755)
        make = self.path / "make_runner.py"
        make.write_text(MAKE_RUNNER)
        self.log = self.path / "calls.jsonl"
        config = self.path / "repos"
        config.write_text("dots me/dotfiles\n")
        self.env = {k: v for k, v in os.environ.items() if not k.startswith(("GH_", "TEST_"))}
        self.env.update(PATH=f"{bin_dir}:{os.environ['PATH']}", HOME=str(self.home),
                        TEST_LOG=str(self.log), TEST_LATEST=LATEST, TEST_MAKE_RUNNER=str(make),
                        GH_RUNNERS_CONFIG=str(config))
        ns = {}
        exec(MAKE_RUNNER, ns)
        self.make_scripts = ns["make_scripts"]
        self.dots = self.add_runner("dotfiles", "host-dotfiles", "me/dotfiles", "2.300.0")
        self.app = self.add_runner("app", "host-app", "org/app", LATEST)

    def add_runner(self, suffix, name, repo, version):
        d = self.home / f"actions-runner-{suffix}"
        d.mkdir()
        self.make_scripts(str(d), version, str(self.log))
        # config.sh writes .runner with a BOM and indentation.
        (d / ".runner").write_text('\ufeff{\n  "agentId": 1,\n  "agentName": "%s",\n'
                                   '  "gitHubUrl": "https://github.com/%s",\n  "workFolder": "_work"\n}' % (name, repo))
        (d / ".service").write_text(f"{self.home}/Library/LaunchAgents/actions.runner.{suffix}.plist\n")
        return d

    def run_cli(self, *args, **env):
        return subprocess.run(["bash", str(ROOT / "gh-runners"), *args], env=self.env | env,
                              text=True, capture_output=True, stdin=subprocess.DEVNULL)

    def calls(self, name=None):
        rows = [json.loads(l) for l in self.log.read_text().splitlines()] if self.log.exists() else []
        return [r for r in rows if name is None or r[0] == name]

    def test_local_lists_runners(self):
        result = self.run_cli("local", TEST_RUNNING="actions.runner.dotfiles")
        self.assertEqual(result.returncode, 0, result.stderr)
        lines = result.stdout.splitlines()
        self.assertEqual(lines[0], "NAME\tREPOSITORY\tSERVICE\tGITHUB\tVERSION\tDIR")
        self.assertIn(f"host-app\torg/app\tstopped\toffline\t{LATEST}\t{self.app}", lines)
        self.assertIn(f"host-dotfiles\tme/dotfiles\trunning\tonline,busy\t2.300.0\t{self.dots}", lines)

    def test_local_accepts_a_runner(self):
        result = self.run_cli("local", "dots", GH_RUNNERS_FORMAT="table")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(result.stdout.splitlines()), 2)
        self.assertIn("host-dotfiles  me/dotfiles  stopped  online,busy  2.300.0", result.stdout)
        result = self.run_cli("local", "nope")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("No runner on this Mac matches: nope", result.stderr)

    def test_local_reports_unreadable_github_state(self):
        result = self.run_cli("local", TEST_SCENARIO="api-failure")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Some GitHub states could not be read", result.stderr)
        self.assertIn("host-app\torg/app\tstopped\t?", result.stdout)

    def test_select_by_name_repo_alias_and_dir(self):
        for sel in ("host-dotfiles", "me/dotfiles", "dots", str(self.dots)):
            self.log.unlink(missing_ok=True)
            result = self.run_cli("stop", sel)
            self.assertEqual(result.returncode, 0, (sel, result.stderr))
            self.assertEqual([c[1:] for c in self.calls("svc.sh")], [[str(self.dots), "stop"]], sel)

    def test_start_restart_all(self):
        result = self.run_cli("start")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(sorted(c[1] for c in self.calls("svc.sh")), sorted([str(self.dots), str(self.app)]))
        self.log.unlink()
        result = self.run_cli("restart", "host-app")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual([c[2] for c in self.calls("svc.sh")], ["stop", "start"])

    def test_unknown_runner(self):
        result = self.run_cli("stop", "nope")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("No runner on this Mac matches: nope", result.stderr)
        self.assertEqual(self.calls("svc.sh"), [])

    def test_remove_needs_selector_and_confirmation(self):
        for args in [("remove",), ("remove", "all")]:
            result = self.run_cli(*args)
            self.assertNotEqual(result.returncode, 0, args)
        result = self.run_cli("remove", "host-app")  # stdin is not a terminal
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("pass --yes", result.stderr)
        self.assertTrue(self.app.exists())
        self.assertEqual(self.calls("config.sh"), [])

    def test_remove(self):
        result = self.run_cli("remove", "host-app", "--yes")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(self.app.exists())
        self.assertTrue(self.dots.exists())
        self.assertIn(["gh", str(self.app), "api", "-X", "POST", "repos/org/app/actions/runners/remove-token",
                       "--jq", ".token"], self.calls("gh"))
        self.assertEqual([c[2] for c in self.calls("config.sh")], ["remove"])
        self.assertIn(["launchctl", str(self.app), "unload",
                       f"{self.home}/Library/LaunchAgents/actions.runner.app.plist"], self.calls("launchctl"))

    def test_remove_keep_dir_and_token_failure(self):
        result = self.run_cli("remove", "dots", "--yes", "--keep-dir")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(self.dots.exists())
        self.assertFalse((self.dots / ".runner").exists())
        result = self.run_cli("remove", "host-app", "--yes", TEST_SCENARIO="token-failure")
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(self.app.exists())  # never deleted while still registered
        result = self.run_cli("remove", "host-app", "--yes", TEST_SCENARIO="config-failure")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Could not unregister host-app", result.stderr)
        self.assertTrue((self.app / ".runner").exists())

    def test_upgrade(self):
        result = self.run_cli("upgrade", TEST_RUNNING="actions.runner.dotfiles")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(f"Upgraded host-dotfiles: 2.300.0 -> {LATEST}", result.stdout)
        self.assertIn(f"host-app is already {LATEST}", result.stdout)
        self.assertEqual([c[2] for c in self.calls("svc.sh")], ["stop", "start"])
        self.assertEqual([c[1] for c in self.calls("tar")], [str(self.dots)])
        self.assertEqual((self.dots / ".runner-version").read_text().strip(), LATEST)

    def test_add_registers_new_runner(self):
        result = self.run_cli("add", "org/new", "--labels", "mac")
        self.assertEqual(result.returncode, 0, result.stderr)
        d = self.home / "actions-runner-new"
        self.assertTrue((d / ".runner").exists())
        self.assertEqual([c[2] for c in self.calls("config.sh")], ["--unattended"])
        self.assertEqual([c[2] for c in self.calls("svc.sh")], ["install", "start", "status"])
        self.assertIn(["gh", str(d), "api", "-X", "POST", "repos/org/new/actions/runners/registration-token",
                       "--jq", ".token"], self.calls("gh"))

    def test_add_replaces_existing_registration(self):
        result = self.run_cli("setup", "--repo", "dots")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual([c[2] for c in self.calls("config.sh")], ["remove", "--unattended"])
        self.assertEqual([c[1] for c in self.calls("tar")], [str(self.dots)])  # old version upgraded

    def test_local_commands_need_macos(self):
        bin_dir = self.path / "linux-bin"
        bin_dir.mkdir()
        (bin_dir / "uname").write_text("#!/bin/sh\necho Linux\n")
        (bin_dir / "uname").chmod(0o755)
        for args in [("local",), ("stop",), ("upgrade",), ("add", "org/x"), ("remove", "x", "--yes")]:
            result = self.run_cli(*args, PATH=f"{bin_dir}:{self.env['PATH']}")
            self.assertNotEqual(result.returncode, 0, args)
            self.assertIn("macOS only", result.stderr)
        self.assertEqual(self.calls("svc.sh") + self.calls("config.sh"), [])


if __name__ == "__main__":
    unittest.main()
