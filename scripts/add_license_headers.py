#!/usr/bin/env python3
# Copyright 2026 Autouse AI — https://github.com/auto-use/Auto-Use
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
# If you build on this project, please keep this header and credit
# Autouse AI (https://github.com/auto-use/Auto-Use) in forks and derivative works.
# A small attribution goes a long way toward a healthy open-source
# community — thank you for contributing.
"""Add the Apache 2.0 header to every .py file that is missing it."""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

_COPYRIGHT_OWNER = "Autouse AI"
_COPYRIGHT_URL = "https://github.com/auto-use/Auto-Use"
_COPYRIGHT_YEAR = "2026"

HEADER_LINES = [
    f"# Copyright {_COPYRIGHT_YEAR} {_COPYRIGHT_OWNER} — {_COPYRIGHT_URL}",
    "#",
    '# Licensed under the Apache License, Version 2.0 (the "License");',
    "# you may not use this file except in compliance with the License.",
    "# You may obtain a copy of the License at",
    "#",
    "#     http://www.apache.org/licenses/LICENSE-2.0",
    "#",
    "# Unless required by applicable law or agreed to in writing, software",
    '# distributed under the License is distributed on an "AS IS" BASIS,',
    "# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.",
    "# See the License for the specific language governing permissions and",
    "# limitations under the License.",
    "#",
    f"# If you build on this project, please keep this header and credit",
    f"# {_COPYRIGHT_OWNER} ({_COPYRIGHT_URL}) in forks and derivative works.",
    "# A small attribution goes a long way toward a healthy open-source",
    "# community — thank you for contributing.",
]

HEADER_TEXT = "\n".join(HEADER_LINES)
DUPLICATE_MARKER = f"Copyright {_COPYRIGHT_YEAR} {_COPYRIGHT_OWNER}"

# Directories to skip entirely.
EXCLUDE_DIR_NAMES = {
    ".git",
    ".venv",
    "venv",
    "env",
    "build",
    "dist",
    "__pycache__",
    "node_modules",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
}

# Files to skip (checker and this fixer already have the header).
EXCLUDE_RELATIVE = {
    "scripts/check_license_headers.py",
    "scripts/add_license_headers.py",
}


def iter_python_files(root: Path):
    for path in root.rglob("*.py"):
        if any(part in EXCLUDE_DIR_NAMES for part in path.parts):
            continue
        rel = path.relative_to(root).as_posix()
        if rel in EXCLUDE_RELATIVE:
            continue
        yield path


def already_has_correct_header(text: str) -> bool:
    lines = text.splitlines()
    start = 1 if lines and lines[0].startswith("#!") else 0
    return lines[start : start + len(HEADER_LINES)] == HEADER_LINES


def add_header(path: Path) -> bool:
    """Return True if the file was modified, False if it already had the header."""
    text = path.read_text(encoding="utf-8")

    if already_has_correct_header(text):
        return False

    if DUPLICATE_MARKER in text:
        # File has some form of the header already but it doesn't match
        # (maybe wrong position or surrounded by other content). Skip and
        # let the CI checker flag it so a human decides.
        print(f"  SKIP (needs manual fix): {path.relative_to(REPO_ROOT)}")
        return False

    lines = text.splitlines(keepends=False)
    ends_with_newline = text.endswith("\n")

    if lines and lines[0].startswith("#!"):
        shebang = lines[0]
        rest = lines[1:]
        new_lines = [shebang, *HEADER_LINES]
        if rest:
            new_lines.append("")
            new_lines.extend(rest)
    else:
        new_lines = list(HEADER_LINES)
        if lines:
            new_lines.append("")
            new_lines.extend(lines)

    new_text = "\n".join(new_lines)
    if ends_with_newline or not text:
        new_text += "\n"

    path.write_text(new_text, encoding="utf-8")
    return True


def main() -> int:
    modified = 0
    already_ok = 0
    skipped = 0

    for path in iter_python_files(REPO_ROOT):
        try:
            result = add_header(path)
        except UnicodeDecodeError:
            print(f"  SKIP (not UTF-8): {path.relative_to(REPO_ROOT)}")
            skipped += 1
            continue

        if result:
            modified += 1
        else:
            already_ok += 1

    print()
    print(f"Modified:     {modified}")
    print(f"Already OK:   {already_ok}")
    print(f"Skipped:      {skipped}")
    print()
    print("Done. Review the diff with `git diff` before committing.")
    return 0


if __name__ == "__main__":
    sys.exit(main())