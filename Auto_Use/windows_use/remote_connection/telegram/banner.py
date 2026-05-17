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

"""Banner — both the StatusBanner wrapper used by callers AND the
subprocess that hosts the pywebview pill.

The same module is invoked two ways:

  1. **Imported** from setup.py / service.py — exposes the
     `StatusBanner` class that drives the wizard. Side-effect-free:
     pywebview and tkinter are NOT imported at module load, only
     inside `_run_subprocess_banner` which the parent never calls.

  2. **Run as `python -m …banner`** (spawned by `StatusBanner.show()`
     via `subprocess.Popen`) — falls through `if __name__ == "__main__"`
     into `_run_subprocess_banner`, which boots pywebview and parks on
     `webview.start()`. Reads JSON commands from stdin, emits JSON
     events on stdout.

Why two roles, one file? Running pywebview's second window from a
worker thread inside the already-running AutoUse process kept landing
the pill off-screen on DPI-scaled displays. A fresh Python interpreter
(the subprocess) was the only way to dodge that DPI confusion —
`banner_test.py` standalone works perfectly on the same machine. The
subprocess body used to live in a separate `banner_proc.py` but it
doesn't need to: a single module's `__main__` guard does the same job
with one fewer file to keep in sync.

Wire protocol (one JSON message per line):

  → stdin   {"cmd": "MSG"|"SHOW_NEXT"|"HIDE_NEXT"|"SHOW_CHOICE"|
                    "SHOW_INPUT"|"CLEAR"|"CLOSE", ...}
  ← stdout  {"event": "READY"|"NEXT"|"CHOICE"|"SAVE"|"CLOSED", ...}
"""
import ctypes
import json
import logging
import subprocess
import sys
import threading
import time
import uuid
from queue import Queue, Empty

logger = logging.getLogger(__name__)


# ── Pill geometry ─────────────────────────────────────────────────────────

PILL_WIDTH = 580
PILL_HEIGHT = 72
# COMPACT_SIZE is the target square dimension for the small "telegram
# task running" indicator pill. WinForms imposes an OS-level minimum
# width (~SM_CXMINTRACK = 132+ logical pixels) on freshly created Forms,
# which stretches a smaller create_window request into a wide pill — so
# we always force the final size via window.resize() after the form is
# alive (see _on_shown). 80 is the sweet spot: small enough to read as
# an indicator, big enough to hold the 42 px orb with breathing room.
COMPACT_SIZE = 80
SCREEN_MARGIN = 20


# ── Win32 region clip + click-through (subprocess-side, but ctypes is
#    stdlib so importing it at the top costs nothing for the parent) ──

class _RECT(ctypes.Structure):
    _fields_ = [
        ("left", ctypes.c_long),
        ("top", ctypes.c_long),
        ("right", ctypes.c_long),
        ("bottom", ctypes.c_long),
    ]


def _stderr(msg: str) -> None:
    """Loud print to whichever stderr we're attached to. Used both by
    the parent (for `[banner] spawned subprocess pid=…` etc.) and by
    the subprocess (which inherits the parent's stderr so the messages
    land in the same terminal)."""
    print(f"[banner] {msg}", file=sys.stderr, flush=True)


def _emit(event: str, **kwargs) -> None:
    """Subprocess → parent: write a JSON event to stdout (one line)."""
    try:
        payload = {"event": event, **kwargs}
        sys.stdout.write(json.dumps(payload) + "\n")
        sys.stdout.flush()
    except Exception:
        pass


def _js_escape(text: str) -> str:
    return (
        (text or "")
        .replace("\\", "\\\\")
        .replace("'", "\\'")
        .replace("\n", "\\n")
        .replace("\r", "")
    )


def _find_hwnd(title: str) -> int:
    """Locate the OS HWND for our pywebview window by title. Polls
    briefly because events.shown can fire one frame before the OS lets
    FindWindowW see the new window."""
    user32 = ctypes.windll.user32
    hwnd = 0
    for _ in range(40):
        hwnd = user32.FindWindowW(None, title)
        if hwnd:
            return hwnd
        time.sleep(0.025)
    return 0


def _make_click_through(title: str) -> None:
    """Make the window pass mouse clicks to whatever is underneath it.

    Achieved by adding WS_EX_LAYERED | WS_EX_TRANSPARENT to the
    extended window style. SetLayeredWindowAttributes with alpha=255
    is required after the LAYERED flag goes on or Windows treats the
    window as fully invisible — we want fully visible but unclickable.

    Used by the compact "telegram task in progress" indicator pill so
    it never blocks the user from clicking the desktop / other apps
    beneath it; the pill is a passive visual cue, never interactive.
    Matches macOS's `setIgnoresMouseEvents_(True)` on the compact
    NSPanel."""
    user32 = ctypes.windll.user32
    hwnd = _find_hwnd(title)
    if not hwnd:
        return
    GWL_EXSTYLE = -20
    WS_EX_LAYERED = 0x00080000
    WS_EX_TRANSPARENT = 0x00000020
    LWA_ALPHA = 0x00000002
    style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
    user32.SetWindowLongW(
        hwnd, GWL_EXSTYLE, style | WS_EX_LAYERED | WS_EX_TRANSPARENT
    )
    # WS_EX_LAYERED windows render nothing until SetLayeredWindowAttributes
    # (or UpdateLayeredWindow) is called. alpha=255 → fully opaque so the
    # orb still paints normally; only mouse input is what we want to drop.
    user32.SetLayeredWindowAttributes(hwnd, 0, 255, LWA_ALPHA)


def _apply_rounded_region(title: str) -> None:
    """Clip the window with the given title into a stadium pill.

    Uses FindWindowW on the unique title to locate the HWND,
    GetWindowRect for the actual DPI-aware size, then SetWindowRgn for
    the clip. Polls briefly because events.shown can fire one frame
    before the OS lets FindWindowW see the new window."""
    user32 = ctypes.windll.user32
    gdi32 = ctypes.windll.gdi32

    hwnd = 0
    for _ in range(40):
        hwnd = user32.FindWindowW(None, title)
        if hwnd:
            break
        time.sleep(0.025)
    if not hwnd:
        return

    rect = _RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    w = rect.right - rect.left
    h = rect.bottom - rect.top
    if w <= 0 or h <= 0:
        return

    # Pill: full-height end caps via corner ellipse = h × h.
    rgn = gdi32.CreateRoundRectRgn(0, 0, w + 1, h + 1, h, h)
    user32.SetWindowRgn(hwnd, rgn, True)


# ── HTML (subprocess-side only — parent never touches these strings) ──

BANNER_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8" />
<style>
  html, body {
    margin: 0;
    padding: 0;
    height: 100%;
    width: 100%;
    background: #ffffff;
    overflow: hidden;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    -webkit-user-select: none;
    user-select: none;
  }

  .banner {
    width: 100%;
    height: 100%;
    display: flex;
    align-items: center;
    gap: 14px;
    padding: 0 12px 0 15px;
    box-sizing: border-box;
  }

  .banner-text {
    flex: 1;
    min-width: 0;                /* lets flex shrink-below-content so the
                                    next-btn never gets pushed out of the
                                    pill by a long unwrapped word. */
    color: #374151;
    font-size: 16px;
    font-weight: 500;
    line-height: 1.35;
    white-space: normal;
    overflow-wrap: break-word;
    word-wrap: break-word;
    padding: 10px 0;             /* breathing room top/bottom when the
                                    text wraps to multiple lines. */
  }

  .next-btn {
    background: #6366f1;
    color: #ffffff;
    border: none;
    font-family: inherit;
    font-size: 14px;
    font-weight: 600;
    padding: 10px 22px;
    border-radius: 999px;
    cursor: pointer;
    transition: background 0.15s ease;
    flex-shrink: 0;
  }
  .next-btn:hover  { background: #4f46e5; }
  .next-btn:active { background: #4338ca; }

  .choice-row { display: none; flex-shrink: 0; gap: 8px; }
  .choice-row .next-btn { padding: 8px 16px; font-size: 13px; }

  .input-row { display: none; flex: 1; align-items: center; gap: 8px; }
  #token-input {
    flex: 1;
    height: 32px;
    border: 1px solid #d1d5db;
    border-radius: 16px;
    padding: 0 12px;
    font-size: 13px;
    font-family: inherit;
    color: #374151;
    background: #ffffff;
    outline: none;
  }
  #token-input:focus { border-color: #6366f1; }

  .stop-agent-button {
    position: relative;
    width: 42px;
    height: 42px;
    flex-shrink: 0;
    background: transparent;
    border-radius: 50%;
    display: flex;
    align-items: center;
    justify-content: center;
    overflow: visible;
  }
  .stop-orb {
    position: relative;
    width: 100%;
    height: 100%;
    display: flex;
    align-items: center;
    justify-content: center;
    pointer-events: none;
  }
  .stop-circle-1 {
    width: 42px;
    height: 42px;
    border-radius: 50%;
    position: absolute;
    background: transparent;
    display: flex;
    align-items: center;
    justify-content: center;
    animation: stop-pulse 4.2s ease-in-out infinite 0.3s;
    z-index: 1;
  }
  .stop-circle-1::before, .stop-circle-1::after {
    content: ""; position: absolute; border-radius: 50%; filter: blur(8px); width: 30%; height: 30%;
  }
  .stop-circle-1::before { background: #ff0073; top: 30%; right: 30%; }
  .stop-circle-1::after  { background: #00baff; bottom: 10%; left: 30%; }

  .stop-circle-2 {
    width: 32px;
    height: 32px;
    border-radius: 50%;
    position: absolute;
    inset: 0;
    margin: auto;
    background-color: white;
    z-index: 9;
    animation: stop-pulse2 4.2s ease-in-out infinite;
  }
  .stop-circle-2::before, .stop-circle-2::after {
    content: ""; position: absolute; border-radius: 50%; filter: blur(6px); z-index: 1;
  }
  .stop-circle-2::before { background: #ff0073; width: 30%; height: 30%; top: 20%; right: 20%; }
  .stop-circle-2::after  { background: #00bbff; width: 20%; height: 20%; bottom: 10%; left: 40%; }

  .stop-bg {
    position: absolute; inset: 0; border-radius: 50%;
    box-shadow: inset 0 0 5px 2px rgba(255,255,255,0.8), 0 0 2px 2px rgba(255,255,255,0.9);
    background-color: #9292d8;
    animation: stop-bgRotate 2.5s linear infinite;
  }
  .stop-bg::before {
    content: ""; position: absolute; inset: 0; border-radius: inherit;
    animation: stop-bgColor 4s linear infinite;
    box-shadow: inset 0 0 5px 2px rgba(255,255,255,0.8);
    opacity: 0.2;
  }

  .stop-pc {
    position: absolute; inset: 0; margin: auto;
    width: 32px; height: 32px; z-index: 10;
    display: flex; flex-direction: column;
    align-items: center; justify-content: center;
    box-sizing: border-box; gap: 1px;
  }
  .stop-monitor {
    width: 12px; height: 10px; background: transparent;
    border-radius: 1px; border: 1px solid white; box-sizing: border-box;
  }
  .stop-screen {
    width: 100%; height: 100%; border-radius: 0.5px;
    display: flex; justify-content: center; align-items: center; gap: 2px;
  }
  .stop-eye {
    width: 1.5px; height: 2.5px; border-radius: 1px;
    background: white; animation: stop-blink 4s infinite;
  }
  .stop-base { width: 16px; height: 1px; background: white; border-radius: 0.5px; }

  @keyframes stop-pulse {
    0%{transform:scale(.97)} 15%{transform:scale(1)} 30%{transform:scale(.98)}
    45%{transform:scale(1)} 60%{transform:scale(.97)} 85%{transform:scale(1)}
    100%{transform:scale(.97)}
  }
  @keyframes stop-pulse2 {
    0%{transform:scale(1)} 15%{transform:scale(1.03)} 30%{transform:scale(.98)}
    45%{transform:scale(1.04)} 60%{transform:scale(.97)} 85%{transform:scale(1.03)}
    100%{transform:scale(1)}
  }
  @keyframes stop-bgRotate {
    0%{transform:rotate(0deg)} 20%{transform:rotate(90deg)}
    40%{transform:rotate(180deg) scale(.95,1)} 60%,100%{transform:rotate(360deg)}
  }
  @keyframes stop-bgColor {
    20%{background-color:red} 40%{background-color:#5eff7e}
    60%{background-color:#2cb5ff} 80%{background-color:#fc63ff}
  }
  @keyframes stop-blink {
    0%,85%,100%{transform:scaleY(1)} 92%{transform:scaleY(.1)}
  }
</style>
</head>
<body>
  <div class="banner">
    <div class="stop-agent-button">
      <div class="stop-orb">
        <div class="stop-circle-1"></div>
        <div class="stop-circle-2"><div class="stop-bg"></div></div>
        <div class="stop-pc">
          <div class="stop-monitor">
            <div class="stop-screen">
              <div class="stop-eye"></div>
              <div class="stop-eye"></div>
            </div>
          </div>
          <div class="stop-base"></div>
        </div>
      </div>
    </div>

    <div class="banner-text" id="msg">Starting…</div>

    <button class="next-btn" id="next" style="display:none"
            onclick="if(window.pywebview&&window.pywebview.api) window.pywebview.api.next_clicked()">Next</button>

    <div class="choice-row" id="choice-row">
      <button class="next-btn" id="choice-left"
              onclick="if(window.pywebview&&window.pywebview.api) window.pywebview.api.choice_clicked('left')">Left</button>
      <button class="next-btn" id="choice-right"
              onclick="if(window.pywebview&&window.pywebview.api) window.pywebview.api.choice_clicked('right')">Right</button>
    </div>

    <div class="input-row" id="input-row">
      <input type="text" id="token-input" placeholder="Paste your BotFather token here" />
      <button class="next-btn" id="save-btn"
              onclick="(function(){var v=document.getElementById('token-input').value;
                       if(window.pywebview&&window.pywebview.api) window.pywebview.api.save_clicked(v);})()">Save</button>
    </div>
  </div>

  <script>
    function setMsg(text) {
      var el = document.getElementById('msg');
      if (el) el.textContent = text || '';
    }
    function showNext()  {
      clearAll();
      document.getElementById('next').style.display = 'inline-block';
      document.getElementById('msg').style.display = 'block';
    }
    function hideNext() { document.getElementById('next').style.display = 'none'; }
    function setChoice(leftLabel, rightLabel) {
      clearAll();
      document.getElementById('msg').style.display = 'none';
      document.getElementById('choice-left').textContent = leftLabel;
      document.getElementById('choice-right').textContent = rightLabel;
      document.getElementById('choice-row').style.display = 'flex';
    }
    function setInput(saveLabel) {
      clearAll();
      document.getElementById('msg').style.display = 'none';
      document.getElementById('save-btn').textContent = saveLabel || 'Save';
      document.getElementById('input-row').style.display = 'flex';
      var inp = document.getElementById('token-input');
      inp.value = '';
      setTimeout(function(){ inp.focus(); }, 30);
    }
    function clearAll() {
      document.getElementById('next').style.display = 'none';
      document.getElementById('choice-row').style.display = 'none';
      document.getElementById('input-row').style.display = 'none';
      document.getElementById('msg').style.display = 'block';
    }
    window.setMsg = setMsg;
    window.showNext = showNext;
    window.hideNext = hideNext;
    window.setChoice = setChoice;
    window.setInput = setInput;
    window.clearAll = clearAll;

    document.getElementById('token-input').addEventListener('keydown', function(e) {
      if (e.key === 'Enter' && window.pywebview && window.pywebview.api) {
        window.pywebview.api.save_clicked(this.value);
      }
    });

    // Report body height to Python so the pywebview window can grow
    // vertically when a long wizard message wraps to multiple lines.
    // A ResizeObserver on document.body fires automatically after any
    // setMsg / setChoice / setInput / clearAll content change — we
    // don't need explicit calls inside those helpers.
    (function () {
      function reportHeight() {
        if (window.pywebview && window.pywebview.api) {
          var h = Math.ceil(document.body.scrollHeight);
          try { window.pywebview.api.height_changed(h); } catch (e) {}
        }
      }
      window.addEventListener('load', function () { setTimeout(reportHeight, 30); });
      window.addEventListener('pywebviewready', function () { setTimeout(reportHeight, 30); });
      try {
        new ResizeObserver(reportHeight).observe(document.body);
      } catch (e) {}
    })();
  </script>
</body>
</html>
"""


COMPACT_HTML = r"""<!DOCTYPE html>
<html><head><meta charset="UTF-8"><style>
  html, body { margin: 0; padding: 0; height: 100%; width: 100%;
    background: #ffffff; overflow: hidden;
    display: flex; align-items: center; justify-content: center; }
  .stop-agent-button { position: relative; width: 42px; height: 42px;
    background: transparent; display: flex; align-items: center; justify-content: center; }
  .stop-orb { position: relative; width: 100%; height: 100%;
    display: flex; align-items: center; justify-content: center; pointer-events: none; }
  .stop-circle-1 { width: 42px; height: 42px; border-radius: 50%; position: absolute;
    background: transparent; animation: stop-pulse 4.2s ease-in-out infinite 0.3s; z-index: 1; }
  .stop-circle-1::before, .stop-circle-1::after {
    content: ""; position: absolute; border-radius: 50%; filter: blur(8px); width: 30%; height: 30%; }
  .stop-circle-1::before { background: #ff0073; top: 30%; right: 30%; }
  .stop-circle-1::after  { background: #00baff; bottom: 10%; left: 30%; }
  .stop-circle-2 { width: 32px; height: 32px; border-radius: 50%; position: absolute;
    inset: 0; margin: auto; background-color: white; z-index: 9;
    animation: stop-pulse2 4.2s ease-in-out infinite; }
  .stop-bg { position: absolute; inset: 0; border-radius: 50%;
    box-shadow: inset 0 0 5px 2px rgba(255,255,255,0.8), 0 0 2px 2px rgba(255,255,255,0.9);
    background-color: #9292d8; animation: stop-bgRotate 2.5s linear infinite; }
  .stop-bg::before { content: ""; position: absolute; inset: 0; border-radius: inherit;
    animation: stop-bgColor 4s linear infinite;
    box-shadow: inset 0 0 5px 2px rgba(255,255,255,0.8); opacity: 0.2; }
  /* Both icons share this stack frame — they sit at the same position
     and cross-fade via opposing opacity keyframes. */
  .icon-stack { position: absolute; inset: 0; margin: auto;
    width: 32px; height: 32px; z-index: 10;
    display: flex; align-items: center; justify-content: center; }
  .icon-layer { position: absolute; inset: 0;
    display: flex; flex-direction: column;
    align-items: center; justify-content: center;
    gap: 1px; box-sizing: border-box;
    /* Promote each layer to its own compositor layer up-front so the
       opacity cross-fade is GPU-only — without this the first fade
       triggers a one-frame layer-promotion artifact (a tiny square
       flash) on EdgeChromium. */
    will-change: opacity;
    transform: translateZ(0);
    backface-visibility: hidden; }
  .icon-pc { animation: icon-cycle-pc 6s ease-in-out infinite; }
  .icon-tg { animation: icon-cycle-tg 6s ease-in-out infinite; color: white; }

  .stop-monitor { width: 12px; height: 10px; border: 1px solid white; box-sizing: border-box; }
  .stop-screen { width: 100%; height: 100%; display: flex;
    justify-content: center; align-items: center; gap: 2px; }
  .stop-eye { width: 1.5px; height: 2.5px; border-radius: 1px; background: white;
    animation: stop-blink 4s infinite; }
  .stop-base { width: 16px; height: 1px; background: white; border-radius: 0.5px; }

  @keyframes stop-pulse  { 0%{transform:scale(.97)} 15%{transform:scale(1)} 30%{transform:scale(.98)} 45%{transform:scale(1)} 60%{transform:scale(.97)} 85%{transform:scale(1)} 100%{transform:scale(.97)} }
  @keyframes stop-pulse2 { 0%{transform:scale(1)} 15%{transform:scale(1.03)} 30%{transform:scale(.98)} 45%{transform:scale(1.04)} 60%{transform:scale(.97)} 85%{transform:scale(1.03)} 100%{transform:scale(1)} }
  @keyframes stop-bgRotate { 0%{transform:rotate(0)} 20%{transform:rotate(90deg)} 40%{transform:rotate(180deg) scale(.95,1)} 60%,100%{transform:rotate(360deg)} }
  @keyframes stop-bgColor  { 20%{background-color:red} 40%{background-color:#5eff7e} 60%{background-color:#2cb5ff} 80%{background-color:#fc63ff} }
  @keyframes stop-blink    { 0%,85%,100%{transform:scaleY(1)} 92%{transform:scaleY(.1)} }
  /* 6 s total cycle = 3 s per icon. 0-40 % = first icon fully visible,
     40-50 % = cross-fade, 50-90 % = second icon fully visible, 90-100 %
     = cross-fade back. ease-in-out timing makes the swap feel soft. */
  @keyframes icon-cycle-pc { 0%, 40% { opacity: 1 } 50%, 90% { opacity: 0 } 100% { opacity: 1 } }
  @keyframes icon-cycle-tg { 0%, 40% { opacity: 0 } 50%, 90% { opacity: 1 } 100% { opacity: 0 } }
</style></head>
<body>
  <div class="stop-agent-button">
    <div class="stop-orb">
      <div class="stop-circle-1"></div>
      <div class="stop-circle-2"><div class="stop-bg"></div></div>
      <div class="icon-stack">
        <div class="icon-layer icon-pc">
          <div class="stop-monitor">
            <div class="stop-screen">
              <div class="stop-eye"></div>
              <div class="stop-eye"></div>
            </div>
          </div>
          <div class="stop-base"></div>
        </div>
        <div class="icon-layer icon-tg">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor"><path d="M21.5 4.5L2.5 12l5.5 2 2 6 3-3.5 5.5 4 3-16zM10 14l8.5-7L11 14.5l-1 4.5L10 14z"/></svg>
        </div>
      </div>
    </div>
  </div>
</body>
</html>
"""


# ── JS↔Python bridge (subprocess-side only) ──────────────────────────────


class _Api:
    """Exposed to JS as window.pywebview.api.<method>."""

    # Hard cap on pill height so a freakishly long message can't push it
    # into a wall-of-text rectangle. Matches the macOS banner's MAX_H.
    _MAX_PILL_HEIGHT = 200

    def __init__(self, title: str, width: int, min_h: int, compact: bool):
        self.window = None
        self._title = title
        self._w = width
        self._min_h = min_h
        self._compact = compact
        self._last_h = min_h

    def next_clicked(self, _value=None):
        _emit("NEXT")
        return None

    def choice_clicked(self, value=None):
        _emit("CHOICE", value=str(value) if value is not None else "left")
        return None

    def save_clicked(self, value=None):
        _emit("SAVE", value=value.strip() if isinstance(value, str) else "")
        return None

    def height_changed(self, h=0):
        """Resize the window to fit the reported body height, then
        re-clip the (possibly taller) window into a stadium so the end
        caps follow the new height. No-op for the compact pill which
        has no scrollable content and a constant 80×80 size."""
        if self._compact or self.window is None:
            return None
        try:
            target = max(self._min_h, min(self._MAX_PILL_HEIGHT, int(h)))
            if target == self._last_h:
                return None
            self._last_h = target
            self.window.resize(self._w, target)
            # SetWindowRgn's saved region is anchored to the OLD height,
            # so without re-clipping the bottom of the now-taller window
            # would render as a hard rectangle below the pill ends.
            _apply_rounded_region(self._title)
        except Exception:
            pass
        return None


# ── stdin reader thread (subprocess-side only) ───────────────────────────


def _stdin_reader(window) -> None:
    """Loop reading JSON commands from stdin and dispatching to the window.

    Runs on its own thread so we don't block the pywebview GUI thread."""
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except Exception:
            continue
        cmd = msg.get("cmd")
        try:
            if cmd == "MSG":
                esc = _js_escape(msg.get("text", ""))
                window.evaluate_js(f"if(window.setMsg) setMsg('{esc}');")
            elif cmd == "SHOW_NEXT":
                window.evaluate_js("if(window.showNext) showNext();")
            elif cmd == "HIDE_NEXT":
                window.evaluate_js("if(window.hideNext) hideNext();")
            elif cmd == "SHOW_CHOICE":
                left = _js_escape(msg.get("left", ""))
                right = _js_escape(msg.get("right", ""))
                window.evaluate_js(
                    f"if(window.setChoice) setChoice('{left}', '{right}');"
                )
            elif cmd == "SHOW_INPUT":
                label = _js_escape(msg.get("label", "Save"))
                window.evaluate_js(
                    f"if(window.setInput) setInput('{label}');"
                )
            elif cmd == "CLEAR":
                window.evaluate_js("if(window.clearAll) clearAll();")
            elif cmd == "CLOSE":
                try:
                    window.destroy()
                except Exception:
                    pass
                return
        except Exception:
            # Window may have been destroyed mid-flight — swallow so the
            # reader thread doesn't crash and the process exits cleanly.
            pass


# ── subprocess entry point ────────────────────────────────────────────────


def _run_subprocess_banner() -> None:
    """Subprocess body. Imports webview + tkinter lazily so the parent
    (which only uses StatusBanner) doesn't pay their startup cost when
    it imports this module.

    Mirrors `banner_test.py` byte-for-byte except for the JSON-stdio
    protocol that lets the parent drive the wizard state machine."""
    import webview
    import tkinter as tk

    compact = "--compact" in sys.argv[1:]

    # tkinter is run from a fresh process so its screen-width report is
    # the standard DPI-virtualised value — no pywebview has touched our
    # DPI awareness yet.
    try:
        r = tk.Tk()
        r.withdraw()
        screen_w = r.winfo_screenwidth()
        r.destroy()
    except Exception:
        screen_w = 1920

    w = COMPACT_SIZE if compact else PILL_WIDTH
    h = COMPACT_SIZE if compact else PILL_HEIGHT
    x = max(0, screen_w - w - SCREEN_MARGIN)
    y = SCREEN_MARGIN
    html = COMPACT_HTML if compact else BANNER_HTML
    title = f"AutoUseBanner_{uuid.uuid4().hex[:8]}"
    api = _Api(title=title, width=w, min_h=h, compact=compact)

    window = webview.create_window(
        title,
        html=html,
        js_api=api,
        width=w,
        height=h,
        min_size=(w, h),
        x=x,
        y=y,
        frameless=True,
        on_top=True,
        easy_drag=True,
        resizable=False,
    )
    api.window = window

    def _on_shown():
        # Compact mode: WinForms stretches our small create_window
        # request to its OS-imposed minimum width (~132+ logical px),
        # producing a wide pill instead of the tight circle we want.
        # A programmatic window.resize() AFTER the form is alive
        # bypasses that minimum — Form.Size setter doesn't go through
        # the SM_CXMINTRACK clamp the way the initial size does. We
        # then re-clip the (now smaller, square) window into a circle.
        if compact:
            try:
                window.resize(COMPACT_SIZE, COMPACT_SIZE)
                # Give WinForms one frame to actually realise the new
                # rect before _apply_rounded_region reads it — without
                # this the region clip runs against the old wide-pill
                # geometry and we lose the circle shape.
                time.sleep(0.1)
            except Exception:
                pass
        # Clip into a pill (or circle, in compact mode) and emit READY
        # so the parent's show() unblocks.
        _apply_rounded_region(title)
        # Compact indicator is purely visual — drop mouse input so the
        # user can click the desktop or any window underneath it. Only
        # applied to compact mode; the standard wizard pill needs
        # Next / Save / choice clicks to land.
        if compact:
            _make_click_through(title)
        _emit("READY")
        # Spawn the stdin reader once the window is up.
        threading.Thread(
            target=_stdin_reader, args=(window,), daemon=True
        ).start()

    window.events.shown += _on_shown

    # webview.start() runs the GUI loop in this subprocess's main thread.
    # Blocks until window.destroy() — which the CLOSE command triggers.
    webview.start()

    _emit("CLOSED")


# ── parent-side wrapper ──────────────────────────────────────────────────


class StatusBanner:
    """Drop-in Windows mirror of the macOS Cocoa banner, backed by a
    subprocess that runs the pywebview pill independently."""

    # Module path the subprocess runs. After merging banner_proc.py
    # into this file, the subprocess re-executes THIS module with the
    # `if __name__ == "__main__"` guard firing into
    # _run_subprocess_banner().
    _PROC_MODULE = "Auto_Use.windows_use.remote_connection.telegram.banner"

    def __init__(self, compact: bool = False):
        self._compact = compact
        self._proc: subprocess.Popen | None = None
        self._stdout_thread: threading.Thread | None = None
        self._closed = threading.Event()
        self._ready = threading.Event()
        self._next_event = threading.Event()
        self._choice_q: Queue = Queue()
        self._input_q: Queue = Queue()

    # ── public API ───────────────────────────────────────────────────────

    def show(self) -> None:
        if self._proc is not None or self._closed.is_set():
            return

        args = [sys.executable, "-m", self._PROC_MODULE]
        if self._compact:
            args.append("--compact")

        try:
            self._proc = subprocess.Popen(
                args,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                # stderr is left attached so the subprocess can write
                # diagnostics to our terminal (useful for debugging,
                # never gets parsed).
                stderr=None,
                text=True,
                bufsize=1,  # line-buffered
                # On Windows, hide the extra console window subprocess
                # would otherwise spawn.
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            _stderr(
                f"spawned banner subprocess pid={self._proc.pid} "
                f"compact={self._compact}"
            )
        except Exception as e:
            _stderr(f"banner subprocess spawn failed: {e!r}")
            self._proc = None
            return

        self._stdout_thread = threading.Thread(
            target=self._stdout_reader,
            daemon=True,
            name="banner-stdout-reader",
        )
        self._stdout_thread.start()

        # Block until the subprocess emits READY (banner is visible).
        # 15 s ceiling covers a cold Python interpreter start; under
        # normal conditions READY arrives in well under a second.
        if not self._ready.wait(timeout=15):
            _stderr("banner subprocess never emitted READY")

    def update(self, text: str) -> None:
        if self._compact:
            return
        self._send({"cmd": "MSG", "text": text or ""})

    def wait_for_next(self, timeout: float | None = None) -> bool:
        if self._compact:
            return True
        if self._proc is None:
            return True
        self._next_event.clear()
        self._send({"cmd": "SHOW_NEXT"})
        signalled = self._next_event.wait(timeout=timeout)
        self._send({"cmd": "HIDE_NEXT"})
        return signalled

    def wait_for_choice(
        self, left_label: str, right_label: str, timeout=None
    ):
        if self._compact or self._proc is None:
            return None
        self._drain(self._choice_q)
        self._send({
            "cmd": "SHOW_CHOICE",
            "left": left_label,
            "right": right_label,
        })
        try:
            value = self._choice_q.get(timeout=timeout if timeout else 600)
        except Empty:
            value = None
        self._send({"cmd": "CLEAR"})
        return value

    def wait_for_input(self, save_label: str = "Save"):
        if self._compact or self._proc is None:
            return None
        self._drain(self._input_q)
        self._send({"cmd": "SHOW_INPUT", "label": save_label})
        try:
            value = self._input_q.get(timeout=600)
        except Empty:
            value = None
        self._send({"cmd": "CLEAR"})
        return value

    def close(self) -> None:
        if self._closed.is_set():
            return
        self._closed.set()
        # Unblock anything still parked on a Queue/Event before we tear
        # the subprocess down.
        self._next_event.set()
        try:
            self._choice_q.put_nowait(None)
        except Exception:
            pass
        try:
            self._input_q.put_nowait(None)
        except Exception:
            pass

        if self._proc is None:
            return

        # Ask the subprocess to close gracefully; fall back to terminate.
        self._send({"cmd": "CLOSE"})
        try:
            self._proc.wait(timeout=3)
        except Exception:
            try:
                self._proc.terminate()
                self._proc.wait(timeout=2)
            except Exception:
                try:
                    self._proc.kill()
                except Exception:
                    pass
        self._proc = None

    # ── internals ────────────────────────────────────────────────────────

    def _send(self, msg: dict) -> None:
        """Write a JSON command to the subprocess stdin. Silent on
        broken-pipe errors so a dead subprocess doesn't crash callers."""
        if self._proc is None or self._proc.stdin is None:
            return
        try:
            self._proc.stdin.write(json.dumps(msg) + "\n")
            self._proc.stdin.flush()
        except Exception:
            pass

    def _stdout_reader(self) -> None:
        """Read JSON events from the subprocess and route to local
        Event / Queue primitives so wait_for_* unblock at the right time."""
        if self._proc is None or self._proc.stdout is None:
            return
        for line in self._proc.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except Exception:
                continue
            event = msg.get("event")
            if event == "READY":
                _stderr("banner subprocess READY — pill visible")
                self._ready.set()
            elif event == "NEXT":
                self._next_event.set()
            elif event == "CHOICE":
                self._choice_q.put(msg.get("value", "left"))
            elif event == "SAVE":
                self._input_q.put(msg.get("value", ""))
            elif event == "CLOSED":
                _stderr("banner subprocess CLOSED")
                break

        # Subprocess exited (whether via CLOSED or pipe break). Unblock
        # any pending waiters so callers don't deadlock.
        self._closed.set()
        self._ready.set()
        self._next_event.set()
        try:
            self._choice_q.put_nowait(None)
        except Exception:
            pass
        try:
            self._input_q.put_nowait(None)
        except Exception:
            pass

    @staticmethod
    def _drain(q: Queue) -> None:
        try:
            while True:
                q.get_nowait()
        except Empty:
            pass


# ── module entry: run as subprocess if invoked via `python -m …banner` ──

if __name__ == "__main__":
    _run_subprocess_banner()
