#!/usr/bin/env bash
# Exercise routing, aliases, formatting and failures against a mock gh (no GitHub access).
# shellcheck source=tests/lib.sh
source "$(dirname "$0")/lib.sh"

setup() {
  mkdir "$TMP/bin"
  ln -s "$MOCKS/gh-remote" "$TMP/bin/gh"
  export PATH="$TMP/bin:$PATH" TEST_LOG=$TMP/calls.jsonl GH_RUNNERS_CONFIG=$TMP/repos
  cat >"$GH_RUNNERS_CONFIG" <<'CONFIG'
# test aliases
corp  example/corp  # inline comment
dots  example/dots
bad   forbidden/repo
CONFIG
}

api_urls() { calls 'select(.[0] == "api") | .[4]'; }
# arg_of NAME : the value after NAME in the last logged call.
arg_of() { calls | tail -n 1 | jq -r --arg k "$1" '.[index($k) + 1]'; }

test_current_repo_by_default() {
  for args in "" list; do
    rm -f "$TEST_LOG"
    run $args
    ok "$args"
    has "$out" "== cur/repo =="
    has "$out" $'runner-a\tonline,busy\tself-hosted,macos'
    has "$out" $'runner-b\toffline\t'
    eq "$(api_urls)" "repos/cur/repo/actions/runners?per_page=100"
  done
}

test_no_current_repo() {
  TEST_SCENARIO=no-repo run list
  not_ok
  has "$err" "Not in a GitHub repository"
  eq "$(api_urls)" ""
}

test_alias_explicit_repo_and_shorthand() {
  run list corp
  ok
  eq "$(api_urls | tail -n 1)" "repos/example/corp/actions/runners?per_page=100"
  run other/repo
  ok
  eq "$(api_urls | tail -n 1)" "repos/other/repo/actions/runners?per_page=100"
}

test_runs_limit() {
  run runs example/other 20
  ok
  has "$out" $'42\tsuccess\tCI\tBuild\tmain\t2026-10-26 00:00 UTC'
  has "$out" "https://github.com/o/r/actions/runs/42"
  eq "$(arg_of --repo)" example/other
  eq "$(arg_of --limit)" 20
  run runs dots
  eq "$(arg_of --repo)" example/dots
  eq "$(arg_of --limit)" 10
}

test_table_format_aligns_columns() {
  GH_RUNNERS_FORMAT=table run list corp
  ok
  has "$out" "NAME      STATUS       LABELS"
  has "$out" "runner-a  online,busy  self-hosted,macos"
  has "$out" "runner-b  offline"
  GH_RUNNERS_FORMAT=table run aliases
  has "$out" "corp  example/corp"
  GH_RUNNERS_FORMAT=nope run list corp
  not_ok
  has "$err" "must be table or tsv"
}

test_unknown_word_names_the_help() {
  run lst
  not_ok
  has "$err" "Unknown command or alias: lst"
}

test_json() {
  run list --json corp
  ok
  json_eq "$out" '[
    {"repository": "example/corp", "name": "runner-a", "status": "online", "busy": true,
     "labels": ["self-hosted", "macos"]},
    {"repository": "example/corp", "name": "runner-b", "status": "offline", "busy": false,
     "labels": []}]'
  run runs dots 5 --json
  ok
  json_eq "$out" '[
    {"repository": "example/dots", "id": 42, "status": "completed", "conclusion": "success",
     "workflow": "CI", "title": "Build", "branch": "main", "createdAt": "2026-10-26T00:00:00Z",
     "url": "https://github.com/o/r/actions/runs/42"}]'
  run aliases --json
  json_eq "$(jq -c '.[0]' <<<"$out")" '{"alias": "corp", "repository": "example/corp"}'
  TEST_SCENARIO=empty run --json corp
  json_eq "$out" '[]'
}

test_json_with_a_failing_repo_is_still_one_array() {
  TEST_SCENARIO=failure run list all --json
  not_ok
  has "$err" "Cannot read forbidden/repo"
  json_eq "$(jq -c '[.[].repository] | unique' <<<"$out")" '["example/corp", "example/dots"]'
}

test_json_rejected_by_other_commands() {
  run add --json
  not_ok
  has "$err" "--json works with"
  eq "$(calls)" ""
}

test_all_uses_every_alias() {
  run list all
  ok
  eq "$(api_urls)" "repos/example/corp/actions/runners?per_page=100
repos/example/dots/actions/runners?per_page=100
repos/forbidden/repo/actions/runners?per_page=100"
}

test_aliases_command() {
  run aliases
  ok
  eq "$out" $'corp\texample/corp\ndots\texample/dots\nbad\tforbidden/repo'
  eq "$(calls)" ""
}

test_empty_results() {
  TEST_SCENARIO=empty run list corp
  ok
  has "$out" "no runners visible"
  TEST_SCENARIO=empty run runs corp
  ok
  has "$out" "no workflow runs"
}

test_failure_still_attempts_remaining_repos() {
  for mode in list runs; do
    rm -f "$TEST_LOG"
    TEST_SCENARIO=failure run "$mode" all
    not_ok "$mode"
    has "$err" "HTTP 403"
    has "$err" "Cannot read forbidden/repo"
    lacks "$out" "no runners visible"
    eq "$(calls | wc -l | tr -d ' ')" 3
  done
}

test_invalid_args_do_not_call_api() {
  local args
  for args in "list nope" "list corp 1" "list ../bad/path" "runs corp 0" "runs corp 101" \
    "runs corp -1" "runs corp 1 extra" "aliases x"; do
    run $args
    not_ok "$args"
  done
  eq "$(calls)" ""
}

test_invalid_config() {
  echo "corp ../bad/path" >"$GH_RUNNERS_CONFIG"
  run list corp
  not_ok
  has "$err" "Invalid repository for alias corp"
  eq "$(calls)" ""
  run list other/repo # an explicit repository ignores the config
  ok
}

test_missing_config_all() {
  GH_RUNNERS_CONFIG=$TMP/none run list all
  not_ok
  has "$err" "No aliases"
}

test_help_does_not_call_api() {
  local args
  for args in --help "list --help" "runs -h" help; do
    run $args
    ok "$args"
    has "$out" "Usage:"
  done
  eq "$(calls)" ""
}

test_setup_refuses_off_macos() {
  [[ $(uname -s) == Darwin ]] && return 0 # only meaningful off macOS
  run setup --repo corp
  not_ok
  has "$err" "macOS only"
  eq "$(calls)" ""
}

main
