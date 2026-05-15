"""Telegram → AgentService bridge with a guided provider/model picker.

Runs as a standalone process (not mounted into Flask). On the first message
the bot asks you to pick a provider (limited to providers with a non-empty
key in api_key.txt / .env), then a model (from the same MODEL_MAPPINGS the
AutoUse frontend uses). Subsequent messages are dispatched as tasks to the
agent with that provider/model. Picked provider/model persist for the whole
chat session until you `/reset`.

Token lookup order (first non-empty wins):
  1. TELEGRAM_BOT_TOKEN env var
  2. .env at the project root
  3. Auto_Use/api_key/api_key.txt

Setup:
  1. @BotFather → /newbot → copy token.
  2. Paste it into .env OR api_key.txt as TELEGRAM_BOT_TOKEN=…
  3. Make sure at least one provider key (e.g. OPENROUTER_API_KEY=…) is set.
  4. python -m Auto_Use.macOS_use.remote_connection.telegram.service
  5. On phone: open Telegram, find your bot, send any message.
"""
import asyncio
import datetime
import importlib
import logging
import threading
from pathlib import Path

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
)

logger = logging.getLogger(__name__)

# service.py → telegram → remote_connection → macOS_use → Auto_Use → repo root
# The Telegram surface treats api_key.txt as its single source of truth — we
# deliberately do NOT consult .env or env vars here. .env is app.py's general
# env-loading concern; keeping the bot self-contained against api_key.txt
# avoids two-files-of-record confusion.
_REPO_ROOT = Path(__file__).resolve().parents[4]
_API_KEY_FILE = _REPO_ROOT / "Auto_Use" / "api_key" / "api_key.txt"

# Agent writes per-step "milestone" lines here. We tail this file during a
# task and forward each new line back to the user's Telegram chat so they
# see the agent's progress in real time.
SCRATCHPAD_PATH = (
    Path(__file__).resolve().parents[2] / "scratchpad" / "milestone" / "milestone.md"
)
SCRATCHPAD_POLL_SEC = 2.0
MAX_TG_MSG_LEN = 4000  # Telegram caps at 4096; leave headroom for safety

# Provider id → API-key name in the KV files. Same mapping the Windows side
# uses ([windows_use/remote_connection/telegram/service.py:44-51]).
PROVIDER_KEY_MAP = {
    "openrouter": "OPENROUTER_API_KEY",
    "groq":       "GROQ_API_KEY",
    "openai":     "OPENAI_API_KEY",
    "anthropic":  "ANTHROPIC_API_KEY",
    "google":     "GOOGLE_API_KEY",
    "perplexity": "PERPLEXITY_API_KEY",
}


# ── file helpers ─────────────────────────────────────────────────────────────

def _read_all_keys(path: Path) -> dict:
    """Parse a simple KEY=VALUE file (one per line) into a dict. Skips empty
    values and lines starting with '#'."""
    out = {}
    if not path.exists():
        return out
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, _, v = line.partition("=")
                k, v = k.strip(), v.strip()
                if v:
                    out[k] = v
    except Exception:
        pass
    return out


def _resolve_token() -> str | None:
    """Read TELEGRAM_BOT_TOKEN from api_key.txt only. .env and env vars are
    intentionally ignored — see header comment."""
    return _read_all_keys(_API_KEY_FILE).get("TELEGRAM_BOT_TOKEN")


def _get_available_providers() -> list:
    """Providers with a non-empty key in api_key.txt only."""
    keys = _read_all_keys(_API_KEY_FILE)
    return [
        {"id": pid, "key": keys[kname]}
        for pid, kname in PROVIDER_KEY_MAP.items()
        if keys.get(kname)
    ]


def _set_key_in_file(path: Path, key: str, value: str) -> None:
    """Write/update KEY=value in a KV file, preserving every other line.

    Unlike a naive read-all-and-write-back-with-_read_all_keys, this keeps
    empty-value placeholder lines (e.g. GROQ_API_KEY=) intact — the AutoUse
    UI relies on those for its provider list rendering.
    """
    lines = []
    found = False
    if path.exists():
        try:
            with open(path, "r", encoding="utf-8") as f:
                for raw in f:
                    stripped = raw.strip()
                    if stripped.startswith(f"{key}="):
                        lines.append(f"{key}={value}\n")
                        found = True
                    else:
                        lines.append(raw if raw.endswith("\n") else raw + "\n")
        except Exception:
            logger.warning("failed to read %s while updating %s", path, key)
            return
    if not found:
        lines.append(f"{key}={value}\n")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.writelines(lines)
    except Exception:
        logger.warning("failed to write %s", path)


def _resolve_owner_chat_id() -> int | None:
    """Owner chat_id = whoever last sent /start. Stored in api_key.txt as
    TELEGRAM_OWNER_CHAT_ID=…, so it survives restarts."""
    val = _read_all_keys(_API_KEY_FILE).get("TELEGRAM_OWNER_CHAT_ID")
    if not val:
        return None
    try:
        return int(val)
    except ValueError:
        return None


def _save_owner_chat_id(chat_id: int) -> None:
    """Persist the owner chat_id so we can message them on the next boot."""
    _set_key_in_file(_API_KEY_FILE, "TELEGRAM_OWNER_CHAT_ID", str(chat_id))


def _get_models_for_provider(provider_id: str) -> list:
    """Read MODEL_MAPPINGS from Auto_Use/macOS_use/llm_provider/<id>/view.py
    and return non-hidden entries as [{id, display_name}, …]."""
    try:
        mod = importlib.import_module(
            f"Auto_Use.macOS_use.llm_provider.{provider_id}.view"
        )
        mappings = getattr(mod, "MODEL_MAPPINGS", {})
        return [
            {"id": mid, "display_name": info.get("display_name", mid)}
            for mid, info in mappings.items()
            if not info.get("hidden", False)
        ]
    except Exception:
        return []


# ── per-chat state ───────────────────────────────────────────────────────────

# chat_id → {
#   "phase":            "idle" | "pick_provider" | "pick_model" | "ready" | "running",
#   "provider":         str | None,
#   "model":            str | None,
#   "model_display":    str | None,
#   "queue":            list[str],  # tasks waiting to run, FIFO
#   "pending":          dict[str, str],  # pending_id → task awaiting Yes/No
#   "pending_counter":  int,         # monotonic id source for pending
# }
_chat_state: dict = {}

# Guards mutations that read+modify state across threads (queue drain races
# between _run_agent's finally and the callback handler tapping "Yes").
_state_lock = threading.Lock()


def _state(chat_id: int) -> dict:
    return _chat_state.setdefault(chat_id, {"phase": "idle"})


def _maybe_run_next_queued(chat_id: int, bot, loop) -> None:
    """If this chat is ready and has a queued task, pop the next one and
    start it. Threadsafe — called from both _run_agent's finally (worker
    thread) and the q+ callback (asyncio loop)."""
    with _state_lock:
        state = _chat_state.get(chat_id)
        if not state:
            return
        if state.get("phase") != "ready":
            return
        queue = state.get("queue") or []
        if not queue:
            return
        provider = state.get("provider")
        model = state.get("model")
        if not provider or not model:
            return
        next_task = queue.pop(0)
        display = state.get("model_display") or model
        state["phase"] = "running"

    _send_chat(
        bot,
        chat_id,
        f"📝 Running queued task: {next_task[:200]}  ({provider} · {display})",
        loop,
    )
    threading.Thread(
        target=_run_agent,
        args=(next_task, provider, model, chat_id, bot, loop),
        daemon=True,
        name=f"telegram-agent-{chat_id}-queued",
    ).start()


# ── Telegram handlers ────────────────────────────────────────────────────────

def _build_online_text(providers: list) -> str:
    now_str = datetime.datetime.now().strftime("%H:%M:%S")
    if providers:
        provider_line = ", ".join(p["id"] for p in providers)
        return f"🟢 AutoUse online at {now_str}\nProviders: {provider_line}"
    return f"🟢 AutoUse online at {now_str}\nProviders: (none configured)"


async def _show_provider_picker(message):
    providers = _get_available_providers()
    # Always lead with the "AutoUse online" status line so the user gets the
    # same greeting they'd see at app boot, even when they message the bot
    # first instead of waiting for the unsolicited startup announcement.
    await message.reply_text(_build_online_text(providers))
    if not providers:
        await message.reply_text(
            "⚠️ No provider API keys found. Add at least one (e.g. "
            "OPENROUTER_API_KEY=…) to api_key.txt or .env and try again."
        )
        return False
    buttons = [
        [InlineKeyboardButton(p["id"], callback_data=f"provider:{p['id']}")]
        for p in providers
    ]
    await message.reply_text(
        "👋 Pick a provider:", reply_markup=InlineKeyboardMarkup(buttons)
    )
    return True


async def _discover_owner_from_updates(bot) -> int | None:
    """Peek at the latest pending update on Telegram's servers and use its
    chat_id as the owner. Lets the bot self-bootstrap on the very first run
    after the chat-saving code was deployed, without requiring the user to
    /start again. Safe to call before start_polling — uses offset=-1 which
    Telegram supports as 'just the most recent update', and doesn't consume
    updates from the polling updater's offset cursor."""
    try:
        updates = await bot.get_updates(offset=-1, limit=1, timeout=2)
    except Exception:
        logger.warning("owner discovery: get_updates failed", exc_info=True)
        return None
    for upd in updates:
        chat = getattr(upd, "effective_chat", None)
        if chat and chat.id:
            return int(chat.id)
    return None


async def _post_init(application) -> None:
    """Fires once after the bot finishes initialising (before polling starts).
    Used to message the saved owner: 'AutoUse online at …' + a fresh provider
    picker — so the user doesn't have to send anything to get going."""
    owner_id = _resolve_owner_chat_id()
    if not owner_id:
        # Not saved yet — try to auto-discover from Telegram's pending updates.
        # Works if the user has ever messaged the bot, even before the
        # chat-saving code was deployed. Persist the result so we don't need
        # to re-discover on every boot.
        owner_id = await _discover_owner_from_updates(application.bot)
        if owner_id:
            try:
                _save_owner_chat_id(owner_id)
                logger.info(
                    "owner discovery: saved chat_id=%s from getUpdates",
                    owner_id,
                )
            except Exception:
                logger.warning("owner discovery: could not persist chat_id", exc_info=True)
    if not owner_id:
        # No owner anywhere — they've never interacted with the bot. Stay
        # silent; they'll register themselves with /start.
        return
    bot = application.bot
    providers = _get_available_providers()
    try:
        await bot.send_message(chat_id=owner_id, text=_build_online_text(providers))
    except Exception:
        logger.exception("startup announcement: failed to send hello")
        return  # if we can't even greet, don't bother with the picker

    if not providers:
        try:
            await bot.send_message(
                chat_id=owner_id,
                text="⚠️ No provider API keys found. Add at least one to api_key.txt and /reset.",
            )
        except Exception:
            pass
        return

    buttons = [
        [InlineKeyboardButton(p["id"], callback_data=f"provider:{p['id']}")]
        for p in providers
    ]
    try:
        await bot.send_message(
            chat_id=owner_id,
            text="👋 Pick a provider:",
            reply_markup=InlineKeyboardMarkup(buttons),
        )
        # Park the owner's chat in pick_provider so the next button tap routes
        # cleanly through the existing callback flow.
        _chat_state[owner_id] = {"phase": "pick_provider"}
    except Exception:
        logger.exception("startup announcement: failed to send provider picker")


async def start_cmd(update, ctx):
    chat_id = update.effective_chat.id
    # Remember this chat so future boots can auto-greet (Phase 10 startup
    # announcement). Best-effort — never let a file-write failure block /start.
    try:
        _save_owner_chat_id(chat_id)
    except Exception:
        logger.warning("could not persist owner chat_id", exc_info=True)
    _chat_state[chat_id] = {"phase": "pick_provider"}
    ok = await _show_provider_picker(update.message)
    if not ok:
        _chat_state[chat_id] = {"phase": "idle"}


async def reset_cmd(update, ctx):
    # Wipe state for this chat — including any queued tasks and pending
    # awaiting Yes/No prompts. We do NOT clear the persisted owner chat_id;
    # /reset is "start over the conversation", not "forget I exist".
    _chat_state[update.effective_chat.id] = {"phase": "idle"}
    await update.message.reply_text(
        "🔄 Reset. Send any message to pick a provider again."
    )


async def text_handler(update, ctx):
    chat_id = update.effective_chat.id
    # Persist on every message, not just /start, so the next app boot can
    # auto-announce "AutoUse online" without the user having to /start first.
    try:
        _save_owner_chat_id(chat_id)
    except Exception:
        logger.warning("could not persist owner chat_id", exc_info=True)
    state = _state(chat_id)
    phase = state.get("phase", "idle")

    if phase in ("idle", "pick_provider"):
        state["phase"] = "pick_provider"
        ok = await _show_provider_picker(update.message)
        if not ok:
            state["phase"] = "idle"
        return

    if phase == "pick_model":
        await update.message.reply_text(
            "Pick a model from the buttons above first."
        )
        return

    if phase == "running":
        # Busy — offer to queue this task. Each pending prompt gets a unique
        # id so multiple "queue this?" prompts can coexist if the user spams.
        task = (update.message.text or "").strip()
        if not task:
            return
        state.setdefault("pending", {})
        state["pending_counter"] = state.get("pending_counter", 0) + 1
        pending_id = str(state["pending_counter"])
        state["pending"][pending_id] = task
        buttons = [[
            InlineKeyboardButton("✅ Yes, queue it", callback_data=f"q+:{pending_id}"),
            InlineKeyboardButton("❌ No",            callback_data=f"q-:{pending_id}"),
        ]]
        await update.message.reply_text(
            f"⏳ Currently busy performing a task.\n"
            f"Do you want to queue: \"{task[:200]}\" ?",
            reply_markup=InlineKeyboardMarkup(buttons),
        )
        return

    # phase == "ready"
    task = (update.message.text or "").strip()
    if not task:
        return
    state["phase"] = "running"
    provider = state["provider"]
    model = state["model"]
    display = state.get("model_display", model)
    await update.message.reply_text(
        f"📝 Running: {task}  ({provider} · {display})"
    )
    bot = ctx.bot
    loop = asyncio.get_running_loop()
    threading.Thread(
        target=_run_agent,
        args=(task, provider, model, chat_id, bot, loop),
        daemon=True,
    ).start()


async def callback_handler(update, ctx):
    query = update.callback_query
    await query.answer()
    chat_id = query.message.chat_id
    try:
        _save_owner_chat_id(chat_id)
    except Exception:
        logger.warning("could not persist owner chat_id", exc_info=True)
    state = _state(chat_id)
    data = query.data or ""

    if data.startswith("provider:"):
        provider_id = data.split(":", 1)[1]
        state["provider"] = provider_id
        state["phase"] = "pick_model"
        models = _get_models_for_provider(provider_id)
        if not models:
            state["phase"] = "pick_provider"
            await query.edit_message_text(
                f"⚠️ No models found for {provider_id}. Pick another provider."
            )
            return
        buttons = [
            [InlineKeyboardButton(m["display_name"], callback_data=f"model:{m['id']}")]
            for m in models
        ]
        await query.edit_message_text(
            f"Pick a model for {provider_id}:",
            reply_markup=InlineKeyboardMarkup(buttons),
        )
        return

    if data.startswith("model:"):
        model_id = data.split(":", 1)[1]
        provider_id = state.get("provider")
        if not provider_id:
            state["phase"] = "idle"
            await query.edit_message_text("Session expired. Send any message to start over.")
            return
        models = _get_models_for_provider(provider_id)
        display = next(
            (m["display_name"] for m in models if m["id"] == model_id), model_id
        )
        state["model"] = model_id
        state["model_display"] = display
        state["phase"] = "ready"
        await query.edit_message_text(
            f"✅ Provider: {provider_id} / Model: {display}\n"
            f"Send me a task whenever you're ready."
        )
        return

    if data.startswith("q+:"):
        # User wants to queue the pending task.
        pending_id = data.split(":", 1)[1]
        task = (state.get("pending") or {}).pop(pending_id, None)
        if not task:
            await query.edit_message_text("(That prompt has already been handled.)")
            return
        state.setdefault("queue", []).append(task)
        qlen = len(state["queue"])
        await query.edit_message_text(
            f"📥 Queued (position {qlen}): \"{task[:200]}\"\n"
            f"Will run when the current task finishes."
        )
        # Edge case: agent finished in the milliseconds between the prompt
        # being sent and the user tapping Yes. Drain the queue now so the
        # queued task isn't stranded.
        _maybe_run_next_queued(chat_id, ctx.bot, asyncio.get_running_loop())
        return

    if data.startswith("q-:"):
        # User declines to queue. Drop the pending task.
        pending_id = data.split(":", 1)[1]
        (state.get("pending") or {}).pop(pending_id, None)
        await query.edit_message_text(
            "👍 OK, won't queue it. I'll let you know once the current task is done."
        )
        return


# ── scratchpad streaming ─────────────────────────────────────────────────────

def _send_chat(bot, chat_id, text, loop, wait: bool = False, timeout: float = 5.0):
    """Schedule a bot.send_message on the asyncio loop from a worker thread.
    Silently ignores failures so a transient send error never kills the
    monitor thread.

    When wait=True, block the calling thread until the send actually
    completes (or `timeout` seconds elapse). Used for terminal messages
    like "✅ Done." that must land in the chat BEFORE the next message
    is scheduled — without it, the "Done" send and the "Running queued
    task" send race inside the asyncio loop as two parallel HTTP POSTs
    and Telegram can deliver them out of order."""
    try:
        fut = asyncio.run_coroutine_threadsafe(
            bot.send_message(chat_id=chat_id, text=text), loop
        )
        if wait:
            try:
                fut.result(timeout=timeout)
            except Exception:
                logger.warning(
                    "send_message to chat %s did not confirm within %ss",
                    chat_id, timeout, exc_info=True,
                )
    except Exception:
        logger.warning("Failed to schedule send_message to chat %s", chat_id)


def _monitor_scratchpad(chat_id, bot, loop, stop_event, start_pos):
    """Tail SCRATCHPAD_PATH and forward each new non-empty line to the chat.

    Polls every SCRATCHPAD_POLL_SEC seconds. start_pos is the byte offset
    the file was at when the task began — we only forward content written
    AFTER that, so old milestones from previous tasks aren't replayed.
    Exits when stop_event is set, after one final sweep to flush any tail.
    """
    last_pos = start_pos

    def _read_and_forward():
        nonlocal last_pos
        if not SCRATCHPAD_PATH.exists():
            # File was deleted (e.g. AgentService.__init__ wiping the
            # scratchpad). Reset so the next poll re-reads the whole new
            # file from the top instead of seeking past its end.
            last_pos = 0
            return
        try:
            # Defensive: if the file shrank below last_pos it was truncated
            # or rotated; restart from byte 0 so we don't slice into the
            # middle of fresh content and stream a fragment.
            try:
                current_size = SCRATCHPAD_PATH.stat().st_size
                if current_size < last_pos:
                    last_pos = 0
            except Exception:
                pass
            with open(SCRATCHPAD_PATH, "r", encoding="utf-8", errors="replace") as f:
                f.seek(last_pos)
                new_content = f.read()
                if not new_content:
                    return
                last_pos = f.tell()
        except Exception as exc:
            logger.warning("Scratchpad read error: %s", exc)
            return
        for raw in new_content.splitlines():
            line = raw.strip()
            if not line:
                continue
            # Chunk excessively long lines so we stay under Telegram's 4096 cap.
            for i in range(0, len(line), MAX_TG_MSG_LEN):
                _send_chat(bot, chat_id, line[i : i + MAX_TG_MSG_LEN], loop)

    while not stop_event.is_set():
        _read_and_forward()
        stop_event.wait(SCRATCHPAD_POLL_SEC)

    # Final sweep — catches any line written between the last poll and the
    # stop_event being set (e.g. the agent's very last milestone).
    _read_and_forward()


# ── agent runner (worker thread) ─────────────────────────────────────────────

def _run_agent(task, provider, model, chat_id, bot, loop):
    """Run the agent and ping the chat when done. Streams scratchpad milestones
    back to the chat live while the agent works. Pops a compact pill so the
    Mac user can see a Telegram task is running, and minimises the main app
    window so the agent has the screen to itself. Restores phase to 'ready'."""
    # Compact "Telegram task in progress" indicator + minimise AutoUse window.
    # Both are best-effort — never let UI fluff block the actual task.
    from Auto_Use.macOS_use.remote_connection.telegram.banner import StatusBanner
    task_banner = StatusBanner(compact=True)
    try:
        task_banner.show()
    except Exception:
        logger.warning("could not show task banner", exc_info=True)
    # Minimise the AutoUse pywebview window so the agent has the screen to
    # itself. We talk to pywebview directly via its global `windows` list
    # rather than importing from app.py — `python app.py` makes app.py the
    # __main__ module, so `from app import …` would re-import a *second*
    # copy of app.py whose webview_window is still None, and the call would
    # silently no-op.
    try:
        import webview as _webview
        if _webview.windows:
            _webview.windows[0].minimize()
    except Exception:
        logger.warning("could not minimise AutoUse window", exc_info=True)

    # Reset the milestone scratchpad to empty before starting the monitor.
    # AgentService.__init__ wipes the entire scratchpad/ directory in
    # _cleanup_scratchpad() — so if we snapshotted the file's current size
    # here and the agent then deleted + rewrote it, the monitor's last_pos
    # would point mid-way into the fresh content and we'd stream a
    # fragment (e.g. "ome." instead of "Verified: …Chrome.") to the chat.
    # Deleting the file ourselves up front and starting from byte 0 keeps
    # the monitor aligned with whatever the agent writes next. Best-effort
    # — a failure here just degrades us back to the old (buggy) behavior.
    try:
        if SCRATCHPAD_PATH.exists():
            SCRATCHPAD_PATH.unlink()
    except Exception:
        logger.warning("could not reset milestone scratchpad", exc_info=True)
    start_pos = 0
    stop_event = threading.Event()
    monitor = threading.Thread(
        target=_monitor_scratchpad,
        args=(chat_id, bot, loop, stop_event, start_pos),
        daemon=True,
        name=f"telegram-scratchpad-{chat_id}",
    )
    monitor.start()

    try:
        # Imported lazily — pulls in tree/element → skimage etc., which we
        # don't want to load until a task actually runs.
        from Auto_Use.macOS_use.agent.service import AgentService

        agent = AgentService(
            provider=provider,
            model=model,
            save_conversation=False,
            thinking=True,
        )
        agent.process_request(task)
        # Stop the monitor BEFORE the done message so the final scratchpad
        # sweep happens first — keeps the chat in correct chronological order.
        stop_event.set()
        monitor.join(timeout=SCRATCHPAD_POLL_SEC + 2)
        # wait=True: block until "✅ Done." is on Telegram's servers before
        # the finally-block fires _maybe_run_next_queued, which would
        # otherwise schedule "📝 Running queued task: …" as a second,
        # concurrent HTTP POST that can race past Done in delivery.
        _send_chat(bot, chat_id, "✅ Done.", loop, wait=True)
    except Exception as e:
        logger.exception("agent error")
        stop_event.set()
        monitor.join(timeout=SCRATCHPAD_POLL_SEC + 2)
        _send_chat(bot, chat_id, f"❌ Error: {e}", loop, wait=True)
    finally:
        if not stop_event.is_set():
            stop_event.set()
        try:
            task_banner.close()
        except Exception:
            pass
        with _state_lock:
            state = _chat_state.get(chat_id)
            if state is not None and state.get("phase") == "running":
                state["phase"] = "ready"
        # Drain one queued task if any — keeps phase='running' if it spawns.
        _maybe_run_next_queued(chat_id, bot, loop)


# ── entry points ─────────────────────────────────────────────────────────────

def _build_telegram_app(token: str):
    """Build a python-telegram-bot Application with all our handlers wired.

    `post_init` is the hook python-telegram-bot calls once after the bot
    finishes initialising but before polling starts — perfect spot to send
    the "AutoUse online" announcement + provider picker to the saved owner.
    """
    app = (
        Application.builder()
        .token(token)
        .post_init(_post_init)
        .build()
    )
    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("reset", reset_cmd))
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))
    return app


_BOT_THREAD: threading.Thread | None = None


def _stderr(msg: str) -> None:
    """Loud print to the terminal where python app.py is running — bypasses
    whatever logging config is in effect so the user actually sees it."""
    import sys
    print(f"[telegram] {msg}", file=sys.stderr, flush=True)


async def _run_bot_until_stopped(tg_app):
    """Manual lifecycle replacement for Application.run_polling().

    run_polling() messes with signals and assumes it owns the main thread;
    we want to drive it from a worker thread so we do it step by step.

    Order matches what run_polling() does internally:
      initialize → start → post_init → start_polling.
    We call _post_init BEFORE start_polling so its bot.get_updates(offset=-1)
    auto-discovery doesn't race with the updater's own polling loop.
    """
    await tg_app.initialize()
    await tg_app.start()
    # Application.post_init() is only invoked by run_polling(), not by the
    # manual initialize+start path above. Call our startup announcement
    # explicitly so the saved owner gets the "AutoUse online" message.
    try:
        await _post_init(tg_app)
    except Exception:
        logger.exception("post_init failed")
    await tg_app.updater.start_polling(allowed_updates=Update.ALL_TYPES)
    _stderr("polling loop is live — send your bot a message")
    # Park here forever (daemon thread; killed on app exit).
    await asyncio.Event().wait()


def start_bot() -> None:
    """Start the Telegram bot polling on a daemon thread.

    Idempotent — safe to call multiple times from app.py boot. Prints loudly
    to stderr at each milestone so the user can see what's happening.
    """
    global _BOT_THREAD
    if _BOT_THREAD is not None and _BOT_THREAD.is_alive():
        _stderr("start_bot() called but the bot is already running — skipping.")
        return
    token = _resolve_token()
    if not token:
        _stderr(
            "BOT NOT STARTED — TELEGRAM_BOT_TOKEN not found in env, .env, or "
            "api_key.txt. Paste your @BotFather token into one of those files."
        )
        return
    _stderr(f"starting bot (token ends in …{token[-6:]})")

    def _runner():
        import sys, traceback
        try:
            # Each thread needs its own asyncio event loop. Without this, the
            # call to asyncio.Event() inside _run_bot_until_stopped fails.
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            tg_app = _build_telegram_app(token)
            try:
                loop.run_until_complete(_run_bot_until_stopped(tg_app))
            finally:
                loop.close()
        except Exception as e:
            _stderr(f"BOT CRASHED: {e!r}")
            traceback.print_exc(file=sys.stderr)

    _BOT_THREAD = threading.Thread(target=_runner, daemon=True, name="telegram-bot")
    _BOT_THREAD.start()


def main():
    """Standalone entry — for testing without launching the full AutoUse app."""
    token = _resolve_token()
    if not token:
        raise SystemExit(
            f"TELEGRAM_BOT_TOKEN not found in {_API_KEY_FILE}\n"
            "(create the bot via @BotFather first, then add the token to that file)."
        )
    tg_app = _build_telegram_app(token)
    logger.info("Telegram bot polling started (main thread)")
    tg_app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    main()
