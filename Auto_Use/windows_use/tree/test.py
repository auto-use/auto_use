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
