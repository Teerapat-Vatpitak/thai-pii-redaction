#!/bin/sh
set -eu

marker=/usr/bin/.aiguard-component-maintenance-v1
receipt=/usr/bin/.aiguard-component-transaction-v1

case "${1:-}" in
  remove|purge) ;;
  *) exit 0 ;;
esac

if [ ! -e "$marker" ] && [ ! -e "$receipt" ]; then
  exit 0
fi
if [ -e "$marker" ]; then
  [ -f "$marker" ]
  [ ! -L "$marker" ]
  [ "$(stat -c %u "$marker")" = 0 ]
  [ "$(stat -c %a "$marker")" = 600 ]
  [ "$(stat -c %h "$marker")" = 1 ]
  [ "$(wc -c < "$marker")" -eq 33 ]
  printf 'AIGUARD_COMPONENT_MAINTENANCE_V1\n' | cmp -s - "$marker"
fi
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
fi
if [ -e "$marker" ]; then
  rm -f -- "$marker"
fi
if [ -e "$receipt" ]; then
  rm -f -- "$receipt"
fi
