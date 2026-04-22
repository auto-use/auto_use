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
Standalone test runner for element.py scanner.
Run from project root:  python -m Auto_Use.macOS_use.tree.test
"""

import sys
import os
import time

# Ensure project root is on path when run directly
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..'))

import Auto_Use.macOS_use.tree.element as element
from Auto_Use.macOS_use.tree.element import UIElementScanner, ELEMENT_CONFIG, AXIsProcessTrusted

# Force debug flags on
element.DEBUG = True
element.SCREENSHOT = True


def main():
    print("=== Element Scanner Test ===")

    if not AXIsProcessTrusted():
        print("\nAccessibility permission required.")
        print("Grant in: System Settings > Privacy & Security > Accessibility")
        sys.exit(1)

    # Countdown — switch to the window you want to scan
    for i in range(5, 0, -1):
        print(f"  Scanning in {i}...")
        time.sleep(1)

    print("\nScanning now...\n")

    scanner = UIElementScanner(ELEMENT_CONFIG)
    scanner.scan_elements()

    tree_text, image_b64, _ = scanner.get_scan_data()
    mapping = scanner.get_elements_mapping()

    print(f"Application : {scanner.application_name}")
    print(f"Elements    : {len(mapping)}")
    print(f"Image       : {'yes' if image_b64 else 'no'}")
    print(f"\n{tree_text}")
    print(f"\nDebug saved to: debug/iteration_{scanner._debug_iteration}/")


if __name__ == "__main__":
    main()
