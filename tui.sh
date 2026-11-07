#!/usr/bin/env sh
# Launch hubctl from this repository. Arguments pass through to the app.
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)

if ! command -v python3 >/dev/null 2>&1; then
    echo "tui.sh: python3 not found" >&2
    exit 127
fi

if [ ! -t 0 ] || [ ! -t 1 ]; then
    echo "tui.sh: needs an interactive terminal" >&2
    exit 2
fi

exec env PYTHONPATH="$ROOT/src" python3 -m hubctl "$@"
