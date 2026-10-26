#!/usr/bin/env bash
# Exercise the commands that manage runners on this Mac, with mock gh / launchctl / runner scripts.
# shellcheck source=tests/lib.sh
source "$(dirname "$0")/lib.sh"

LATEST=2.400.0

setup() {
  HOME=$TMP/home
  mkdir "$HOME" "$TMP/bin"
  local name
  for name in gh uname scutil launchctl curl tar; do
    ln -s "$MOCKS/local" "$TMP/bin/$name"
  done
  echo "dots me/dotfiles" >"$TMP/repos"
  export HOME PATH="$TMP/bin:$PATH" TEST_MOCKS=$MOCKS TEST_LOG=$TMP/calls.jsonl TEST_LATEST=$LATEST GH_RUNNERS_CONFIG=$TMP/repos
  DOTS=$(add_runner dotfiles host-dotfiles me/dotfiles 2.300.0)
  APP=$(add_runner app host-app org/app "$LATEST")
}

# add_runner SUFFIX NAME REPO VERSION: a registered runner directory; prints its path.
add_runner() {
  local d=$HOME/actions-runner-$1
  mkdir "$d"
  "$MOCKS/make-runner" "$d" "$4"
  # config.sh writes .runner with a BOM and indentation.
  printf '\xef\xbb\xbf{\n  "agentId": 1,\n  "agentName": "%s",\n  "gitHubUrl": "https://github.com/%s",\n  "workFolder": "_work"\n}' \
    "$2" "$3" >"$d/.runner"
  echo "$HOME/Library/LaunchAgents/actions.runner.$1.plist" >"$d/.service"
  echo "$d"
}

# steps NAME [FIELD] : FIELD (default 2: the first argument) of each logged call of NAME.
steps() { calls "select(.[0] == \"$1\") | .[${2:-2}]"; }

test_local_lists_runners() {
  TEST_RUNNING=actions.runner.dotfiles run local
  ok
  eq "$(head -n 1 <<<"$out")" $'NAME\tREPOSITORY\tSERVICE\tGITHUB\tVERSION\tDIR'
  has "$out" $'host-app\torg/app\tstopped\toffline\t'"$LATEST"$'\t'"$APP"
  has "$out" $'host-dotfiles\tme/dotfiles\trunning\tonline,busy\t2.300.0\t'"$DOTS"
}

test_local_accepts_a_runner() {
  GH_RUNNERS_FORMAT=table run local dots
  ok
  eq "$(wc -l <<<"$out" | tr -d ' ')" 2
  has "$out" "host-dotfiles  me/dotfiles  stopped  online,busy  2.300.0"
  run local nope
  not_ok
  has "$err" "No runner on this Mac matches: nope"
}

test_local_reports_unreadable_github_state() {
  TEST_SCENARIO=api-failure run local
  not_ok
  has "$err" "Some GitHub states could not be read"
  has "$out" $'host-app\torg/app\tstopped\t?'
}

test_local_json() {
  TEST_RUNNING=actions.runner.dotfiles run local --json
  ok
  json_eq "$(jq -c '.[] | select(.name == "host-dotfiles")' <<<"$out")" "{
    \"name\": \"host-dotfiles\", \"repository\": \"me/dotfiles\", \"service\": \"running\",
    \"status\": \"online\", \"busy\": true, \"version\": \"2.300.0\", \"dir\": \"$DOTS\"}"
  eq "$(jq -r '.[] | select(.name == "host-app") | .status' <<<"$out")" offline
  TEST_SCENARIO=api-failure run local --json
  not_ok
  json_eq "$(jq -c '[.[].status] | unique' <<<"$out")" '[null]'
}

test_select_by_name_repo_alias_and_dir() {
  local sel
  for sel in host-dotfiles me/dotfiles dots "$DOTS"; do
    rm -f "$TEST_LOG"
    run stop "$sel"
    ok "$sel"
    eq "$(calls 'select(.[0] == "svc.sh") | .[1:] | join(" ")')" "$DOTS stop"
  done
}

test_start_restart_all() {
  run start
  ok
  eq "$(steps svc.sh 1 | sort)" "$(printf '%s\n' "$DOTS" "$APP" | sort)"
  rm "$TEST_LOG"
  run restart host-app
  ok
  eq "$(steps svc.sh)" $'stop\nstart'
}

test_unknown_runner() {
  run stop nope
  not_ok
  has "$err" "No runner on this Mac matches: nope"
  eq "$(steps svc.sh)" ""
}

test_remove_needs_selector_and_confirmation() {
  run remove
  not_ok
  run remove all
  not_ok
  run remove host-app # stdin is not a terminal
  not_ok
  has "$err" "pass --yes"
  [[ -d $APP ]] || fail "$APP was deleted"
  eq "$(steps config.sh)" ""
}

test_remove() {
  run remove host-app --yes
  ok
  [[ ! -e $APP ]] || fail "$APP still exists"
  [[ -d $DOTS ]] || fail "$DOTS was deleted"
  has "$(calls)" "[\"gh\",\"$APP\",\"api\",\"-X\",\"POST\",\"repos/org/app/actions/runners/remove-token\",\"--jq\",\".token\"]"
  eq "$(steps config.sh)" remove
  has "$(calls)" "[\"launchctl\",\"$APP\",\"unload\",\"$HOME/Library/LaunchAgents/actions.runner.app.plist\"]"
}

test_remove_keep_dir_and_token_failure() {
  run remove dots --yes --keep-dir
  ok
  [[ -d $DOTS ]] || fail "$DOTS was deleted"
  [[ ! -e $DOTS/.runner ]] || fail "$DOTS/.runner still exists"
  TEST_SCENARIO=token-failure run remove host-app --yes
  not_ok
  [[ -d $APP ]] || fail "$APP was deleted while still registered"
  TEST_SCENARIO=config-failure run remove host-app --yes
  not_ok
  has "$err" "Could not unregister host-app"
  [[ -e $APP/.runner ]] || fail "$APP/.runner was deleted"
}

test_upgrade() {
  TEST_RUNNING=actions.runner.dotfiles run upgrade
  ok
  has "$out" "Upgraded host-dotfiles: 2.300.0 -> $LATEST"
  has "$out" "host-app is already $LATEST"
  eq "$(steps svc.sh)" $'stop\nstart'
  eq "$(steps tar 1)" "$DOTS"
  eq "$(<"$DOTS/.runner-version")" "$LATEST"
}

test_add_registers_new_runner() {
  run add org/new --labels mac
  ok
  local d=$HOME/actions-runner-new
  [[ -e $d/.runner ]] || fail "$d/.runner is missing"
  eq "$(steps config.sh)" --unattended
  eq "$(steps svc.sh)" $'install\nstart\nstatus'
  has "$out" "Registered org-new on org/new" # default name: <owner>-<repo>
  has "$(calls)" "[\"gh\",\"$d\",\"api\",\"-X\",\"POST\",\"repos/org/new/actions/runners/registration-token\",\"--jq\",\".token\"]"
}

test_add_replaces_existing_registration() {
  run setup --repo dots --name mine
  ok
  has "$out" "Registered mine on me/dotfiles"
  eq "$(steps config.sh)" $'remove\n--unattended'
  eq "$(steps tar 1)" "$DOTS" # old version upgraded
}

test_local_commands_need_macos() {
  mkdir "$TMP/linux-bin"
  printf '#!/bin/sh\necho Linux\n' >"$TMP/linux-bin/uname"
  chmod +x "$TMP/linux-bin/uname"
  local args
  for args in local stop upgrade "add org/x" "remove x --yes"; do
    PATH=$TMP/linux-bin:$PATH run $args
    not_ok "$args"
    has "$err" "macOS only"
  done
  eq "$(steps svc.sh)$(steps config.sh)" ""
}

main
