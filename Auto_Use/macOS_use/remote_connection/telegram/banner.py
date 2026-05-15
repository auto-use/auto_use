"""Interactive walkthrough banner for setup.py.

A small always-on-top pill at the top-right of the screen that contains:
  - the animated stop-orb on the left,
  - a status message in the middle (multi-line capable; pill grows downward),
  - a clickable "Next" button on the right (only visible when the script is
    waiting for the user — hidden during processing steps).

setup.py calls show() once, then alternates update("…") + wait_for_next()
to pace the user. close() tears it down. The Next button is shown
automatically inside wait_for_next() and hidden as soon as it returns, so
callers don't have to manage visibility manually.

The pill default height is the original 44px. When a long status message
wraps to multiple lines a ResizeObserver in JS posts the new body height
back to Python via a second WKScriptMessageHandler, and Python resizes the
NSWindow (top edge anchored, height grows downward).

Everything runs inside the existing Python process. pywebview's main-thread
NSApplication run loop (started by webview.start() in app.py) is reused —
AppKit work is dispatched onto it via PyObjCTools.AppHelper.callAfter so the
Flask worker thread that runs setup.py never touches Cocoa directly.

If Cocoa/PyObjC isn't importable for any reason the class becomes a no-op
so the automation still completes without a banner.
"""
import logging
import threading

logger = logging.getLogger(__name__)

try:
    from Cocoa import (
        NSWindow, NSColor, NSScreen,
        NSBackingStoreBuffered, NSMakeRect,
    )
    from Foundation import NSObject
    from WebKit import WKWebView, WKWebViewConfiguration
    from PyObjCTools.AppHelper import callAfter
    _COCOA_OK = True
except Exception as e:
    logger.warning(f"banner: Cocoa unavailable, popup disabled ({e})")
    _COCOA_OK = False

NSWindowStyleMaskBorderless = 0
NSStatusWindowLevel = 25


BANNER_HTML = """
<!DOCTYPE html>
<html><head><meta charset="utf-8"><style>
html, body { margin: 0; padding: 0; width: 100%; background: transparent;
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; }
html { height: 100%; }
body { display: flex; align-items: center; gap: 8px; padding: 6px 10px; box-sizing: border-box;
  min-height: 44px; overflow: hidden; }

.orb-wrap { position: relative; width: 36px; height: 36px; flex-shrink: 0;
  display: flex; align-items: center; justify-content: center; align-self: flex-start; margin-top: 0; }
.stop-circle-1 {
  width: 36px; height: 36px; border-radius: 50%; position: absolute; background: transparent;
  display: flex; align-items: center; justify-content: center;
  animation: stop-pulse 4.2s ease-in-out infinite 0.3s; z-index: 1;
}
.stop-circle-1::before, .stop-circle-1::after {
  content: ""; position: absolute; border-radius: 50%; filter: blur(7px); width: 30%; height: 30%;
}
.stop-circle-1::before { background: #ff0073; top: 30%; right: 30%; }
.stop-circle-1::after  { background: #00baff; bottom: 10%; left: 30%; }
.stop-circle-2 {
  width: 28px; height: 28px; border-radius: 50%; position: absolute; inset: 0; margin: auto;
  background-color: white; z-index: 9;
  animation: stop-pulse2 4.2s ease-in-out infinite;
}
.stop-circle-2::before, .stop-circle-2::after {
  content: ""; position: absolute; border-radius: 50%; filter: blur(5px); z-index: 1;
}
.stop-circle-2::before { background: #ff0073; width: 30%; height: 30%; top: 20%; right: 20%; }
.stop-circle-2::after  { background: #00bbff; width: 20%; height: 20%; bottom: 10%; left: 40%; }
.stop-bg {
  position: absolute; inset: 0; border-radius: 50%;
  box-shadow: inset 0 0 5px 2px rgba(255,255,255,0.8), 0 0 2px 2px rgba(255,255,255,0.9);
  background-color: #9292d8; animation: stop-bgRotate 2.5s linear infinite;
}
.stop-bg::before {
  content: ""; position: absolute; inset: 0; border-radius: inherit;
  animation: stop-bgColor 4s linear infinite;
  box-shadow: inset 0 0 5px 2px rgba(255,255,255,0.8); opacity: 0.2;
}
.stop-pc {
  position: absolute; inset: 0; margin: auto; width: 28px; height: 28px; z-index: 10;
  display: flex; flex-direction: column; align-items: center; justify-content: center;
  box-sizing: border-box; gap: 1px;
}
.stop-monitor { width: 11px; height: 9px; background: transparent; border-radius: 1px; padding: 0;
  border: 1px solid white; box-sizing: border-box; }
.stop-screen { width: 100%; height: 100%; display: flex; justify-content: center; align-items: center; gap: 2px; }
.stop-eye { width: 1.5px; height: 2.5px; border-radius: 1px; background: white; animation: stop-blink 4s infinite; }
.stop-base { width: 14px; height: 1px; background: white; border-radius: 0.5px; }

/* min-width: 0 is the flexbox shrink-below-content-size fix — without it a
   long message refuses to shrink and pushes the Next button off the pill. */
.msg { flex: 1 1 auto; min-width: 0; font-size: 12.5px; color: #6b6b75; padding: 0 4px;
  line-height: 1.35; word-wrap: break-word; overflow-wrap: break-word; }

.next-btn { flex-shrink: 0; height: 28px; padding: 0 14px; border: none; border-radius: 14px;
  background: #5e6ad2; color: white; font-size: 12px; font-weight: 600; cursor: pointer;
  font-family: inherit; transition: background 0.15s ease; align-self: center; }
.next-btn:hover  { background: #6e7ce3; }
.next-btn:active { background: #4e5ac2; }

@keyframes stop-pulse  { 0%{transform:scale(.97)} 15%{transform:scale(1)} 30%{transform:scale(.98)} 45%{transform:scale(1)} 60%{transform:scale(.97)} 85%{transform:scale(1)} 100%{transform:scale(.97)} }
@keyframes stop-pulse2 { 0%{transform:scale(1)} 15%{transform:scale(1.03)} 30%{transform:scale(.98)} 45%{transform:scale(1.04)} 60%{transform:scale(.97)} 85%{transform:scale(1.03)} 100%{transform:scale(1)} }
@keyframes stop-bgRotate { 0%{transform:rotate(0)} 20%{transform:rotate(90deg)} 40%{transform:rotate(180deg) scale(.95,1)} 60%,100%{transform:rotate(360deg)} }
@keyframes stop-bgColor  { 20%{background-color:red} 40%{background-color:#5eff7e} 60%{background-color:#2cb5ff} 80%{background-color:#fc63ff} }
@keyframes stop-blink    { 0%,85%,100%{transform:scaleY(1)} 92%{transform:scaleY(.1)} }
</style></head>
<body>
<div class="orb-wrap">
  <div class="stop-circle-1"></div>
  <div class="stop-circle-2"><div class="stop-bg"></div></div>
  <div class="stop-pc">
    <div class="stop-monitor"><div class="stop-screen"><div class="stop-eye"></div><div class="stop-eye"></div></div></div>
    <div class="stop-base"></div>
  </div>
</div>
<span class="msg" id="msg">Starting…</span>
<button class="next-btn" id="next"
        onclick="webkit.messageHandlers.next_clicked.postMessage(1)">Next</button>
<script>
  // Word-by-word reveal: Python calls setMsg("…") with the full text; we
  // animate it in word-at-a-time so the banner reads smoothly. A new call
  // cancels any in-flight animation and starts over with the latest text.
  let _revealTimer = null;
  function setMsg(fullText) {
    if (_revealTimer) { clearTimeout(_revealTimer); _revealTimer = null; }
    const el = document.getElementById('msg');
    if (!el) return;
    const words = (fullText || '').split(/(\s+)/);  // keep whitespace tokens
    el.textContent = '';
    let i = 0;
    const step = () => {
      if (i >= words.length) { _revealTimer = null; return; }
      el.textContent += words[i];
      i++;
      _revealTimer = setTimeout(step, 70);
    };
    step();
  }
  window.setMsg = setMsg;

  // Tell Python whenever the body's natural height changes so the NSWindow
  // can grow/shrink to fit. Debounced to the last reported value to avoid
  // a resize loop (window resize → WebView resize → body re-measure → fire).
  (function () {
    let last = -1;
    const report = () => {
      const h = Math.ceil(document.body.scrollHeight);
      if (h === last) return;
      last = h;
      try { webkit.messageHandlers.height_changed.postMessage(h); } catch (e) {}
    };
    window.addEventListener('load', () => setTimeout(report, 30));
    const ro = new ResizeObserver(report);
    ro.observe(document.body);
    ro.observe(document.getElementById('msg'));
  })();
</script>
</body></html>
"""


# Compact HTML — used when StatusBanner(compact=True). Just the orb in a tiny
# circular pill, no message span, no Next button, no JS message handlers. The
# centred PC monitor icon cross-fades with a Telegram paper-plane every ~5s
# so the user can tell at a glance this is a Telegram-triggered task.
COMPACT_HTML = """
<!DOCTYPE html>
<html><head><meta charset="utf-8"><style>
html, body { margin: 0; padding: 0; width: 100%; height: 100%; background: transparent;
  overflow: hidden; }
body { display: flex; align-items: center; justify-content: center; }

.orb-wrap { position: relative; width: 36px; height: 36px;
  display: flex; align-items: center; justify-content: center; }

.stop-circle-1 {
  width: 36px; height: 36px; border-radius: 50%; position: absolute; background: transparent;
  display: flex; align-items: center; justify-content: center;
  animation: stop-pulse 4.2s ease-in-out infinite 0.3s; z-index: 1;
}
.stop-circle-1::before, .stop-circle-1::after {
  content: ""; position: absolute; border-radius: 50%; filter: blur(7px); width: 30%; height: 30%;
}
.stop-circle-1::before { background: #ff0073; top: 30%; right: 30%; }
.stop-circle-1::after  { background: #00baff; bottom: 10%; left: 30%; }
.stop-circle-2 {
  width: 28px; height: 28px; border-radius: 50%; position: absolute; inset: 0; margin: auto;
  background-color: white; z-index: 9;
  animation: stop-pulse2 4.2s ease-in-out infinite;
}
.stop-circle-2::before, .stop-circle-2::after {
  content: ""; position: absolute; border-radius: 50%; filter: blur(5px); z-index: 1;
}
.stop-circle-2::before { background: #ff0073; width: 30%; height: 30%; top: 20%; right: 20%; }
.stop-circle-2::after  { background: #00bbff; width: 20%; height: 20%; bottom: 10%; left: 40%; }
.stop-bg {
  position: absolute; inset: 0; border-radius: 50%;
  box-shadow: inset 0 0 5px 2px rgba(255,255,255,0.8), 0 0 2px 2px rgba(255,255,255,0.9);
  background-color: #9292d8; animation: stop-bgRotate 2.5s linear infinite;
}
.stop-bg::before {
  content: ""; position: absolute; inset: 0; border-radius: inherit;
  animation: stop-bgColor 4s linear infinite;
  box-shadow: inset 0 0 5px 2px rgba(255,255,255,0.8); opacity: 0.2;
}

/* Both icons stacked at the same spot; opposing keyframes cross-fade them. */
.icon-stack {
  position: absolute; inset: 0; margin: auto; width: 28px; height: 28px; z-index: 10;
  display: flex; align-items: center; justify-content: center;
}
.icon-layer {
  position: absolute; inset: 0;
  display: flex; flex-direction: column; align-items: center; justify-content: center;
  gap: 1px; box-sizing: border-box;
  /* Force each layer onto its own GPU compositor layer up-front so the
     opacity cross-fade doesn't trigger a one-frame promotion artifact (the
     "small square" flash). */
  will-change: opacity;
  transform: translateZ(0);
  -webkit-backface-visibility: hidden;
  backface-visibility: hidden;
}
.icon-pc { animation: icon-cycle-pc 10s ease-in-out infinite; }
.icon-tg { animation: icon-cycle-tg 10s ease-in-out infinite; color: white; }

.stop-monitor { width: 11px; height: 9px; background: transparent; border-radius: 1px; padding: 0;
  border: 1px solid white; box-sizing: border-box; }
.stop-screen { width: 100%; height: 100%; display: flex; justify-content: center; align-items: center; gap: 2px; }
.stop-eye { width: 1.5px; height: 2.5px; border-radius: 1px; background: white; animation: stop-blink 4s infinite; }
.stop-base { width: 14px; height: 1px; background: white; border-radius: 0.5px; }

@keyframes stop-pulse  { 0%{transform:scale(.97)} 15%{transform:scale(1)} 30%{transform:scale(.98)} 45%{transform:scale(1)} 60%{transform:scale(.97)} 85%{transform:scale(1)} 100%{transform:scale(.97)} }
@keyframes stop-pulse2 { 0%{transform:scale(1)} 15%{transform:scale(1.03)} 30%{transform:scale(.98)} 45%{transform:scale(1.04)} 60%{transform:scale(.97)} 85%{transform:scale(1.03)} 100%{transform:scale(1)} }
@keyframes stop-bgRotate { 0%{transform:rotate(0)} 20%{transform:rotate(90deg)} 40%{transform:rotate(180deg) scale(.95,1)} 60%,100%{transform:rotate(360deg)} }
@keyframes stop-bgColor  { 20%{background-color:red} 40%{background-color:#5eff7e} 60%{background-color:#2cb5ff} 80%{background-color:#fc63ff} }
@keyframes stop-blink    { 0%,85%,100%{transform:scaleY(1)} 92%{transform:scaleY(.1)} }
@keyframes icon-cycle-pc { 0%, 40% { opacity: 1 } 50%, 90% { opacity: 0 } 100% { opacity: 1 } }
@keyframes icon-cycle-tg { 0%, 40% { opacity: 0 } 50%, 90% { opacity: 1 } 100% { opacity: 0 } }
</style></head>
<body>
<div class="orb-wrap">
  <div class="stop-circle-1"></div>
  <div class="stop-circle-2"><div class="stop-bg"></div></div>
  <div class="icon-stack">
    <div class="icon-layer icon-pc">
      <div class="stop-monitor"><div class="stop-screen"><div class="stop-eye"></div><div class="stop-eye"></div></div></div>
      <div class="stop-base"></div>
    </div>
    <div class="icon-layer icon-tg">
      <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor"><path d="M21.5 4.5L2.5 12l5.5 2 2 6 3-3.5 5.5 4 3-16zM10 14l8.5-7L11 14.5l-1 4.5L10 14z"/></svg>
    </div>
  </div>
</div>
</body></html>
"""


if _COCOA_OK:
    class _NextHandler(NSObject):
        """WKScriptMessageHandler — fires self._event when JS posts to 'next_clicked'.

        No custom init: PyObjC's bridged NSObject.init takes no args, so calling
        NSObject.init(self) inside a subclass crashes with "Need 0 arguments,
        got 1". Instead, allocate with the default init and set the event as a
        plain Python attribute right after — PyObjC subclasses accept arbitrary
        Python attributes just fine.
        """
        def userContentController_didReceiveScriptMessage_(self, controller, message):
            try:
                self._event.set()
            except Exception:
                pass

    class _HeightHandler(NSObject):
        """WKScriptMessageHandler — receives body.scrollHeight from JS and calls
        the banner's _on_height_changed on the main thread (already the current
        thread, since WK message delivery is on main)."""
        def userContentController_didReceiveScriptMessage_(self, controller, message):
            try:
                banner = self._banner
                if banner is not None:
                    banner._on_height_changed(int(message.body()))
            except Exception:
                pass
else:
    _NextHandler = None
    _HeightHandler = None


class StatusBanner:
    W, MIN_H, MAX_H, TOP_MARGIN, RIGHT_MARGIN = 440, 44, 200, 56, 20
    # Compact variant: just the orb, no msg / button / scripts. Fixed-size
    # circular pill (W == H, radius == W/2). Used for "Telegram task running"
    # indicator — pure visual, click-through. Sized to hug the 36 px orb with
    # ~4 px breathing room — anything taller and the pill looks padded.
    COMPACT_W = COMPACT_H = 44

    def __init__(self, compact: bool = False):
        self._compact = compact
        self._window = None
        self._webview = None
        self._next_handler = None    # strong refs so the JS-bridge handlers
        self._height_handler = None  # don't get GC'd
        self._next_event = threading.Event()
        self._current_h = self.COMPACT_H if compact else self.MIN_H

    # ---- public API (callable from any thread) ----

    def show(self):
        if not _COCOA_OK:
            return
        callAfter(self._create)

    def update(self, text):
        # Compact pills have no msg span — silently no-op so callers don't
        # have to branch.
        if not _COCOA_OK or self._compact:
            return
        callAfter(self._set_text, text)

    def wait_for_next(self, timeout=None):
        """Block calling thread until user clicks Next (or timeout). Returns True if clicked.

        Shows the Next button on entry and hides it on exit, so during normal
        update() calls the button stays hidden — only the entry/exit boundaries
        of a wait_for_next show a clickable Next.
        """
        if not _COCOA_OK:
            return True  # no banner → don't block forever
        if self._compact:
            # No Next button in compact mode — return immediately so callers
            # that accidentally chain it don't hang forever.
            return True
        callAfter(self._set_next_visible, True)
        self._next_event.clear()
        clicked = self._next_event.wait(timeout)
        callAfter(self._set_next_visible, False)
        return clicked

    def close(self):
        if not _COCOA_OK:
            return
        callAfter(self._destroy)

    # ---- main-thread implementations ----

    def _create(self):
        try:
            scr = NSScreen.mainScreen().frame()
            if self._compact:
                w_px, h_px = self.COMPACT_W, self.COMPACT_H
                corner = w_px / 2.0
                html = COMPACT_HTML
                ignores_mouse = True  # click-through; purely visual
            else:
                w_px, h_px = self.W, self.MIN_H
                corner = self.MIN_H / 2.0
                html = BANNER_HTML
                ignores_mouse = False
            x = scr.size.width - w_px - self.RIGHT_MARGIN
            y = scr.size.height - h_px - self.TOP_MARGIN
            rect = NSMakeRect(x, y, w_px, h_px)

            w = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
                rect, NSWindowStyleMaskBorderless, NSBackingStoreBuffered, False
            )
            w.setLevel_(NSStatusWindowLevel)
            w.setOpaque_(False)
            w.setBackgroundColor_(NSColor.clearColor())
            w.setIgnoresMouseEvents_(ignores_mouse)
            w.setHasShadow_(True)
            w.setReleasedWhenClosed_(False)

            content = w.contentView()
            content.setWantsLayer_(True)
            content.layer().setBackgroundColor_(
                NSColor.colorWithCalibratedRed_green_blue_alpha_(1.0, 1.0, 1.0, 0.96).CGColor()
            )
            # Fixed at MIN_H/2 so the pill stays a stadium at default height
            # and becomes a rounded-rectangle when the height grows to fit
            # multi-line messages — cleaner than a fat oval. In compact mode
            # we use W/2 → perfect circle.
            content.layer().setCornerRadius_(corner)
            content.layer().setMasksToBounds_(True)

            cfg = WKWebViewConfiguration.alloc().init()

            # JS→Python bridges only relevant in standard mode (compact pill
            # has no Next button and a fixed size — no need for either handler).
            if not self._compact:
                nh = _NextHandler.alloc().init()
                nh._event = self._next_event
                cfg.userContentController().addScriptMessageHandler_name_(nh, "next_clicked")

                hh = _HeightHandler.alloc().init()
                hh._banner = self
                cfg.userContentController().addScriptMessageHandler_name_(hh, "height_changed")
            else:
                nh = hh = None

            wv_rect = NSMakeRect(0, 0, w_px, h_px)
            wv = WKWebView.alloc().initWithFrame_configuration_(wv_rect, cfg)
            try:
                wv.setValue_forKey_(False, "drawsBackground")
            except Exception:
                pass
            try:
                wv.setWantsLayer_(True)
                wv.layer().setBackgroundColor_(NSColor.clearColor().CGColor())
            except Exception:
                pass
            wv.loadHTMLString_baseURL_(html, None)
            content.addSubview_(wv)

            w.orderFrontRegardless()
            self._window, self._webview = w, wv
            self._next_handler, self._height_handler = nh, hh
            self._current_h = h_px
        except Exception as e:
            logger.warning(f"banner: _create failed ({e})")

    def _set_text(self, text):
        try:
            if self._webview is None:
                return
            safe = (str(text)
                    .replace("\\", "\\\\")
                    .replace("'", "\\'")
                    .replace("\n", " ")
                    .replace("\r", " "))
            # Hand the full text to JS which animates it in word-by-word so
            # the banner reads as a smooth reveal rather than snapping.
            js = f"if (window.setMsg) setMsg('{safe}'); else document.getElementById('msg').textContent = '{safe}';"
            self._webview.evaluateJavaScript_completionHandler_(js, None)
        except Exception:
            pass

    def _set_next_visible(self, visible):
        try:
            if self._webview is None:
                return
            disp = "inline-block" if visible else "none"
            js = (f"var b=document.getElementById('next'); "
                  f"if (b) b.style.display='{disp}';")
            self._webview.evaluateJavaScript_completionHandler_(js, None)
        except Exception:
            pass

    def _on_height_changed(self, requested_h):
        """Resize the NSWindow to match the WebView's content height.

        Top edge stays put — height grows downward by adjusting NSWindow's
        bottom-left origin Y. Clamped to [MIN_H, MAX_H].
        """
        try:
            if self._window is None:
                return
            new_h = max(self.MIN_H, min(int(requested_h), self.MAX_H))
            if abs(new_h - self._current_h) < 1:
                return
            self._current_h = new_h
            frame = self._window.frame()
            # NSWindow origin is bottom-left; to keep top edge fixed while
            # height changes, shift origin Y by (old_h - new_h).
            new_y = frame.origin.y + frame.size.height - new_h
            new_frame = NSMakeRect(frame.origin.x, new_y, frame.size.width, new_h)
            self._window.setFrame_display_animate_(new_frame, True, True)
            # WebView must also follow — content view auto-resizes with the
            # window, but the WKWebView subview doesn't unless told.
            if self._webview is not None:
                self._webview.setFrame_(NSMakeRect(0, 0, frame.size.width, new_h))
        except Exception as e:
            logger.warning(f"banner: _on_height_changed failed ({e})")

    def _destroy(self):
        try:
            if self._webview is not None:
                try:
                    self._webview.stopLoading()
                except Exception:
                    pass
                try:
                    cfg = self._webview.configuration()
                    if cfg is not None:
                        uc = cfg.userContentController()
                        uc.removeScriptMessageHandlerForName_("next_clicked")
                        uc.removeScriptMessageHandlerForName_("height_changed")
                except Exception:
                    pass
            if self._window is not None:
                self._window.orderOut_(None)
        except Exception:
            pass
        finally:
            try:
                self._next_event.set()
            except Exception:
                pass
            self._window = None
            self._webview = None
            self._next_handler = None
            self._height_handler = None
