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
#   python mac_app.py            # launch the app
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
# Step 1 — Sync shared files to macOS flavor
# -----------------------------------------------------------------------------
# The frontend and root Python scripts are shared with the Windows fork. If the
# working copy has Windows-flavored refs (windows_animation, windows_use,
# windows_app), rewrite them to the macOS equivalents before anything runs.
# Idempotent — a no-op when the tree is already macOS-flavored.
print_step "STEP 1: Syncing shared files to macOS"

# Frontend: windows_animation.html -> mac_animation.html
# Skip entirely if frontend/ isn't present (minimal installs without the UI).
if [ -d "frontend" ]; then
    frontend_hits=$(grep -rl "windows_animation" frontend 2>/dev/null | wc -l | tr -d ' ' || echo 0)
    if [ "$frontend_hits" != "0" ]; then
        grep -rl "windows_animation" frontend 2>/dev/null \
            | xargs sed -i '' 's|windows_animation|mac_animation|g'
        print_ok "Patched $frontend_hits frontend file(s): windows_animation -> mac_animation"
    else
        print_info "Frontend already references mac_animation"
    fi
else
    print_info "No frontend/ folder — skipping frontend sync"
fi

# Root Python: windows_use -> macOS_use and windows_app -> mac_app
# Scope: .py files outside venv/, dist/, __pycache__/, the Windows fork
# folders (windows_use/, windows_app/), AND the Windows-specific top-level
# scripts (windows_app.py, windows_binary_build.py, or anything matching
# windows_*.py). --exclude-dir only filters directories, so those files
# would otherwise be rewritten — which mangles the Windows fork in a
# combined mac+windows checkout. We only want to rewrite stray refs in
# genuinely shared files like main.py.
#
# Portability note: BSD grep on macOS supports --exclude=GLOB for filename
# filtering, so we use it here alongside --exclude-dir.
py_win_use=$(grep -rl --include='*.py' --exclude='windows_*.py' \
    --exclude-dir=venv --exclude-dir=dist --exclude-dir=__pycache__ \
    --exclude-dir=windows_use --exclude-dir=windows_app \
    'windows_use' . 2>/dev/null | wc -l | tr -d ' ' || echo 0)
if [ "$py_win_use" != "0" ]; then
    grep -rl --include='*.py' --exclude='windows_*.py' \
        --exclude-dir=venv --exclude-dir=dist --exclude-dir=__pycache__ \
        --exclude-dir=windows_use --exclude-dir=windows_app \
        'windows_use' . 2>/dev/null \
        | xargs sed -i '' 's|windows_use|macOS_use|g'
    print_ok "Patched $py_win_use Python file(s): windows_use -> macOS_use"
else
    print_info "Python imports already reference macOS_use"
fi

py_win_app=$(grep -rl --include='*.py' --exclude='windows_*.py' \
    --exclude-dir=venv --exclude-dir=dist --exclude-dir=__pycache__ \
    --exclude-dir=windows_use --exclude-dir=windows_app \
    'windows_app' . 2>/dev/null | wc -l | tr -d ' ' || echo 0)
if [ "$py_win_app" != "0" ]; then
    grep -rl --include='*.py' --exclude='windows_*.py' \
        --exclude-dir=venv --exclude-dir=dist --exclude-dir=__pycache__ \
        --exclude-dir=windows_use --exclude-dir=windows_app \
        'windows_app' . 2>/dev/null \
        | xargs sed -i '' 's|windows_app|mac_app|g'
    print_ok "Patched $py_win_app Python file(s): windows_app -> mac_app"
fi

# -----------------------------------------------------------------------------
# Step 2 — Python 3 present?
# -----------------------------------------------------------------------------
print_step "STEP 2: Checking for Python 3"

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
# Step 2 — version gate (>= 3.10)
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
# Step 3 — venv/
# -----------------------------------------------------------------------------
print_step "STEP 3: Preparing venv/"

if [ -d "venv" ]; then
    print_info "venv/ already exists — reusing"
else
    python3 -m venv venv
    print_ok "Created venv/"
fi

# -----------------------------------------------------------------------------
# Step 4 — activate + install
# -----------------------------------------------------------------------------
print_step "STEP 4: Installing mac_requirements.txt"

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
[ -f "mac_app.py" ]          && printf "    python mac_app.py            # launch the GUI app\n"
[ -f "mac_binary_build.py" ] && printf "    python mac_binary_build.py   # produce AutoUse.dmg\n"
printf "\n"
