#!/bin/bash
#
# Auto Use — macOS one-click setup
# ================================
# Verifies Python 3.10+ is installed, creates a local venv/, and installs
# mac_requirements.txt into it.
#
# How to run (any of these):
#   bash MacOS_setup.sh          # simplest, works right after clone
#   chmod +x MacOS_setup.sh && ./MacOS_setup.sh
#   Finder → right-click MacOS_setup.sh → Open With → Terminal.app
#
# After it finishes:
#   source venv/bin/activate
#   python app.py                # launch the GUI app (macOS + Windows)
#   python mac_binary_build.py   # produce AutoUse.dmg
#

set -e

cd "$(dirname "$0")"

# -----------------------------------------------------------------------------
# Print helpers (match the style used in mac_binary_build.py)
# -----------------------------------------------------------------------------
print_step()   { printf "\n============================================================\n  %s\n============================================================\n\n" "$1"; }
print_ok()     { printf "  [OK] %s\n" "$1"; }
print_info()   { printf "  [INFO] %s\n" "$1"; }
print_error()  { printf "  [ERROR] %s\n" "$1"; }

# -----------------------------------------------------------------------------
# Step 1 — Python 3 present?
# -----------------------------------------------------------------------------
# NOTE: Previous versions of this script had an extra "sync shared files to
# macOS flavor" step here that sed-rewrote imports and HTML refs from the
# Windows variant to the macOS variant. That's gone now — main.py, cli.py,
# frontend/index.html and frontend/script.js detect the OS at runtime, so a
# single checkout runs on both macOS and Windows with zero file patching.
print_step "STEP 1: Checking for Python 3"

if ! command -v python3 >/dev/null 2>&1; then
    print_error "Python 3 is not installed on this Mac."
    print_info  "Opening Safari to python.org/downloads/macos — install Python, then re-run this script."

    # GUI popup so it's visible even if launched from Finder
    osascript -e 'display dialog "Python 3 is not installed.\n\nOpening Safari to python.org/downloads/macos.\n\nInstall Python, then run this script again." buttons {"OK"} default button 1 with icon caution with title "Auto Use setup"' >/dev/null 2>&1 || true

    open -a Safari "https://www.python.org/downloads/macos/"
    exit 1
fi

PY_BIN="$(command -v python3)"
PY_VERSION="$(python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])')"
print_ok "Found python3 at $PY_BIN (Python $PY_VERSION)"

# -----------------------------------------------------------------------------
# Step 1b — version gate (>= 3.10)
# -----------------------------------------------------------------------------
MIN_MAJOR=3
MIN_MINOR=10

if ! python3 -c "import sys; sys.exit(0 if sys.version_info >= ($MIN_MAJOR, $MIN_MINOR) else 1)"; then
    print_error "Python $PY_VERSION is too old. This project needs Python >= ${MIN_MAJOR}.${MIN_MINOR}."
    print_info  "Install a newer Python from https://www.python.org/downloads/macos/ and re-run."
    open -a Safari "https://www.python.org/downloads/macos/"
    exit 1
fi

# -----------------------------------------------------------------------------
# Step 2 — venv/
# -----------------------------------------------------------------------------
print_step "STEP 2: Preparing venv/"

if [ -d "venv" ]; then
    print_info "venv/ already exists — reusing"
else
    python3 -m venv venv
    print_ok "Created venv/"
fi

# -----------------------------------------------------------------------------
# Step 3 — activate + install
# -----------------------------------------------------------------------------
print_step "STEP 3: Installing mac_requirements.txt"

# shellcheck disable=SC1091
source venv/bin/activate

python -m pip install --upgrade pip >/dev/null
print_ok "pip upgraded inside venv"

if [ ! -f "mac_requirements.txt" ]; then
    print_error "mac_requirements.txt not found in $(pwd)"
    exit 1
fi

pip install -r mac_requirements.txt

# -----------------------------------------------------------------------------
# Done
# -----------------------------------------------------------------------------
print_step "SETUP COMPLETE"
print_ok "Dependencies installed into venv/"
printf "\n"
print_info "Next steps:"
printf "    source venv/bin/activate\n"
[ -f "main.py" ]             && printf "    python main.py               # run the CLI agent\n"
[ -f "app.py" ]              && printf "    python app.py                # launch the GUI app\n"
[ -f "mac_binary_build.py" ] && printf "    python mac_binary_build.py   # produce AutoUse.dmg\n"
printf "\n"
