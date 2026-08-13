#!/bin/sh
set -eu

manager=/usr/bin/aiguard-native-host-manager
receipt=/usr/bin/.aiguard-component-transaction-v1

if [ -e "$receipt" ]; then
  [ -f "$receipt" ]
  [ ! -L "$receipt" ]
  [ "$(stat -c %u "$receipt")" = 0 ]
  [ "$(stat -c %a "$receipt")" = 600 ]
  [ "$(stat -c %h "$receipt")" = 1 ]
  [ "$(wc -c < "$receipt")" -eq 65 ]
  transaction=$(cat "$receipt")
  [ "${#transaction}" -eq 64 ]
  case "$transaction" in *[!0-9a-f]*) exit 1 ;; esac
  printf '%s\n' "$transaction" | cmp -s - "$receipt"
  "$manager" complete deb "$transaction"
else
  "$manager" complete-legacy deb
fi
