#!/bin/sh
set -eu

manager=/usr/bin/aiguard-native-host-manager
broker=/usr/bin/aiguard-native-broker
backend=/usr/bin/aiguard
adapter=/usr/bin/aiguard-chrome-native-host
desktop=/usr/bin/desktop
marker=/usr/bin/.aiguard-component-maintenance-v1
receipt=/usr/bin/.aiguard-component-transaction-v1

# Serialize ordinary manager actions with the pre-unpack proof. After this
# script exits, the active marker keeps those actions closed through unpack.
exec 9< /usr/bin
flock -n 9

validate_marker() {
  [ -f "$marker" ]
  [ ! -L "$marker" ]
  [ "$(stat -c %u "$marker")" = 0 ]
  [ "$(stat -c %a "$marker")" = 600 ]
  [ "$(stat -c %h "$marker")" = 1 ]
  [ "$(wc -c < "$marker")" -eq 33 ]
  printf 'AIGUARD_COMPONENT_MAINTENANCE_V1\n' | cmp -s - "$marker"
}

begin_replacement() {
  if [ -e "$marker" ]; then
    validate_marker
    return
  fi
  old_umask=$(umask)
  umask 077
  if ! (set -C; printf 'AIGUARD_COMPONENT_MAINTENANCE_V1\n' > "$marker") 2>/dev/null; then
    umask "$old_umask"
    validate_marker
    return
  fi
  umask "$old_umask"
  validate_marker
}

component_identity() {
  path=$1
  if [ ! -e "$path" ]; then
    printf '\n'
    return
  fi
  [ -f "$path" ]
  [ ! -L "$path" ]
  [ "$(stat -c %u "$path")" = 0 ]
  [ "$(stat -c %a "$path")" = 755 ]
  [ "$(stat -c %h "$path")" = 1 ]
  stat -Lc '%d:%i' "$path"
}

identity_is_running() {
  expected=$1
  [ -n "$expected" ] || return 1
  for executable in /proc/[0-9]*/exe; do
    observed=$(stat -Lc '%d:%i' "$executable" 2>/dev/null || true)
    if [ "$observed" = "$expected" ]; then
      return 0
    fi
  done
  return 1
}

wait_for_component_exit() {
  broker_identity=$1
  backend_identity=$2
  adapter_identity=$3
  desktop_identity=$4
  cleanup=$5
  attempt=0
  clear_attempts=0
  while [ "$clear_attempts" -lt 10 ]; do
    if identity_is_running "$broker_identity" || identity_is_running "$backend_identity" || identity_is_running "$adapter_identity" || identity_is_running "$desktop_identity"; then
      clear_attempts=0
    elif [ "$cleanup" -eq 1 ] && ! "$manager" cleanup deb >/dev/null 2>&1; then
      clear_attempts=0
    else
      clear_attempts=$((clear_attempts + 1))
    fi
    attempt=$((attempt + 1))
    [ "$attempt" -le 300 ] || return 1
    sleep 0.1
  done
}

validate_receipt() {
  [ -f "$receipt" ]
  [ ! -L "$receipt" ]
  [ "$(stat -c %u "$receipt")" = 0 ]
  [ "$(stat -c %a "$receipt")" = 600 ]
  [ "$(stat -c %h "$receipt")" = 1 ]
  [ "$(wc -c < "$receipt")" -eq 65 ]
  transaction=$(cat "$receipt")
  [ "${#transaction}" -eq 64 ]
  case "$transaction" in *[!0-9a-f]*) return 1 ;; esac
  printf '%s\n' "$transaction" | cmp -s - "$receipt"
}

quarantine_legacy_launchers() {
  for path in "$desktop" "$adapter" "$broker" "$backend" "$manager"; do
    [ -e "$path" ] || continue
    quarantine="$path.aiguard-slice6-quarantine"
    [ ! -e "$quarantine" ]
    mv -- "$path" "$quarantine"
  done
}

restore_legacy_launchers() {
  for path in "$desktop" "$adapter" "$broker" "$backend" "$manager"; do
    quarantine="$path.aiguard-slice6-quarantine"
    [ -e "$quarantine" ] || continue
    [ ! -e "$path" ] || return 1
    mv -- "$quarantine" "$path"
  done
}

remove_legacy_quarantine() {
  rm -f -- \
    "$desktop.aiguard-slice6-quarantine" \
    "$adapter.aiguard-slice6-quarantine" \
    "$broker.aiguard-slice6-quarantine" \
    "$backend.aiguard-slice6-quarantine" \
    "$manager.aiguard-slice6-quarantine"
}

isolate_legacy_registration() {
  expected='{
  "allowed_origins": [
    "chrome-extension://kdjmkknedgmfphpkjhjdhmjadaelgggm/"
  ],
  "description": "AI Guard Chrome Native Messaging adapter",
  "name": "th.ac.psu.aiguard.native_host",
  "path": "/usr/bin/aiguard-chrome-native-host",
  "type": "stdio"
}'
  expected_size=$(printf '%s\n' "$expected" | wc -c)
  for registration in \
    /etc/opt/chrome/native-messaging-hosts/th.ac.psu.aiguard.native_host.json \
    /etc/opt/chrome_for_testing/native-messaging-hosts/th.ac.psu.aiguard.native_host.json \
    /etc/chromium/native-messaging-hosts/th.ac.psu.aiguard.native_host.json
  do
    [ -e "$registration" ] || continue
    [ -f "$registration" ]
    [ ! -L "$registration" ]
    [ "$(stat -c %u "$registration")" = 0 ]
    [ "$(stat -c %a "$registration")" = 644 ]
    [ "$(stat -c %h "$registration")" = 1 ]
    [ "$(wc -c < "$registration")" -eq "$expected_size" ]
    printf '%s\n' "$expected" | cmp -s - "$registration"
    quarantine="$registration.aiguard-slice6-quarantine"
    [ ! -e "$quarantine" ]
    mv -- "$registration" "$quarantine"
  done
}

restore_legacy_registration() {
  for registration in \
    /etc/opt/chrome/native-messaging-hosts/th.ac.psu.aiguard.native_host.json \
    /etc/opt/chrome_for_testing/native-messaging-hosts/th.ac.psu.aiguard.native_host.json \
    /etc/chromium/native-messaging-hosts/th.ac.psu.aiguard.native_host.json
  do
    quarantine="$registration.aiguard-slice6-quarantine"
    [ -e "$quarantine" ] || continue
    [ ! -e "$registration" ] || return 1
    mv -- "$quarantine" "$registration"
  done
}

remove_legacy_registration_quarantine() {
  rm -f -- \
    /etc/opt/chrome/native-messaging-hosts/th.ac.psu.aiguard.native_host.json.aiguard-slice6-quarantine \
    /etc/opt/chrome_for_testing/native-messaging-hosts/th.ac.psu.aiguard.native_host.json.aiguard-slice6-quarantine \
    /etc/chromium/native-messaging-hosts/th.ac.psu.aiguard.native_host.json.aiguard-slice6-quarantine
}

restore_legacy_state() {
  restore_legacy_launchers
  restore_legacy_registration
}

if [ ! -x "$manager" ]; then
  begin_replacement
  trap 'restore_legacy_state' EXIT HUP INT TERM
  isolate_legacy_registration
  broker_identity=$(component_identity "$broker")
  backend_identity=$(component_identity "$backend")
  adapter_identity=$(component_identity "$adapter")
  desktop_identity=$(component_identity "$desktop")
  quarantine_legacy_launchers
  wait_for_component_exit "$broker_identity" "$backend_identity" "$adapter_identity" "$desktop_identity" 0
  remove_legacy_quarantine
  remove_legacy_registration_quarantine
  trap - EXIT HUP INT TERM
  exit 0
fi

# Current managers create the barrier and request a graceful drain. The first
# upgrade from the pre-Slice-6 package lacks that action, so establish the same
# fixed barrier here and remove its registration before the stable exit proof.
if "$manager" capability deb >/dev/null 2>&1; then
  current_manager=1
  manager_transaction=$("$manager" drain deb)
  validate_receipt
  [ "$manager_transaction" = "$transaction" ]
else
  current_manager=0
  begin_replacement
  trap 'restore_legacy_state' EXIT HUP INT TERM
  isolate_legacy_registration
fi
validate_marker

broker_identity=$(component_identity "$broker")
backend_identity=$(component_identity "$backend")
adapter_identity=$(component_identity "$adapter")
desktop_identity=$(component_identity "$desktop")

if [ "$current_manager" -eq 1 ]; then
  wait_for_component_exit "$broker_identity" "$backend_identity" "$adapter_identity" "" 1
else
  quarantine_legacy_launchers
  wait_for_component_exit "$broker_identity" "$backend_identity" "$adapter_identity" "$desktop_identity" 0
  remove_legacy_quarantine
  remove_legacy_registration_quarantine
  trap - EXIT HUP INT TERM
  exit 0
fi

# Keep the verified manager addressable until every live broker is gone and
# all proven-inactive per-user runtime roots have been cleaned.
rm -f -- "$desktop" "$adapter" "$broker" "$backend" "$manager"
