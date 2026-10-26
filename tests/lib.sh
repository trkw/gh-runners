# shellcheck shell=bash
# Minimal test harness, sourced by tests/test_*.sh. Needs bash and jq only.
# Each test_* function runs in its own subshell after setup(); an assertion that fails exits it.

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
MOCKS=$ROOT/tests/mock

# The tests set their own GH_* / TEST_* variables.
unset "${!GH_@}" "${!TEST_@}"

fail() {
  printf '  %s\n' "$@" >&2
  printf '  exit %s\n  --- stdout\n%s\n  --- stderr\n%s\n' "${rc:-}" "${out:-}" "${err:-}" >&2
  exit 1
}

# run ARGS... : run the extension; sets $out, $err and $rc. Environment prefixes apply (FOO=1 run ...).
run() {
  rc=0
  bash "$ROOT/gh-runners" "$@" >"$TMP/stdout" 2>"$TMP/stderr" </dev/null || rc=$?
  out=$(<"$TMP/stdout")
  err=$(<"$TMP/stderr")
}

ok() { [[ $rc == 0 ]] || fail "expected success: $*"; }
not_ok() { [[ $rc != 0 ]] || fail "expected failure: $*"; }
has() { [[ $1 == *"$2"* ]] || fail "expected to contain: $2"; }
lacks() { [[ $1 != *"$2"* ]] || fail "expected not to contain: $2"; }
eq() { [[ $1 == "$2" ]] || fail "expected: $2" "actual:   $1"; }
# json_eq JSON FILTER : the JSON equals jq FILTER (compared after normalising both).
json_eq() {
  jq -e --argjson want "$(jq -nc "$2")" '. == $want' <<<"$1" >/dev/null || fail "JSON is not $2"
}

# calls [FILTER] : the logged mock calls (one JSON array each), through jq FILTER, one result per line.
calls() {
  [[ -e $TEST_LOG ]] || return 0
  jq -r "${1:-.}" "$TEST_LOG" | if [[ ${1:-} ]]; then cat; else jq -c .; fi
}

main() {
  local t passed=0 failed=0
  for t in $(declare -F | sed -n "s/^declare -f \(test_.*\)/\1/p"); do
    TMP=$(mktemp -d)
    if (setup && "$t"); then
      passed=$((passed + 1))
    else
      failed=$((failed + 1))
      echo "FAIL $t" >&2
    fi
    rm -rf "$TMP"
  done
  echo "$passed passed, $failed failed"
  [[ $failed == 0 && $passed != 0 ]]
}
