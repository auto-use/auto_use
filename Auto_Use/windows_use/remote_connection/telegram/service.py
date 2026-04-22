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

import asyncio
import threading
import logging
from pathlib import Path
from typing import Optional

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
    ContextTypes,
)

logger = logging.getLogger(__name__)
# AgentService is imported lazily inside _run_agent so this module (and the Telegram
# polling thread) can start without loading tree/element → skimage until a task runs.

# service.py -> telegram -> remote_connection -> windows_use -> Auto_Use / api_key / api_key.txt
API_KEY_FILE = Path(__file__).parent.parent.parent.parent / "api_key" / "api_key.txt"
MILESTONE_PATH = Path(__file__).parent.parent / "scratchpad" / "milestone" / "milestone.md"

PROVIDER_KEY_MAP = {
    'openrouter': 'OPENROUTER_API_KEY',
    'groq': 'GROQ_API_KEY',
    'openai': 'OPENAI_API_KEY',
    'anthropic': 'ANTHROPIC_API_KEY',
    'google': 'GOOGLE_API_KEY',
    'perplexity': 'PERPLEXITY_API_KEY',
}


def _read_api_keys() -> dict:
    """Read api_key.txt and return dict of key_name -> value."""
    keys = {}
    if API_KEY_FILE.exists():
        try:
            with open(API_KEY_FILE, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if '=' in line:
                        name, _, value = line.partition('=')
                        keys[name] = value
        except Exception:
            pass
    return keys


def _get_available_providers() -> list[dict]:
    """Return providers that have a non-empty API key in api_key.txt."""
    keys = _read_api_keys()
    available = []
    for provider_id, key_name in PROVIDER_KEY_MAP.items():
        if keys.get(key_name, '').strip():
            available.append({'id': provider_id, 'key': keys[key_name]})
    return available


def _get_models_for_provider(provider_id: str) -> list[dict]:
    """Import the view module for a provider and return its non-hidden models."""
    view_modules = {
        'openrouter': 'Auto_Use.windows_use.llm_provider.openrouter.view',
        'groq': 'Auto_Use.windows_use.llm_provider.groq.view',
        'openai': 'Auto_Use.windows_use.llm_provider.openai.view',
        'anthropic': 'Auto_Use.windows_use.llm_provider.anthropic.view',
        'google': 'Auto_Use.windows_use.llm_provider.google.view',
        'perplexity': 'Auto_Use.windows_use.llm_provider.perplexity.view',
    }
    module_path = view_modules.get(provider_id)
    if not module_path:
        return []
    try:
        import importlib
        mod = importlib.import_module(module_path)
        mappings = getattr(mod, 'MODEL_MAPPINGS', {})
        return [
            {'id': model_id, 'display_name': info.get('display_name', model_id)}
            for model_id, info in mappings.items()
            if not info.get('hidden', False)
        ]
    except Exception:
        return []


class TelegramAgentBot:
    """Telegram bot that lets users pick a provider/model and run agent tasks."""

    def __init__(self, token: str):
        self._token = token
        self._busy = False
        self._stop_event: Optional[threading.Event] = None
        self._pending: dict = {}  # chat_id -> {task, provider, api_key}

    # ── helpers ───────────────────────────────────────────────────────────

    def _monitor_milestones(self, chat_id: int, loop, bot, stop_event: threading.Event):
        """Poll milestone.md every 5s and send new lines to the Telegram chat."""
        last_pos = 0
        while not stop_event.is_set():
            if MILESTONE_PATH.exists():
                try:
                    with open(MILESTONE_PATH, 'r', encoding='utf-8') as f:
                        f.seek(last_pos)
                        new_content = f.read()
                        if new_content:
                            last_pos = f.tell()
                            lines = new_content.strip().split('\n')
                            for line in lines:
                                if line.strip():
                                    text = line.strip()
                                    for chunk in [text[i:i+4096] for i in range(0, len(text), 4096)]:
                                        asyncio.run_coroutine_threadsafe(
                                            bot.send_message(chat_id=chat_id, text=chunk), loop
                                        )
                except Exception as exc:
                    logger.warning("Milestone read error: %s", exc)
            stop_event.wait(5)

        # Final sweep
        if MILESTONE_PATH.exists():
            try:
                with open(MILESTONE_PATH, 'r', encoding='utf-8') as f:
                    f.seek(last_pos)
                    new_content = f.read()
                    if new_content:
                        for line in new_content.strip().split('\n'):
                            if line.strip():
                                asyncio.run_coroutine_threadsafe(
                                    bot.send_message(chat_id=chat_id, text=line.strip()), loop
                                )
            except Exception:
                pass

    def _run_agent(self, task: str, provider: str, model: str, api_key: str,
                   chat_id: int, loop, bot):
        try:
            from ...agent.service import AgentService

            agent = AgentService(
                provider=provider,
                model=model,
                save_conversation=True,
                thinking=True,
                api_key=api_key,
                stop_event=self._stop_event,
            )

            monitor = threading.Thread(
                target=self._monitor_milestones,
                args=(chat_id, loop, bot, self._stop_event),
                daemon=True,
            )
            monitor.start()

            agent.process_request(task)

            asyncio.run_coroutine_threadsafe(
                bot.send_message(chat_id=chat_id, text="✅ Task completed."), loop
            )
        except Exception as exc:
            logger.exception("Agent error")
            asyncio.run_coroutine_threadsafe(
                bot.send_message(chat_id=chat_id, text=f"❌ Agent error: {exc}"), loop
            )
        finally:
            self._busy = False
            self._stop_event = None
            self._pending.pop(chat_id, None)

    # ── Telegram handlers ────────────────────────────────────────────────

    async def start_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text(
            "👋 Send me a task and I will execute it on the desktop.\n\n"
            "Commands:\n"
            "/stop  – abort current task\n"
            "/status – check if a task is running"
        )

    async def stop_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if self._stop_event and self._busy:
            self._stop_event.set()
            await update.message.reply_text("🛑 Stop signal sent.")
        else:
            await update.message.reply_text("No task is running.")

    async def status_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if self._busy:
            await update.message.reply_text("⏳ A task is currently running. Send /stop to cancel.")
        else:
            await update.message.reply_text("💤 Idle – send a message to start a task.")

    async def task_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """User sends a text message → store it as a pending task, show provider buttons."""
        if self._busy:
            await update.message.reply_text(
                "⏳ A task is already running. Send /stop first, then try again."
            )
            return

        task = update.message.text.strip()
        if not task:
            return

        providers = _get_available_providers()
        if not providers:
            await update.message.reply_text(
                "⚠️ No API keys configured.\n"
                "Add provider API keys through the Auto Use desktop app settings first."
            )
            return

        chat_id = update.effective_chat.id
        self._pending[chat_id] = {'task': task}

        buttons = [
            [InlineKeyboardButton(p['id'], callback_data=f"provider:{p['id']}")]
            for p in providers
        ]
        await update.message.reply_text(
            f"📝 Task received:\n{task}\n\nChoose a provider:",
            reply_markup=InlineKeyboardMarkup(buttons),
        )

    async def callback_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle inline-keyboard button presses for provider/model selection."""
        query = update.callback_query
        await query.answer()
        chat_id = query.message.chat_id
        data = query.data

        pending = self._pending.get(chat_id)
        if not pending:
            await query.edit_message_text("Session expired. Send a new task.")
            return

        if data.startswith("provider:"):
            provider_id = data.split(":", 1)[1]
            providers = _get_available_providers()
            api_key = next((p['key'] for p in providers if p['id'] == provider_id), None)
            if not api_key:
                await query.edit_message_text("⚠️ API key for this provider is no longer available.")
                self._pending.pop(chat_id, None)
                return

            pending['provider'] = provider_id
            pending['api_key'] = api_key

            models = _get_models_for_provider(provider_id)
            if not models:
                await query.edit_message_text(f"⚠️ No models found for {provider_id}.")
                self._pending.pop(chat_id, None)
                return

            buttons = [
                [InlineKeyboardButton(m['display_name'], callback_data=f"model:{m['id']}")]
                for m in models
            ]
            await query.edit_message_text(
                f"Provider: {provider_id}\n\nChoose a model:",
                reply_markup=InlineKeyboardMarkup(buttons),
            )

        elif data.startswith("model:"):
            model_id = data.split(":", 1)[1]
            provider = pending.get('provider')
            api_key = pending.get('api_key')
            task = pending.get('task')

            if not all([provider, api_key, task]):
                await query.edit_message_text("Session expired. Send a new task.")
                self._pending.pop(chat_id, None)
                return

            self._busy = True
            self._stop_event = threading.Event()

            await query.edit_message_text("🤔 Thinking...")

            loop = asyncio.get_running_loop()
            bot = context.bot
            thread = threading.Thread(
                target=self._run_agent,
                args=(task, provider, model_id, api_key, chat_id, loop, bot),
                daemon=True,
            )
            thread.start()

    # ── public entry point ───────────────────────────────────────────────

    def run(self):
        """Start polling (blocking). Called from a thread by app.py."""
        app = Application.builder().token(self._token).build()
        app.add_handler(CommandHandler("start", self.start_handler))
        app.add_handler(CommandHandler("stop", self.stop_handler))
        app.add_handler(CommandHandler("status", self.status_handler))
        app.add_handler(CallbackQueryHandler(self.callback_handler))
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.task_handler))

        logger.info("Telegram bot polling started")
        app.run_polling(allowed_updates=Update.ALL_TYPES)

    def stop(self):
        """Signal any running agent to stop."""
        if self._stop_event:
            self._stop_event.set()
