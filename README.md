# gh-runners

A [GitHub CLI](https://cli.github.com/) extension for self-hosted GitHub Actions runners.
See which runners are online / offline / busy and the recent workflow runs, across several repositories, and (re)register a runner on a Mac as a launchd service.

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
gh runners setup                # register a runner for the current repository on this Mac
gh runners aliases              # show the configured aliases
```

`list` and `runs` only read the GitHub API. Listing runners needs admin access to the repository (or a token that can read runners); plain read access often returns HTTP 403.
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

### setup (macOS, Apple Silicon)

```sh
gh runners setup [--repo TARGET] [--name NAME] [--dir DIR] [--labels LABELS]
```

Downloads the latest [actions/runner](https://github.com/actions/runner) into `DIR`, registers it with `--replace`, and installs and starts it as a launchd service.
Running it again gives the same state: an existing service and registration in `DIR` are removed first, and the runner is updated when a newer release is out.
Registration tokens are fetched with `gh api` each time and are never stored.

| Option | Default |
| --- | --- |
| `--repo` | the current repository |
| `--name` | `<LocalHostName>-<repo name>` |
| `--dir` | `~/actions-runner-<repo name>` |
| `--labels` | `<LocalHostName>` (plus the default `self-hosted`, `macOS`, `ARM64`) |

The account needs admin access to the repository.

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
shellcheck gh-runners
python3 tests/test_gh_runners.py   # uses a mock gh; needs jq
nix flake check
```

## License

MIT
