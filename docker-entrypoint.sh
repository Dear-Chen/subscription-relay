#!/bin/sh
# Fix data dir ownership, then run the app unprivileged.
#
# Bind mounts (e.g. ./data on Docker Desktop) appear as root-owned inside the
# container, which blocks the unprivileged app user from writing. We start as
# root only to chown, then drop privileges via gosu.
set -e

DATA_DIR="${SUBRELAY_DATA_DIR:-/app/data}"

mkdir -p "$DATA_DIR" "$DATA_DIR/cache"
chown -R subrelay:subrelay "$DATA_DIR"

exec gosu subrelay "$@"
