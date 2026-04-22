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
OCR Detection - Windows Native OCR Scanner
Captures full screen, runs Windows built-in OCR, returns raw word list.
Designed to run as a parallel thread alongside UIA/Win32 scans.
Filtering/merging happens in the caller (element.py).
"""

import asyncio
from PIL import ImageGrab

from winrt.windows.media.ocr import OcrEngine
from winrt.windows.globalization import Language
from winrt.windows.graphics.imaging import SoftwareBitmap, BitmapPixelFormat, BitmapAlphaMode


async def _pil_to_software_bitmap(pil_image):
    """Convert PIL Image to WinRT SoftwareBitmap for OCR input"""
    if pil_image.mode != "RGBA":
        pil_image = pil_image.convert("RGBA")

    width, height = pil_image.size
    pixels = pil_image.tobytes()

    bgra = bytearray(len(pixels))
    for i in range(0, len(pixels), 4):
        bgra[i] = pixels[i + 2]
        bgra[i + 1] = pixels[i + 1]
        bgra[i + 2] = pixels[i]
        bgra[i + 3] = pixels[i + 3]

    bitmap = SoftwareBitmap(BitmapPixelFormat.BGRA8, width, height, BitmapAlphaMode.PREMULTIPLIED)
    bitmap.copy_from_buffer(bytes(bgra))
    return bitmap


async def _run_ocr(pil_image):
    """Run Windows OCR on a PIL image, return list of line dicts"""
    engine = OcrEngine.try_create_from_user_profile_languages()
    if engine is None:
        engine = OcrEngine.try_create_from_language(Language("en-US"))
    if engine is None:
        return []

    bitmap = await _pil_to_software_bitmap(pil_image)
    result = await engine.recognize_async(bitmap)

    lines = []
    for line in result.lines:
        if not line.words:
            continue
        # Compute line bounding box from constituent words
        min_left = min(int(w.bounding_rect.x) for w in line.words)
        min_top = min(int(w.bounding_rect.y) for w in line.words)
        max_right = max(int(w.bounding_rect.x + w.bounding_rect.width) for w in line.words)
        max_bottom = max(int(w.bounding_rect.y + w.bounding_rect.height) for w in line.words)
        lines.append({
            "text": line.text,
            "left": min_left,
            "top": min_top,
            "right": max_right,
            "bottom": max_bottom,
        })
    return lines


class OCRScanner:
    """
    Lightweight OCR scanner. Captures full screen, runs Windows OCR,
    stores raw line list. Thread-safe for parallel execution.
    """

    def __init__(self):
        self.lines = []

    def scan(self):
        """Capture full screen and run OCR. Stores results in self.lines."""
        try:
            screenshot = ImageGrab.grab()
        except OSError:
            self.lines = []
            return

        self.lines = asyncio.run(_run_ocr(screenshot))

    def get_lines(self):
        """Return raw line list: [{text, left, top, right, bottom}, ...]"""
        return self.lines