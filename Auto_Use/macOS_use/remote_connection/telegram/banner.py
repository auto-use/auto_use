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
        NSPanel, NSColor, NSScreen,
        NSBackingStoreBuffered, NSMakeRect,
    )
    from Foundation import NSObject
    from WebKit import WKWebView, WKWebViewConfiguration
    from PyObjCTools.AppHelper import callAfter
    _COCOA_OK = True
except Exception as e:
    logger.warning(f"banner: Cocoa unavailable, popup disabled ({e})")
    _COCOA_OK = False

# Non-activating panel: clicks inside the WebView do NOT activate the Python
# process, so the AutoUse main pywebview window can't pop over Safari while
# the wizard is running. The panel still becomes key when a text input needs
# keyboard focus (setBecomesKeyOnlyIfNeeded_).
NSWindowStyleMaskNonactivatingPanel = 1 << 7  # 128
NSStatusWindowLevel = 25


BANNER_HTML = """
<!DOCTYPE html>
<html><head><meta charset="utf-8"><style>
html, body { margin: 0; padding: 0; width: 100%; background: transparent;
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; }
html { height: 100%; }
/* The orb is absolute-positioned (top-left, anchored), and the body has
   extra left padding (= orb-width 36 + gap 8 = 44) so flex content starts
   to the right of the orb. This decouples orb position from message
   height: no matter how many lines the message wraps to, the orb stays
   exactly where it started — first line of text stays next to it,
   additional lines flow below. */
body { display: flex; flex-wrap: wrap; align-items: center; gap: 8px;
  padding: 6px 10px 6px 54px; box-sizing: border-box;
  min-height: 44px; overflow: hidden; position: relative; }

.orb-wrap { position: absolute; top: 6px; left: 10px;
  width: 36px; height: 36px; flex-shrink: 0;
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
   long message refuses to shrink and pushes the Next button off the pill.
   align-self + padding-top pin the first line to the same vertical spot it
   sits at when single-line — so when the text wraps, the first line stays
   put and the new line flows below it instead of the whole block sliding
   down to stay centered. */
.msg { flex: 1 1 auto; min-width: 0; font-size: 12.5px; color: #6b6b75;
  padding: 10px 4px 0; line-height: 1.35;
  word-wrap: break-word; overflow-wrap: break-word;
  align-self: flex-start; }

.next-btn { flex-shrink: 0; height: 28px; padding: 0 14px; border: none; border-radius: 14px;
  background: #5e6ad2; color: white; font-size: 12px; font-weight: 600; cursor: pointer;
  font-family: inherit; transition: background 0.15s ease; align-self: center; }
.next-btn:hover  { background: #6e7ce3; }
.next-btn:active { background: #4e5ac2; }

.choice-row { display: none; flex-shrink: 0; gap: 6px; align-self: center; }
.input-row { display: none; flex-basis: 100%; flex-direction: column; gap: 4px;
  padding: 2px 4px 0; order: 1; }
.input-line { display: flex; gap: 6px; align-items: center; }
#token-input { flex: 1 1 auto; height: 28px; border: 1px solid #d4d4dc; border-radius: 14px;
  padding: 0 10px; font-size: 12px; font-family: inherit; outline: none; color: #333;
  background: white; }
#token-input:focus { border-color: #5e6ad2; }
.input-error { display: none; color: #d23; font-size: 11px; padding: 0 4px; }

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
<div class="choice-row" id="choice-row">
  <button class="next-btn" id="choice-left"
          onclick="webkit.messageHandlers.choice_clicked.postMessage('left')">Left</button>
  <button class="next-btn" id="choice-right"
          onclick="webkit.messageHandlers.choice_clicked.postMessage('right')">Right</button>
</div>
<div class="input-row" id="input-row">
  <div class="input-line">
    <input type="text" id="token-input" placeholder="Paste your BotFather token here" />
    <button class="next-btn" id="save-btn"
            onclick="(function(){var v=document.getElementById('token-input').value;
                     webkit.messageHandlers.save_clicked.postMessage(v);})()">Save</button>
  </div>
  <div class="input-error" id="input-error"></div>
</div>
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
      if (i >= words.length) {
        _revealTimer = null;
        // Tell Python the streaming reveal has finished so it can now show
        // whichever control set (Next / choice / input) is appropriate for
        // this step. Without this signal the button would pop in while the
        // text is still being typed out.
        try { webkit.messageHandlers.reveal_done.postMessage(1); } catch (e) {}
        return;
      }
      // Wrap each token in its own span and fade it in. Multiple spans are
      // in their transition at once because the inter-word delay (55 ms) is
      // shorter than the fade duration (220 ms) — that overlap is what
      // makes the stream read as smooth rather than as discrete pops.
      const span = document.createElement('span');
      span.textContent = words[i];
      span.style.opacity = '0';
      span.style.transition = 'opacity 220ms ease-out';
      el.appendChild(span);
      requestAnimationFrame(() => { span.style.opacity = '1'; });
      i++;
      _revealTimer = setTimeout(step, 55);
    };
    step();
  }
  window.setMsg = setMsg;

  // ── choice / input UI controls (paired with wait_for_choice / wait_for_input
  //    on the Python side). All three rows — #next, #choice-row, #input-row —
  //    are mutually exclusive: showing one hides the others.
  function setChoice(leftLabel, rightLabel) {
    document.getElementById('choice-left').textContent = leftLabel;
    document.getElementById('choice-right').textContent = rightLabel;
    document.getElementById('choice-row').style.display = 'flex';
    document.getElementById('next').style.display = 'none';
    document.getElementById('input-row').style.display = 'none';
  }
  function setInput(saveLabel) {
    document.getElementById('save-btn').textContent = saveLabel || 'Save';
    document.getElementById('input-row').style.display = 'flex';
    document.getElementById('choice-row').style.display = 'none';
    document.getElementById('next').style.display = 'none';
    document.getElementById('input-error').style.display = 'none';
    var inp = document.getElementById('token-input');
    inp.value = '';
    setTimeout(function(){ inp.focus(); }, 30);
  }
  function setInputError(msg) {
    var el = document.getElementById('input-error');
    if (msg) { el.textContent = msg; el.style.display = 'block'; }
    else     { el.style.display = 'none'; }
  }
  function clearAll() {
    document.getElementById('choice-row').style.display = 'none';
    document.getElementById('input-row').style.display = 'none';
    document.getElementById('input-error').style.display = 'none';
  }
  window.setChoice = setChoice;
  window.setInput = setInput;
  window.setInputError = setInputError;
  window.clearAll = clearAll;

  // Enter in the token input acts as Save.
  document.getElementById('token-input').addEventListener('keydown', function(e) {
    if (e.key === 'Enter') {
      webkit.messageHandlers.save_clicked.postMessage(this.value);
    }
  });

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
    class _NonActivatingPanel(NSPanel):
        """Borderless NSPanel that can still become key.

        AppKit returns NO from -canBecomeKeyWindow for borderless panels by
        default, which blocks WKWebView text inputs from ever receiving
        keyboard focus (the user clicks the field and nothing happens).
        Overriding to YES makes the field usable. NSWindowStyleMaskNonactivatingPanel
        is still set on the instance, so becoming key still doesn't activate
        this Python process — Safari stays in the foreground."""
        def canBecomeKeyWindow(self):
            return True


    class _ClickableWebView(WKWebView):
        """WKWebView that returns YES from acceptsFirstMouse:.

        Without this, the first click after the panel loses key status
        (e.g. user just clicked Safari) is swallowed by AppKit while it
        promotes the panel back to key — the button click never fires, and
        the user has to tap a second time. Returning YES tells AppKit to
        forward the very first click straight to the view, so single-tap
        works regardless of key-window state."""
        def acceptsFirstMouse_(self, event):
            return True


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

    class _ChoiceHandler(NSObject):
        """WKScriptMessageHandler for the two-button choice row. Stores the
        clicked label ('left' or 'right') on self._value, then fires self._event."""
        def userContentController_didReceiveScriptMessage_(self, controller, message):
            try:
                self._value = str(message.body())
                self._event.set()
            except Exception:
                pass

    class _SaveHandler(NSObject):
        """WKScriptMessageHandler for the token input. Stores the typed string
        on self._value, then fires self._event."""
        def userContentController_didReceiveScriptMessage_(self, controller, message):
            try:
                self._value = str(message.body())
                self._event.set()
            except Exception:
                pass

    class _RevealHandler(NSObject):
        """WKScriptMessageHandler fired by JS when the word-by-word setMsg
        reveal finishes. Used to gate control-set visibility on stream
        completion so buttons don't pop in mid-sentence."""
        def userContentController_didReceiveScriptMessage_(self, controller, message):
            try:
                self._event.set()
            except Exception:
                pass
else:
    _NextHandler = None
    _HeightHandler = None
    _ChoiceHandler = None
    _SaveHandler = None
    _RevealHandler = None


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
        self._choice_handler = None
        self._save_handler = None
        self._reveal_handler = None
        self._next_event = threading.Event()
        self._choice_event = threading.Event()
        self._save_event = threading.Event()
        # Set initially: no streaming reveal is pending until update() is called.
        # update() clears this; the JS reveal_done handler re-sets it.
        self._reveal_event = threading.Event()
        self._reveal_event.set()
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
        # A streaming reveal is about to start in JS; clear the event so any
        # following wait_for_* call blocks until JS posts reveal_done.
        self._reveal_event.clear()
        callAfter(self._set_text, text)

    # Cap the wait-for-reveal so a JS hiccup that drops the reveal_done
    # message can never deadlock us. Realistic banner messages stream out
    # in well under this — and shorter is better, because the wait is what
    # the user experiences between the message finishing and the button
    # showing.
    _REVEAL_WAIT_SEC = 3.0

    def _await_reveal(self):
        """Block until the most recent update()'s reveal animation has
        finished (or the safety timeout fires). No-op if no update() is
        pending — the event stays set in that case."""
        self._reveal_event.wait(self._REVEAL_WAIT_SEC)

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
        # Clear the click event BEFORE the reveal wait. If we cleared after,
        # any click that lands during streaming (rare, since the button is
        # hidden until reveal finishes — but defensive) would be wiped here
        # and the user would have to click a second time.
        self._next_event.clear()
        self._await_reveal()
        callAfter(self._clear_extra_ui)
        callAfter(self._set_next_visible, True)
        clicked = self._next_event.wait(timeout)
        callAfter(self._set_next_visible, False)
        return clicked

    def wait_for_choice(self, left_label, right_label, timeout=None):
        """Show two side-by-side buttons; block until one is clicked.
        Returns 'left' or 'right', or None on timeout / no Cocoa."""
        if not _COCOA_OK or self._compact:
            return None
        self._choice_event.clear()
        self._await_reveal()
        callAfter(self._set_next_visible, False)
        callAfter(self._show_choice, left_label, right_label)
        clicked = self._choice_event.wait(timeout)
        value = getattr(self._choice_handler, "_value", None) if clicked else None
        callAfter(self._clear_extra_ui)
        return value

    def wait_for_input(self, save_label="Save", validate=None,
                       error_msg="Token can't be empty"):
        """Show a text input + Save button; block until user submits a value
        that passes `validate` (default: non-empty after strip). Failed
        validation surfaces `error_msg` in red below the input and keeps
        waiting. Returns the accepted value, or None on no Cocoa."""
        if not _COCOA_OK or self._compact:
            return None
        if validate is None:
            validate = lambda v: bool((v or "").strip())
        self._save_event.clear()
        self._await_reveal()
        callAfter(self._set_next_visible, False)
        callAfter(self._show_input, save_label)
        try:
            while True:
                self._save_event.wait()
                # _destroy() also sets the event — bail out if the banner
                # has been torn down out from under us.
                if self._webview is None:
                    return None
                value = getattr(self._save_handler, "_value", "") or ""
                if validate(value):
                    return value
                callAfter(self._set_input_error, error_msg)
                self._save_event.clear()
        finally:
            callAfter(self._clear_extra_ui)

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

            w = _NonActivatingPanel.alloc().initWithContentRect_styleMask_backing_defer_(
                rect, NSWindowStyleMaskNonactivatingPanel,
                NSBackingStoreBuffered, False,
            )
            w.setLevel_(NSStatusWindowLevel)
            w.setOpaque_(False)
            w.setBackgroundColor_(NSColor.clearColor())
            w.setIgnoresMouseEvents_(ignores_mouse)
            w.setHasShadow_(True)
            w.setReleasedWhenClosed_(False)
            # Panels normally hide when their app deactivates — we want the
            # banner to stay visible the entire time Safari is in front.
            # Leave becomesKeyOnlyIfNeeded at the NSPanel default (NO) so a
            # click on the token input properly makes the panel key and the
            # field accepts paste / typing. NonactivatingPanelMask means
            # becoming key still doesn't activate the Python process.
            try:
                w.setHidesOnDeactivate_(False)
            except Exception:
                pass

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

                ch = _ChoiceHandler.alloc().init()
                ch._event = self._choice_event
                ch._value = None
                cfg.userContentController().addScriptMessageHandler_name_(ch, "choice_clicked")

                sh = _SaveHandler.alloc().init()
                sh._event = self._save_event
                sh._value = ""
                cfg.userContentController().addScriptMessageHandler_name_(sh, "save_clicked")

                rh = _RevealHandler.alloc().init()
                rh._event = self._reveal_event
                cfg.userContentController().addScriptMessageHandler_name_(rh, "reveal_done")
            else:
                nh = hh = ch = sh = rh = None

            wv_rect = NSMakeRect(0, 0, w_px, h_px)
            wv = _ClickableWebView.alloc().initWithFrame_configuration_(wv_rect, cfg)
            try:
                wv.setValue_forKey_(False, "drawsBackground")
            except Exception:
                pass
            try:
                wv.setWantsLayer_(True)
                wv.layer().setBackgroundColor_(NSColor.clearColor().CGColor())
            except Exception:
                pass
            # NSViewWidthSizable (2) | NSViewHeightSizable (16). When the
            # window animates between sizes (multi-line message growing,
            # collapsing back to single line), the WebView's frame follows
            # the animation instead of snapping — that's what makes the
            # pill grow/shrink as a smooth shape.
            try:
                wv.setAutoresizingMask_(2 | 16)
            except Exception:
                pass
            wv.loadHTMLString_baseURL_(html, None)
            content.addSubview_(wv)

            w.orderFrontRegardless()
            # Make the panel key on show so the first user click on Next
            # registers as the button click — not as "promote panel to key".
            # NonActivatingPanelMask means becoming key still doesn't
            # activate this Python process, so Safari stays in front.
            if not self._compact:
                try:
                    w.makeKeyWindow()
                except Exception:
                    pass
            self._window, self._webview = w, wv
            self._next_handler, self._height_handler = nh, hh
            self._choice_handler, self._save_handler = ch, sh
            self._reveal_handler = rh
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
            # Primary path: hand the full text to JS which animates it
            # word-by-word and fires reveal_done when finished. Fallback:
            # if the page-side script hasn't run yet (window.setMsg is
            # undefined — happens for the very first update right after
            # the WebView starts loading), set textContent directly and
            # post reveal_done ourselves so wait_for_next doesn't sit on
            # its safety timeout.
            js = (f"if (window.setMsg) {{ setMsg('{safe}'); }}"
                  f" else {{"
                  f"   var m = document.getElementById('msg');"
                  f"   if (m) m.textContent = '{safe}';"
                  f"   try {{ webkit.messageHandlers.reveal_done.postMessage(1); }}"
                  f"   catch (e) {{}}"
                  f" }}")
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

    @staticmethod
    def _js_escape(text):
        return (str(text)
                .replace("\\", "\\\\")
                .replace("'", "\\'")
                .replace("\n", " ")
                .replace("\r", " "))

    def _show_choice(self, left_label, right_label):
        try:
            if self._webview is None:
                return
            l = self._js_escape(left_label)
            r = self._js_escape(right_label)
            js = f"if (window.setChoice) setChoice('{l}', '{r}');"
            self._webview.evaluateJavaScript_completionHandler_(js, None)
        except Exception:
            pass

    def _show_input(self, save_label):
        try:
            if self._webview is None:
                return
            s = self._js_escape(save_label)
            js = f"if (window.setInput) setInput('{s}');"
            self._webview.evaluateJavaScript_completionHandler_(js, None)
        except Exception:
            pass

    def _set_input_error(self, msg):
        try:
            if self._webview is None:
                return
            m = self._js_escape(msg or "")
            js = f"if (window.setInputError) setInputError('{m}');"
            self._webview.evaluateJavaScript_completionHandler_(js, None)
        except Exception:
            pass

    def _clear_extra_ui(self):
        try:
            if self._webview is None:
                return
            js = "if (window.clearAll) clearAll();"
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
            # The WebView resizes with the window via its autoresizingMask
            # (set in _create), so no manual setFrame snap is needed here —
            # snapping would override the in-flight animation and the pill
            # would visually jump to its final size rather than morph.
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
                        uc.removeScriptMessageHandlerForName_("choice_clicked")
                        uc.removeScriptMessageHandlerForName_("save_clicked")
                        uc.removeScriptMessageHandlerForName_("reveal_done")
                except Exception:
                    pass
            if self._window is not None:
                self._window.orderOut_(None)
        except Exception:
            pass
        finally:
            for ev in (self._next_event, self._choice_event,
                       self._save_event, self._reveal_event):
                try:
                    ev.set()
                except Exception:
                    pass
            self._window = None
            self._webview = None
            self._next_handler = None
            self._height_handler = None
            self._choice_handler = None
            self._save_handler = None
            self._reveal_handler = None
