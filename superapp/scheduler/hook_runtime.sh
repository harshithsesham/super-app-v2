# Sourced by every hook polling script as $HATCH_HOOK_RUNTIME.
# Provides: log, silent, wake, disable_after_run. Each script run must end
# with exactly one silent or wake. Verdicts are written as JSON lines to the
# file named by $HATCH_HOOK_RESULT; the engine reads them after the script.
_hook_emit() {
  printf '{"kind":"%s","reason":%s,"payload":%s,"ts":%s}\n' "$1" "$(printf '%s' "$2" | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read()))')" "${3:-null}" "$(date +%s)" >> "$HATCH_HOOK_RESULT"
}
log() { _hook_emit observation "$1" "${2:-null}"; }
silent() { _hook_emit silent "$1" "${2:-null}"; exit 0; }
wake() { _hook_emit wake "$1" "${2:-null}"; exit 0; }
disable_after_run() { _hook_emit disable_after_run "requested" null; }
export HATCH_HOOK_DRY_RUN="${HATCH_HOOK_DRY_RUN:-0}"
