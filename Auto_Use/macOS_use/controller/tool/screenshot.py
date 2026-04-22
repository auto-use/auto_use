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

# Auto_Use/macOS_use/controller/tool/screenshot.py
# macOS — capture main display via Quartz, crop element region, save to Desktop

import logging
import os
from datetime import datetime
from pathlib import Path

import Quartz
from PIL import Image
from io import BytesIO

logger = logging.getLogger(__name__)


class ScreenshotService:
    """Capture and crop element screenshots on macOS."""

    def __init__(self, controller_service, sandbox_workspace: str = None):
        self.controller_service = controller_service
        self.sandbox_workspace = sandbox_workspace

    def capture_element(self, rect, index="element") -> dict:
        """
        Capture the main display, crop to element rect, save to Desktop.

        Args:
            rect: Element rect with .left, .top, .right, .bottom
            index: Element index for filename

        Returns:
            dict with status and saved file path
        """
        try:
            # Capture entire main display
            cg_image = Quartz.CGWindowListCreateImage(
                Quartz.CGRectInfinite,
                Quartz.kCGWindowListOptionOnScreenOnly,
                Quartz.kCGNullWindowID,
                Quartz.kCGWindowImageDefault,
            )
            if cg_image is None:
                return {
                    "status": "error",
                    "action": "screenshot",
                    "message": "Failed to capture main display"
                }

            # Convert CGImage → PIL Image
            width = Quartz.CGImageGetWidth(cg_image)
            height = Quartz.CGImageGetHeight(cg_image)
            bytes_per_row = Quartz.CGImageGetBytesPerRow(cg_image)
            data_provider = Quartz.CGImageGetDataProvider(cg_image)
            raw_data = Quartz.CGDataProviderCopyData(data_provider)

            img = Image.frombytes("RGBA", (width, height), raw_data, "raw", "BGRA", bytes_per_row, 1)

            # Get Retina scale factor (2x on HiDPI, 1x on standard)
            from Cocoa import NSScreen
            scale = int(NSScreen.mainScreen().backingScaleFactor())

            # Rect is in logical points — scale to physical pixels
            crop_box = (
                int(rect.left * scale),
                int(rect.top * scale),
                int(rect.right * scale),
                int(rect.bottom * scale),
            )
            cropped = img.crop(crop_box)

            # Save to sandbox workspace (or Desktop as fallback)
            timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
            filename = f"screenshot_{index}_{timestamp}.png"
            if self.sandbox_workspace and os.path.isdir(self.sandbox_workspace):
                save_dir = Path(self.sandbox_workspace)
            else:
                save_dir = Path.home() / "Desktop"
            save_path = save_dir / filename

            cropped.save(str(save_path), "PNG")
            logger.info(f"Screenshot saved: {save_path}")

            return {
                "status": "success",
                "action": "screenshot",
                "message": f"Image saved at: {save_path}",
                "path": str(save_path),
            }

        except Exception as e:
            logger.error(f"Screenshot capture failed: {e}")
            return {
                "status": "error",
                "action": "screenshot",
                "message": f"Screenshot failed: {str(e)}"
            }