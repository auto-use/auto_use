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

"""
Manual test harness for element.py.

Runs a 5-second countdown, then drives the same three-call sequence the agent
uses in production (scan_elements -> save_to_file -> get_scan_data) with
DEBUG force-enabled, so the element tree and annotated screenshot are written
to debug/element/ and debug/screenshot/ under the current working directory.

Run from the repo root:
    python -m Auto_Use.windows_use.tree.test
"""

import time

from . import element
from .element import UIElementScanner, ELEMENT_CONFIG


def main():
    # Force-enable DEBUG so UIElementScanner writes to debug/element/ and
    # debug/screenshot/. We patch the module attribute rather than editing
    # element.py so production code stays untouched.
    element.DEBUG = True

    for i in range(5, 0, -1):
        print(f"Scanning in {i}...")
        time.sleep(1)

    print("Starting scan now!\n")
    scanner = UIElementScanner(ELEMENT_CONFIG)

    # scan_elements() only populates internal state. The debug artifacts are
    # produced by save_to_file() (tree .txt) and get_scan_data() (annotated
    # screenshot .jpg) -- matching the sequence AgentService uses in prod.
    scanner.scan_elements()
    scanner.save_to_file()
    scanner.get_scan_data()

    print("\nScan complete. Check debug/element/ and debug/screenshot/ for output.")


if __name__ == "__main__":
    main()
