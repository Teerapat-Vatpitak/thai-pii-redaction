#!/bin/sh
set -eu

manager=/usr/bin/aiguard-native-host-manager
broker=/usr/bin/aiguard-native-broker
backend=/usr/bin/aiguard
adapter=/usr/bin/aiguard-chrome-native-host
desktop=/usr/bin/desktop
marker=/usr/bin/.aiguard-component-maintenance-v1
receipt=/usr/bin/.aiguard-component-transaction-v1

exec 9< /usr/bin
flock -n 9

component_identity() {
  path=$1
  [ -f "$path" ]
  [ ! -L "$path" ]
  [ "$(stat -c %u "$path")" = 0 ]
  [ "$(stat -c %a "$path")" = 755 ]
  [ "$(stat -c %h "$path")" = 1 ]
  stat -Lc '%d:%i' "$path"
}

validate_marker() {
  [ -f "$marker" ]
  [ ! -L "$marker" ]
  [ "$(stat -c %u "$marker")" = 0 ]
  [ "$(stat -c %a "$marker")" = 600 ]
  [ "$(stat -c %h "$marker")" = 1 ]
  [ "$(wc -c < "$marker")" -eq 33 ]
  printf 'AIGUARD_COMPONENT_MAINTENANCE_V1\n' | cmp -s - "$marker"
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

identity_is_running() {
  expected=$1
  for executable in /proc/[0-9]*/exe; do
    observed=$(stat -Lc '%d:%i' "$executable" 2>/dev/null || true)
    if [ "$observed" = "$expected" ]; then
      return 0
    fi
  done
  return 1
}

# dpkg can repeat prerm after interruption. Missing launchers together with an
# exact receipt and marker mean the verified first pass reached unlinking only
# after unregister, runtime cleanup, and the bounded live-process proof.
if [ -e "$receipt" ]; then
  validate_receipt
  if [ -e "$marker" ]; then
    validate_marker
    partial=0
    for path in "$desktop" "$adapter" "$broker" "$backend" "$manager"; do
      if [ ! -e "$path" ] && [ ! -L "$path" ]; then
        partial=1
      fi
    done
    if [ "$partial" -eq 1 ]; then
      for registration in \
        /etc/opt/chrome/native-messaging-hosts/th.ac.psu.aiguard.native_host.json \
        /etc/opt/chrome_for_testing/native-messaging-hosts/th.ac.psu.aiguard.native_host.json \
        /etc/chromium/native-messaging-hosts/th.ac.psu.aiguard.native_host.json
      do
        [ ! -e "$registration" ] && [ ! -L "$registration" ]
      done
      for path in "$desktop" "$adapter" "$broker" "$backend" "$manager"; do
        { [ ! -e "$path" ] && [ ! -L "$path" ]; } || component_identity "$path" >/dev/null
      done
      attempt=0
      clear_attempts=0
      while [ "$clear_attempts" -lt 10 ]; do
        live=0
        for path in "$desktop" "$adapter" "$broker" "$backend" "$manager"; do
          { [ ! -e "$path" ] && [ ! -L "$path" ]; } || {
            identity=$(component_identity "$path")
            identity_is_running "$identity" && live=1
          }
        done
        if [ "$live" -eq 1 ]; then
          clear_attempts=0
        elif [ -e "$manager" ] || [ -L "$manager" ]; then
          if "$manager" cleanup deb >/dev/null 2>&1; then
            clear_attempts=$((clear_attempts + 1))
          else
            clear_attempts=0
          fi
        else
          # The manager is the final rm operand. If it is already absent, the
          # first pass must also have unlinked every earlier launcher after its
          # cleanup proof; any remaining file is an impossible retry state.
          for path in "$desktop" "$adapter" "$broker" "$backend"; do
            [ ! -e "$path" ] && [ ! -L "$path" ]
          done
          clear_attempts=$((clear_attempts + 1))
        fi
        attempt=$((attempt + 1))
        [ "$attempt" -le 300 ] || exit 1
        sleep 0.1
      done
      rm -f -- "$desktop" "$adapter" "$broker" "$backend" "$manager"
      exit 0
    fi
  fi
fi

broker_identity=$(component_identity "$broker")
backend_identity=$(component_identity "$backend")
adapter_identity=$(component_identity "$adapter")
desktop_identity=$(component_identity "$desktop")
manager_transaction=$("$manager" remove deb)
validate_receipt
[ "$manager_transaction" = "$transaction" ]

attempt=0
clear_attempts=0
while [ "$clear_attempts" -lt 10 ]; do
  if identity_is_running "$broker_identity" || identity_is_running "$backend_identity" || identity_is_running "$adapter_identity" || { [ "${1:-}" = remove ] && identity_is_running "$desktop_identity"; }; then
    clear_attempts=0
  elif ! "$manager" cleanup deb >/dev/null 2>&1; then
    clear_attempts=0
  else
    clear_attempts=$((clear_attempts + 1))
  fi
  attempt=$((attempt + 1))
  [ "$attempt" -le 300 ] || exit 1
  sleep 0.1
done

# Unlink only after the bounded live-process and all-UID cleanup proof. A
# failed proof leaves the verified installed set present for a safe retry.
rm -f -- "$desktop" "$adapter" "$broker" "$backend" "$manager"
