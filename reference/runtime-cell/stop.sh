#!/bin/sh
set -eu

machine=htch-runtime
ready_file=/run/hatch/runtime-cell/runtime-cell.ready
handoff_dir="/run/hatch/runtime-cell"
machine_state_file="/run/systemd/machines/$machine"
machine_unit_link="/run/systemd/machines/unit:com.hatch.runtime-cell.service"
machine_propagate_dir="/run/systemd/nspawn/propagate/$machine"
daemon_ctl_dir="/run/hatch/daemon-ctl"
graceful_poweroff_attempts="${runtime_cell_stop_poweroff_attempts:-50}"
terminate_attempts="${runtime_cell_stop_terminate_attempts:-30}"
kill_attempts="${runtime_cell_stop_kill_attempts:-30}"
spawnd_bin="/opt/hatch/bin/spawnd"

log_stop() {
    echo "runtime-cell stop: $*" >&2
}

emit_mount_stop_lifecycle_event() {
    phase="$1"
    event="$2"
    timestamp_ms="$3"
    status="${4:-}"
    if [ -n "$status" ]; then
        "$spawnd_bin" emit-mount-stop-lifecycle \
            --phase "$phase" \
            --event "$event" \
            --timestamp-ms "$timestamp_ms" \
            --status "$status" || true
    else
        "$spawnd_bin" emit-mount-stop-lifecycle \
            --phase "$phase" \
            --event "$event" \
            --timestamp-ms "$timestamp_ms" || true
    fi
}

emit_daemon_lifecycle_event() {
    "$spawnd_bin" emit-daemon-lifecycle --phase "$1" || true
}

machine_exists() {
    machinectl show "$machine" >/dev/null 2>&1
}

machine_leader() {
    machinectl show "$machine" -p Leader --value 2>/dev/null || true
}

machine_leader_is_live() {
    leader="$(machine_leader)"
    [ -n "$leader" ] && [ "$leader" != "0" ] && kill -0 "$leader" >/dev/null 2>&1
}

clear_stale_machine_state() {
    if command -v busctl >/dev/null 2>&1; then
        busctl call \
            org.freedesktop.machine1 \
            /org/freedesktop/machine1 \
            org.freedesktop.machine1.Manager \
            UnregisterMachine s "$machine" >/dev/null 2>&1 || true
    fi
    rm -f "$machine_state_file" "$machine_unit_link" || true
    rm -rf "$machine_propagate_dir" || true
}

wait_for_machine_gone() {
    attempts="$1"
    for i in $(seq 1 "$attempts"); do
        if ! machine_exists; then
            return 0
        fi
        if ! machine_leader_is_live; then
            clear_stale_machine_state
            if ! machine_exists; then
                return 0
            fi
        fi
        sleep 0.1
    done
    return 1
}

attempt_machine_terminate() {
    log_stop "sending terminate to machine=$machine"
    machinectl terminate "$machine" 2>/dev/null || true
    wait_for_machine_gone "$terminate_attempts"
}

attempt_machine_kill() {
    log_stop "sending kill to machine=$machine"
    machinectl kill --signal=KILL --kill-whom=all "$machine" 2>/dev/null || true
    wait_for_machine_gone "$kill_attempts"
}

fast_cleanup_machine() {
    reason="$1"
    log_stop "skipping graceful poweroff: machine=$machine reason=$reason"
    clear_stale_machine_state
    if attempt_machine_terminate; then
        return 0
    fi
    if attempt_machine_kill; then
        return 0
    fi
    log_stop "machine still registered after forced cleanup; clearing stale state before retry: machine=$machine"
    clear_stale_machine_state
    wait_for_machine_gone 1 || true
    return 0
}

emit_daemon_lifecycle_event stop-observed

rm -f "$ready_file"
# RT-3: lifecycle handoff files live in root-owned /run/hatch/daemon-ctl now;
# /run/hatch/daemon is the daemon SOCKET dir only and holds nothing to clean.
rm -f \
    "$handoff_dir/shellworks-daemon-lifecycle-context.json" \
    "$handoff_dir/shellworks-daemon-lifecycle-identity.json" \
    "$handoff_dir/shellworks-wake-bootstrap-context.json" \
    "$handoff_dir/jarvis-runtime-cell-bootstrap-identity.json" \
    "$daemon_ctl_dir/runtime-cell-pre-start-started-at-ms" \
    "$daemon_ctl_dir/post-hatch-mount-boundaries.json" \
    "$daemon_ctl_dir/db-preflight-failed-before-daemon-start-at-ms"
rm -rf "$daemon_ctl_dir/env"
rm -rf "$handoff_dir/runtime-cell-bootstrap-events"
# The sanitized lifecycle projection is gone, so revoke rv-graft's temporary
# mapped-cell group traversal grant even when this directory is a persistent bind path.
# A missing/non-directory path has no grant to revoke and must not abort the
# machine shutdown escalation below.
if [ -d "$handoff_dir" ] && [ ! -L "$handoff_dir" ]; then
    chown root:root "$handoff_dir"
    chmod 0750 "$handoff_dir"
fi

emit_mount_stop_lifecycle_event runtime_cell_stop started "$(date +%s%3N)"

if ! machine_exists; then
    fast_cleanup_machine "machine_missing_or_unregistered"
    emit_mount_stop_lifecycle_event runtime_cell_stop completed "$(date +%s%3N)" machine_missing_or_unregistered
    exit 0
fi

if ! machine_leader_is_live; then
    fast_cleanup_machine "machine_leader_missing_or_dead"
    emit_mount_stop_lifecycle_event runtime_cell_stop completed "$(date +%s%3N)" machine_leader_missing_or_dead
    exit 0
fi

log_stop "requesting graceful poweroff: machine=$machine timeout_ms=$((graceful_poweroff_attempts * 100))"
machinectl poweroff "$machine" 2>/dev/null || true
if wait_for_machine_gone "$graceful_poweroff_attempts"; then
    emit_mount_stop_lifecycle_event runtime_cell_stop completed "$(date +%s%3N)" clean
    exit 0
fi

log_stop "graceful poweroff timed out; escalating to terminate: machine=$machine"
if attempt_machine_terminate; then
    emit_mount_stop_lifecycle_event runtime_cell_stop completed "$(date +%s%3N)" terminated
    exit 0
fi

log_stop "terminate timed out; escalating to kill: machine=$machine"
if attempt_machine_kill; then
    emit_mount_stop_lifecycle_event runtime_cell_stop completed "$(date +%s%3N)" killed
    exit 0
fi

log_stop "machine still registered after kill; clearing stale state before retry: machine=$machine"
clear_stale_machine_state
emit_mount_stop_lifecycle_event runtime_cell_stop completed "$(date +%s%3N)" stale_cleanup
exit 0
