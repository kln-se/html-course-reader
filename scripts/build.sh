#!/usr/bin/env bash
# Git Bash entry point; keep the build procedure in one place.
set -euo pipefail

case "$(uname -s)" in
    MINGW*|MSYS*) ;;
    *) printf '%s\n' 'Use Git Bash on Windows. Linux, macOS and WSL builds are not supported.' >&2; exit 1 ;;
esac

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
command -v powershell.exe >/dev/null 2>&1 || {
    printf '%s\n' 'Windows PowerShell (powershell.exe) was not found.' >&2
    exit 1
}
exec powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$(cygpath -w "$script_dir/build.ps1")"
