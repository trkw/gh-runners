# gh-runners

A [GitHub CLI](https://cli.github.com/) extension for self-hosted GitHub Actions runners.
See which runners are online / offline / busy and the recent workflow runs, across several repositories, and manage the runners on a Mac: register, remove, start / stop and upgrade them as launchd services.

```sh
gh extension install trkw/gh-runners
```

Requires `gh` (logged in with `gh auth login`) and bash. Nothing else: JSON is filtered with `gh --jq`.

## Usage

```sh
gh runners                      # runners of the current repository: name / status / busy / labels
gh runners list OWNER/REPO
gh runners list work            # an alias from the config file
gh runners list all             # every alias
gh runners runs                 # 10 recent workflow runs of the current repository
gh runners runs all 20          # 20 per repository (1..100)
gh runners aliases              # show the configured aliases

gh runners add                  # register a runner for the current repository on this Mac
gh runners local                # runners on this Mac: service state, GitHub status, version
gh runners local dots           # only that runner
gh runners stop dots            # stop / start / restart a runner (all runners when omitted)
gh runners upgrade              # update every runner on this Mac to the latest release
gh runners remove dots          # unregister it, uninstall the service, delete its directory
```

Tables are printed as aligned columns on a terminal and as tab-separated rows when the output is piped, so `gh runners list all | grep offline` keeps working; `GH_RUNNERS_FORMAT=table` or `=tsv` overrides the choice.

### JSON

`--json` (on `list`, `runs`, `local` and `aliases`) prints one JSON array for scripts and launchers, with full values (no truncation) and one object per runner, run or alias:

```sh
gh runners list all --json      # [{"repository", "name", "status", "busy", "labels": [...]}, ...]
gh runners runs dots 5 --json   # [{"repository", "id", "status", "conclusion", "workflow", "title", "branch", "createdAt", "url"}, ...]
gh runners local --json         # [{"name", "repository", "service", "status", "busy", "version", "dir"}, ...]
gh runners aliases --json       # [{"alias", "repository"}, ...]
```

With several repositories the array holds them all; a repository that cannot be read is reported on stderr and the exit status is non-zero, but the array is still printed.
In `local --json`, `status` and `busy` are `null` when GitHub could not be read, and `status` is `"not registered"` when the runner is missing on GitHub.

`list`, `runs`, `aliases` and `local` only read. Listing runners needs admin access to the repository (or a token that can read runners); plain read access often returns HTTP 403.
When one repository fails, the others are still shown and the command exits non-zero.
An API error is reported separately from an empty list.

Without a target, the current repository is used (`GH_REPO` or the git remote, as other `gh` commands do).

### Aliases

Put one `ALIAS OWNER/REPO` per line in `~/.config/gh-runners/repos` (`$XDG_CONFIG_HOME` is honoured; `GH_RUNNERS_CONFIG` overrides the path):

```
# ~/.config/gh-runners/repos
work   my-org/app
dots   me/dotfiles
```

`all` means every alias in the file.

### Runners on this Mac (macOS, Apple Silicon)

Each runner lives in its own directory `~/actions-runner-*` and runs as a launchd service installed by the runner's `svc.sh`.
The directories are the only state: `local`, `start`, `stop`, `restart`, `upgrade` and `remove` find runners by looking for a registration (`.runner`) in them.

`RUNNER` selects runners on this Mac by name, by directory, or by repository (`OWNER/REPO` or an alias).
`local`, `start`, `stop`, `restart` and `upgrade` act on every runner when it is omitted; `remove` always needs one.

#### add

```sh
gh runners add [TARGET] [--name NAME] [--dir DIR] [--labels LABELS]
```

Downloads the latest [actions/runner](https://github.com/actions/runner) into `DIR`, registers it with `--replace`, and installs and starts it as a launchd service.
Running it again gives the same state: an existing service and registration in `DIR` are removed first, and the runner is updated when a newer release is out.
Registration tokens are fetched with `gh api` each time and are never stored.
`setup` is an alias of `add`, and `--repo TARGET` works in place of the positional `TARGET`.

| Option | Default |
| --- | --- |
| `TARGET` | the current repository |
| `--name` | `<LocalHostName>-<repo name>` |
| `--dir` | `~/actions-runner-<repo name>` |
| `--labels` | `<LocalHostName>` (plus the default `self-hosted`, `macOS`, `ARM64`) |

The account needs admin access to the repository.

#### remove

```sh
gh runners remove RUNNER [--keep-dir] [--yes]
```

Uninstalls the launchd service, unregisters the runner from GitHub and deletes its directory (`--keep-dir` keeps it).
It asks for confirmation; pass `--yes` when not on a terminal.
If unregistering fails (the removal token or `config.sh remove`), it stops there and keeps the directory, so the removal can be retried (`gh runners add` restores the service).

#### upgrade

Runners usually update themselves, but `upgrade` brings a stopped or stuck one to the latest release: it stops a running service, unpacks the release over the directory and starts it again.

## Nix

The flake provides the extension as a package, for Home Manager's `programs.gh.extensions`:

```nix
# flake.nix
inputs.gh-runners = {
  url = "github:trkw/gh-runners";
  inputs.nixpkgs.follows = "nixpkgs";
};

# Home Manager module
programs.gh.extensions = [ inputs.gh-runners.packages.${pkgs.stdenv.hostPlatform.system}.default ];
xdg.configFile."gh-runners/repos".text = ''
  dots me/dotfiles
'';
```

## Development

```sh
shellcheck -x gh-runners tests/test_*.sh tests/mock/*
bash tests/test_gh_runners.sh   # mock gh; needs jq
bash tests/test_local.sh        # mock gh / launchctl / runner scripts
nix flake check
```

## License

MIT
