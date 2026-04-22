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
Auto Use — unified entry point (Windows + macOS)
================================================
Single app.py that self-detects the host OS and routes to the matching
Auto_Use.<platform>_use package. Run directly for the GUI:

    python app.py

For binary builds, see windows_binary_build.py (produces .exe) or
mac_binary_build.py (produces .dmg / .app). Both build scripts use this
file as the single Nuitka entry point.
"""

import sys
import io
import os
import platform
import subprocess
import traceback
import logging
import threading
import time
import shutil
import importlib
from datetime import datetime
from pathlib import Path

import webview
from flask import Flask, jsonify, send_from_directory

# =============================================================================
# Platform detection
# =============================================================================
# PLATFORM_PKG is the name of the Auto_Use sub-package that contains the
# platform-specific implementation (controller, agent, llm_provider, ...).
# On Windows: Auto_Use.windows_use.*  — On macOS: Auto_Use.macOS_use.*
IS_MAC = platform.system() == "Darwin"
IS_WINDOWS = platform.system() == "Windows"

if IS_MAC:
    PLATFORM_PKG = "macOS_use"
elif IS_WINDOWS:
    PLATFORM_PKG = "windows_use"
else:
    raise RuntimeError(f"Unsupported OS: {platform.system()}")

# =============================================================================
# DEBUG LOGGING - Only for compiled binary (not in dev mode)
# =============================================================================

# Check if running as compiled binary (Nuitka)
IS_COMPILED = getattr(sys, 'frozen', False) or '__compiled__' in dir()
IS_CLI_SUBPROCESS = "--cli-mode" in sys.argv

def get_log_path():
    """Get path for debug log file (only used in compiled mode)"""
    return os.path.join(os.path.dirname(sys.executable), "autouse_debug.log")

DEBUG_LOG_PATH = get_log_path() if IS_COMPILED else None

def debug_log(message, level="INFO"):
    """Write debug message to log file (only in compiled mode)"""
    if not IS_COMPILED or not DEBUG_LOG_PATH:
        return
    try:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        log_line = f"[{timestamp}] [{level}] {message}\n"
        with open(DEBUG_LOG_PATH, 'a', encoding='utf-8') as f:
            f.write(log_line)
    except:
        pass

def debug_exception(context):
    """Log full exception traceback (only in compiled mode)"""
    if not IS_COMPILED:
        return
    debug_log(f"EXCEPTION in {context}:", "ERROR")
    debug_log(traceback.format_exc(), "ERROR")

# Initialize log file on startup (only in compiled mode, not CLI subprocess)
if IS_COMPILED and not IS_CLI_SUBPROCESS and DEBUG_LOG_PATH:
    try:
        with open(DEBUG_LOG_PATH, 'w', encoding='utf-8') as f:
            f.write(f"=== Auto Use Debug Log - Started {datetime.now()} ===\n")
            f.write(f"Python: {sys.version}\n")
            f.write(f"Platform: {platform.system()} ({PLATFORM_PKG})\n")
            f.write(f"Executable: {sys.executable}\n")
            f.write("=" * 60 + "\n\n")
    except:
        pass

# =============================================================================
# Fix for bundled app (MUST be before any print statements)
# Skip when run from main.py / cli.py so terminal output is not buffered.
# =============================================================================

def _entry_is_cli_script():
    """True when the process was started with python main.py or python cli.py."""
    if '__main__' not in sys.modules:
        return False
    main_file = getattr(sys.modules['__main__'], '__file__', None) or ''
    return os.path.basename(main_file) in ('main.py', 'cli.py')

if not _entry_is_cli_script():
    if sys.stdout is None:
        sys.stdout = open(os.devnull, 'w', encoding='utf-8')
    elif hasattr(sys.stdout, 'buffer'):
        try:
            sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
        except:
            pass

    if sys.stderr is None:
        sys.stderr = open(os.devnull, 'w', encoding='utf-8')
    elif hasattr(sys.stderr, 'buffer'):
        try:
            sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')
        except:
            pass

# =============================================================================
# EMBEDDED RESOURCE LOADER (for Nuitka compiled binary)
# =============================================================================

def _setup_embedded_resources():
    import builtins
    import base64

    try:
        from _embedded_resources import RESOURCES  # type: ignore - generated by the binary build script
    except ImportError:
        return False

    _original_open = builtins.open

    def _patched_open(file, mode='r', *args, **kwargs):
        file_str = str(file).replace('\\', '/')

        for res_path, encoded_data in RESOURCES.items():
            if file_str.endswith(res_path) or res_path in file_str:
                file_parts = file_str.split('/')
                res_parts = res_path.split('/')

                if len(file_parts) >= 2 and len(res_parts) >= 2:
                    if file_parts[-1] == res_parts[-1] and file_parts[-2] == res_parts[-2]:
                        pass
                    elif file_str.endswith(res_path):
                        pass
                    else:
                        continue
                elif file_parts[-1] != res_parts[-1]:
                    continue

                content = base64.b64decode(encoded_data)

                if 'b' in mode:
                    return io.BytesIO(content)
                else:
                    encoding = kwargs.get('encoding', 'utf-8')
                    return io.StringIO(content.decode(encoding))

        return _original_open(file, mode, *args, **kwargs)

    builtins.open = _patched_open
    return True

if IS_COMPILED:
    _setup_embedded_resources()

# =============================================================================
# Flask app initialization
# =============================================================================

def get_frontend_path():
    """Get correct frontend path for dev mode (returns None in compiled mode)"""
    if IS_COMPILED:
        return None
    else:
        return os.path.join(os.path.dirname(__file__), 'frontend')

frontend_path = get_frontend_path()
if frontend_path:
    app = Flask(__name__, static_folder=frontend_path, static_url_path='')
else:
    app = Flask(__name__)

# Suppress default Flask logging
log = logging.getLogger('werkzeug')
log.setLevel(logging.ERROR)

# =============================================================================
# Helper functions
# =============================================================================

def get_auto_use_path():
    """Get path to the Auto_Use package root"""
    if IS_COMPILED:
        return Path(sys.executable).parent / "Auto_Use"
    else:
        return Path(__file__).parent / "Auto_Use"

def get_platform_use_path():
    """Get path to the active Auto_Use/<platform>_use/ directory"""
    return get_auto_use_path() / PLATFORM_PKG

def clean_scratchpad():
    """Clear contents of <platform>_use/scratchpad/ and sandbox_workspace/ on startup"""
    try:
        scratchpad_dir = get_platform_use_path() / "scratchpad"
        if scratchpad_dir.exists():
            for item in scratchpad_dir.iterdir():
                if item.is_dir():
                    shutil.rmtree(item)
                else:
                    item.unlink()
        else:
            scratchpad_dir.mkdir(parents=True, exist_ok=True)

        # Clean sandbox_workspace on Desktop
        sandbox_dir = Path.home() / "Desktop" / "sandbox_workspace"
        if sandbox_dir.exists():
            for item in sandbox_dir.iterdir():
                if item.is_dir():
                    shutil.rmtree(item)
                else:
                    item.unlink()
    except Exception:
        debug_exception("clean_scratchpad")

def set_frontend_flag():
    """Override the FRONTEND flag in Auto_Use.<platform>_use.tree.element to True"""
    try:
        element = importlib.import_module(f"Auto_Use.{PLATFORM_PKG}.tree.element")
        element.FRONTEND = True
    except ImportError:
        pass
    except Exception:
        debug_exception("set_frontend_flag")

def request_macos_permissions():
    """Prompt user for required macOS permissions on first launch (no-op elsewhere)"""
    if not IS_MAC:
        return
    try:
        from ApplicationServices import AXIsProcessTrusted

        # Accessibility — prompt if not already granted
        if not AXIsProcessTrusted():
            from ApplicationServices import AXIsProcessTrustedWithOptions
            AXIsProcessTrustedWithOptions({"AXTrustedCheckOptionPrompt": True})

        # Screen Recording — prompt if not already granted
        from Quartz import CGPreflightScreenCaptureAccess, CGRequestScreenCaptureAccess
        if not CGPreflightScreenCaptureAccess():
            CGRequestScreenCaptureAccess()

        # Automation (Apple Events) — trigger System Events prompt at first launch
        try:
            subprocess.run(
                ["osascript", "-e", 'tell application "System Events" to return name of first process whose frontmost is true'],
                capture_output=True, text=True, timeout=10
            )
        except Exception:
            pass

    except Exception:
        debug_exception("request_macos_permissions")

def get_llm_providers():
    """Get list of available LLM providers and their models for the active platform."""
    try:
        base = f"Auto_Use.{PLATFORM_PKG}.llm_provider"
        openrouter_models = importlib.import_module(f"{base}.openrouter.view").MODEL_MAPPINGS
        groq_models       = importlib.import_module(f"{base}.groq.view").MODEL_MAPPINGS
        openai_models     = importlib.import_module(f"{base}.openai.view").MODEL_MAPPINGS
        anthropic_models  = importlib.import_module(f"{base}.anthropic.view").MODEL_MAPPINGS
        google_models     = importlib.import_module(f"{base}.google.view").MODEL_MAPPINGS
        perplexity_models = importlib.import_module(f"{base}.perplexity.view").MODEL_MAPPINGS

        def format_models(mappings):
            return [{
                'id': model_id,
                'display_name': info.get('display_name', model_id),
                'reasoning_support': info.get('reasoning_support', False)
            } for model_id, info in mappings.items() if not info.get('hidden', False)]

        return [
            {'id': 'openrouter', 'name': 'openrouter', 'models': format_models(openrouter_models)},
            {'id': 'groq',       'name': 'groq',       'models': format_models(groq_models)},
            {'id': 'openai',     'name': 'openai',     'models': format_models(openai_models)},
            {'id': 'anthropic',  'name': 'anthropic',  'models': format_models(anthropic_models)},
            {'id': 'google',     'name': 'google',     'models': format_models(google_models)},
            {'id': 'perplexity', 'name': 'perplexity', 'models': format_models(perplexity_models)},
        ]
    except Exception:
        debug_exception("get_llm_providers")
        return []

# =============================================================================
# API Key File Management
# =============================================================================

PROVIDER_KEY_MAP = {
    'openrouter': 'OPENROUTER_API_KEY',
    'groq': 'GROQ_API_KEY',
    'openai': 'OPENAI_API_KEY',
    'anthropic': 'ANTHROPIC_API_KEY',
    'google': 'GOOGLE_API_KEY',
    'perplexity': 'PERPLEXITY_API_KEY',
}

def get_api_key_file():
    """Get path to api_key.txt (lives at Auto_Use/api_key/, shared across platforms)"""
    return get_auto_use_path() / "api_key" / "api_key.txt"

# Extra keys stored in the same api_key.txt
EXTRA_KEYS = ['VERTEX_PROJECT_ID', 'VERTEX_LOCATION']

def read_api_keys():
    """Read api_key.txt and return dict of provider -> key value"""
    key_file = get_api_key_file()
    all_key_names = list(PROVIDER_KEY_MAP.values()) + EXTRA_KEYS
    keys = {k: '' for k in all_key_names}
    if key_file.exists():
        try:
            with open(key_file, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if '=' in line:
                        name, _, value = line.partition('=')
                        if name in keys:
                            keys[name] = value
        except Exception:
            debug_exception("read_api_keys")
    return keys

def write_api_keys(keys):
    """Write dict of key names -> values to api_key.txt"""
    key_file = get_api_key_file()
    try:
        key_file.parent.mkdir(parents=True, exist_ok=True)
        all_key_names = list(PROVIDER_KEY_MAP.values()) + EXTRA_KEYS
        with open(key_file, 'w', encoding='utf-8') as f:
            for name in all_key_names:
                f.write(f"{name}={keys.get(name, '')}\n")
    except Exception:
        debug_exception("write_api_keys")

def get_provider_api_key(provider):
    """Get API key for a specific provider from file"""
    env_name = PROVIDER_KEY_MAP.get(provider)
    if not env_name:
        return None
    keys = read_api_keys()
    return keys.get(env_name, '') or None

# =============================================================================
# Global state
# =============================================================================

webview_window = None
active_agent_stop_event = None
active_agent_session_id = None

# =============================================================================
# Embedded file serving (for compiled mode)
# =============================================================================

MIME_TYPES = {
    '.html': 'text/html',
    '.css': 'text/css',
    '.js': 'application/javascript',
    '.json': 'application/json',
    '.png': 'image/png',
    '.jpg': 'image/jpeg',
    '.jpeg': 'image/jpeg',
    '.gif': 'image/gif',
    '.ico': 'image/x-icon',
    '.svg': 'image/svg+xml',
    '.woff': 'font/woff',
    '.woff2': 'font/woff2',
    '.ttf': 'font/ttf',
}

def serve_embedded_file(resource_path):
    """Serve a file from embedded resources (compiled mode only)"""
    try:
        from _embedded_resources import RESOURCES  # type: ignore - generated by the binary build script
        import base64
        from flask import Response

        resource_path = resource_path.replace('\\', '/')

        for res_key, encoded_data in RESOURCES.items():
            if res_key.endswith(resource_path) or resource_path in res_key:
                if res_key.split('/')[-1] == resource_path.split('/')[-1]:
                    content = base64.b64decode(encoded_data)
                    ext = os.path.splitext(resource_path)[1].lower()
                    mime_type = MIME_TYPES.get(ext, 'application/octet-stream')
                    return Response(content, mimetype=mime_type)

        return None
    except ImportError:
        return None

# =============================================================================
# Flask routes
# =============================================================================

@app.route('/')
def index():
    if IS_COMPILED:
        response = serve_embedded_file('frontend/index.html')
        if response:
            return response
        return "index.html not found in embedded resources", 500
    return send_from_directory(app.static_folder, 'index.html')

@app.route('/<path:filename>')
def serve_static(filename):
    """Serve static files - from embedded resources in compiled mode, filesystem in dev mode"""
    if IS_COMPILED:
        for prefix in ['frontend/', f'Auto_Use/{PLATFORM_PKG}/sandbox/terminal/']:
            response = serve_embedded_file(prefix + filename)
            if response:
                return response
        response = serve_embedded_file(filename)
        if response:
            return response
        return "Not found", 404

    if app.static_folder:
        return send_from_directory(app.static_folder, filename)
    return "Not found", 404

@app.route('/terminal/<path:filename>')
def serve_terminal(filename):
    """Serve CLI agent terminal files"""
    if IS_COMPILED:
        response = serve_embedded_file(f'Auto_Use/{PLATFORM_PKG}/sandbox/terminal/{filename}')
        if response:
            return response
        return "Not found", 404

    terminal_path = os.path.join(os.path.dirname(__file__), 'Auto_Use', PLATFORM_PKG, 'sandbox', 'terminal')
    return send_from_directory(terminal_path, filename)

@app.route('/logo.png')
def serve_logo():
    """Serve the Auto Use logo for the splash screen"""
    if IS_COMPILED:
        response = serve_embedded_file('Auto_Use/logo/auto_use.png')
        if response:
            return response
        return "Logo not found", 404
    return send_from_directory(os.path.join(os.path.dirname(__file__), 'Auto_Use', 'logo'), 'auto_use.png')

@app.route('/cursor.png')
def serve_cursor():
    """Serve the cursor image for the splash animation"""
    if IS_COMPILED:
        response = serve_embedded_file('Auto_Use/logo/cursor.png')
        if response:
            return response
        return "Cursor not found", 404
    return send_from_directory(os.path.join(os.path.dirname(__file__), 'Auto_Use', 'logo'), 'cursor.png')

@app.route('/api/providers', methods=['GET'])
def get_providers():
    try:
        providers = get_llm_providers()
        return jsonify(providers)
    except Exception:
        debug_exception("get_providers API")
        return jsonify([])

@app.route('/api/keys/status', methods=['GET'])
def get_keys_status():
    """Return which providers have keys set (never returns actual keys)"""
    try:
        keys = read_api_keys()
        status = {}
        for provider_id, env_name in PROVIDER_KEY_MAP.items():
            status[provider_id] = bool(keys.get(env_name, ''))
        return jsonify(status)
    except Exception:
        debug_exception("get_keys_status")
        return jsonify({})

@app.route('/api/keys/save', methods=['POST'])
def save_api_key():
    """Save a single provider's API key to file"""
    from flask import request
    try:
        data = request.get_json()
        provider = data.get('provider')
        key_value = data.get('key', '')

        env_name = PROVIDER_KEY_MAP.get(provider)
        if not env_name:
            return jsonify({'error': 'Unknown provider'}), 400

        keys = read_api_keys()
        keys[env_name] = key_value
        write_api_keys(keys)

        return jsonify({'status': 'saved'})
    except Exception:
        debug_exception("save_api_key")
        return jsonify({'error': 'Failed to save'}), 500

@app.route('/api/keys/delete', methods=['POST'])
def delete_api_key():
    """Delete a single provider's API key from file"""
    from flask import request
    try:
        data = request.get_json()
        provider = data.get('provider')

        env_name = PROVIDER_KEY_MAP.get(provider)
        if not env_name:
            return jsonify({'error': 'Unknown provider'}), 400

        keys = read_api_keys()
        keys[env_name] = ''
        write_api_keys(keys)

        return jsonify({'status': 'deleted'})
    except Exception:
        debug_exception("delete_api_key")
        return jsonify({'error': 'Failed to delete'}), 500

@app.route('/api/vertex/status', methods=['GET'])
def get_vertex_status():
    """Return current Vertex AI config (project_id and location)"""
    try:
        keys = read_api_keys()
        return jsonify({
            'project_id': keys.get('VERTEX_PROJECT_ID', ''),
            'location': keys.get('VERTEX_LOCATION', '') or 'global'
        })
    except Exception:
        debug_exception("get_vertex_status")
        return jsonify({'project_id': '', 'location': 'global'})

@app.route('/api/vertex/save', methods=['POST'])
def save_vertex_config():
    """Save Vertex AI project ID and location to api_key.txt"""
    from flask import request
    try:
        data = request.get_json()
        project_id = data.get('project_id', '')
        location = data.get('location', 'global')

        keys = read_api_keys()
        keys['VERTEX_PROJECT_ID'] = project_id
        keys['VERTEX_LOCATION'] = location
        write_api_keys(keys)

        return jsonify({'status': 'saved'})
    except Exception:
        debug_exception("save_vertex_config")
        return jsonify({'error': 'Failed to save'}), 500

@app.route('/api/screenshot')
def get_screenshot():
    return jsonify({'image': None})

def send_image_to_frontend(base64_image):
    global webview_window
    if webview_window:
        try:
            js_code = f"window.updateAgentImage('{base64_image}')"
            webview_window.evaluate_js(js_code)
        except Exception:
            debug_exception("send_image_to_frontend")

def send_text_to_frontend(text):
    global webview_window
    if webview_window:
        try:
            escaped_text = text.replace('\\', '\\\\').replace("'", "\\'").replace('\n', '\\n').replace('\r', '\\r')
            js_code = f"window.streamAgentText('{escaped_text}')"
            webview_window.evaluate_js(js_code)
        except Exception:
            debug_exception("send_text_to_frontend")

def send_milestone_to_frontend(text):
    global webview_window
    if webview_window:
        try:
            escaped_text = text.replace('\\', '\\\\').replace("'", "\\'").replace('\n', '\\n').replace('\r', '\\r')
            js_code = f"window.streamMilestone('{escaped_text}')"
            webview_window.evaluate_js(js_code)
        except Exception:
            debug_exception("send_milestone_to_frontend")

def send_web_status_to_frontend(status):
    global webview_window
    if webview_window:
        try:
            if status == "start":
                webview_window.evaluate_js("window.webSearchStart()")
            elif status == "end":
                webview_window.evaluate_js("window.webSearchEnd()")
        except Exception:
            debug_exception("send_web_status_to_frontend")

def send_shell_status_to_frontend(event, data=None, label=None):
    """Send shell / AppleScript execution status to frontend for terminal animation.
    `label` lets callers tag the terminal card ("Shell", "AppleScript", ...);
    defaults to 'Shell' when omitted (Windows callers don't pass it)."""
    global webview_window
    if webview_window:
        try:
            if event == "start":
                escaped_cmd = (data or "").replace('\\', '\\\\').replace("'", "\\'").replace('\n', '\\n').replace('\r', '\\r')
                escaped_label = (label or "Shell").replace("'", "\\'")
                webview_window.evaluate_js(f"window.shellStart('{escaped_cmd}', '{escaped_label}')")
            elif event == "result":
                status = (data or {}).get("status", "success")
                output = (data or {}).get("output", "")
                escaped_output = output.replace('\\', '\\\\').replace("'", "\\'").replace('\n', '\\n').replace('\r', '\\r')
                webview_window.evaluate_js(f"window.shellResult('{status}', '{escaped_output}')")
            elif event == "end":
                webview_window.evaluate_js("window.shellEnd()")
        except Exception:
            debug_exception("send_shell_status_to_frontend")

@app.route('/api/start-agent', methods=['POST'])
def start_agent():
    """Start the agent with the provided provider, model, and task"""
    from flask import request
    global active_agent_stop_event, active_agent_session_id

    try:
        data = request.get_json()
        provider = data.get('provider')
        model = data.get('model')
        task = data.get('task')

        if not all([provider, model, task]):
            return jsonify({'error': 'Missing provider, model, or task'}), 400

        api_key = get_provider_api_key(provider)

        active_agent_stop_event = threading.Event()
        active_agent_session_id = str(time.time())
        current_session_id = active_agent_session_id

        def run_agent():
            stop_event = active_agent_stop_event

            def monitor_milestones():
                milestone_path = get_platform_use_path() / "scratchpad" / "milestone" / "milestone.md"
                last_pos = 0

                while not milestone_path.exists() and not stop_event.is_set():
                    time.sleep(0.5)

                while not stop_event.is_set():
                    if milestone_path.exists():
                        try:
                            with open(milestone_path, 'r', encoding='utf-8') as f:
                                f.seek(last_pos)
                                new_content = f.read()
                                if new_content:
                                    last_pos = f.tell()
                                    lines = new_content.strip().split('\n')
                                    for line in lines:
                                        if line.strip():
                                            send_milestone_to_frontend(line.strip())
                        except Exception:
                            debug_exception("monitor_milestones")
                    time.sleep(1)

                # Final read to stream any remaining milestones after agent stopped
                if milestone_path.exists():
                    try:
                        with open(milestone_path, 'r', encoding='utf-8') as f:
                            f.seek(last_pos)
                            new_content = f.read()
                            if new_content:
                                lines = new_content.strip().split('\n')
                                for line in lines:
                                    if line.strip():
                                        send_milestone_to_frontend(line.strip())
                    except Exception:
                        debug_exception("monitor_milestones final read")

            try:
                AgentService = importlib.import_module(
                    f"Auto_Use.{PLATFORM_PKG}.agent.service"
                ).AgentService

                agent = AgentService(
                    provider=provider,
                    model=model,
                    thinking=True,
                    frontend_callback=send_image_to_frontend,
                    text_callback=send_text_to_frontend,
                    web_callback=send_web_status_to_frontend,
                    shell_callback=send_shell_status_to_frontend,
                    api_key=api_key,
                    stop_event=stop_event
                )

                monitor_thread = threading.Thread(target=monitor_milestones)
                monitor_thread.daemon = True
                monitor_thread.start()

                agent.process_request(task)

            except Exception:
                debug_exception("run_agent")
            finally:
                stop_event.set()
                if webview_window and current_session_id == active_agent_session_id:
                    try:
                        webview_window.evaluate_js("window.agentComplete()")
                    except Exception:
                        debug_exception("signaling agent completion")

        thread = threading.Thread(target=run_agent)
        thread.daemon = True
        thread.start()

        return jsonify({'status': 'started'})

    except Exception as e:
        debug_exception("start_agent API")
        return jsonify({'error': str(e)}), 500

@app.route('/api/stop-agent', methods=['POST'])
def stop_agent():
    """Stop the currently running agent"""
    global active_agent_stop_event
    if active_agent_stop_event:
        active_agent_stop_event.set()
        return jsonify({'status': 'stopped'})
    return jsonify({'status': 'no_agent_running'})

def start_server():
    # Windows build exposes the Flask server on 0.0.0.0 so the Telegram
    # remote-pairing flow can reach it from other devices on the LAN.
    # macOS build sticks to localhost since it doesn't ship Telegram yet.
    host = '0.0.0.0' if IS_WINDOWS else '127.0.0.1'
    app.run(host=host, port=5000, debug=False, use_reloader=False)

def _compute_window_center(win_w, win_h):
    """Return (x, y) to center a (win_w, win_h) window on the main display.
    Falls back to a sensible default if the native APIs are unavailable."""
    try:
        if IS_MAC:
            from AppKit import NSScreen
            frame = NSScreen.mainScreen().frame()
            screen_w = frame.size.width
            screen_h = frame.size.height
            return int((screen_w - win_w) / 2), int((screen_h - win_h) / 2)

        if IS_WINDOWS:
            import ctypes

            class RECT(ctypes.Structure):
                _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                            ("right", ctypes.c_long), ("bottom", ctypes.c_long)]
            work_rect = RECT()
            # SPI_GETWORKAREA = 0x0030 — excludes the taskbar
            ctypes.windll.user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(work_rect), 0)
            area_w = work_rect.right - work_rect.left
            area_h = work_rect.bottom - work_rect.top
            cx = work_rect.left + (area_w - win_w) // 2
            cy = work_rect.top + (area_h - win_h) // 2
            return cx, cy
    except Exception:
        debug_exception("_compute_window_center")

    return 600, 30

def main():
    # Register Telegram blueprint on Windows (macOS doesn't ship it yet).
    if IS_WINDOWS:
        try:
            from Auto_Use.windows_use.remote_connection.telegram.view import telegram_bp, start_bot
            app.register_blueprint(telegram_bp)
            start_bot()
        except Exception:
            debug_exception("telegram_blueprint_init")

    if "--cli-mode" in sys.argv:
        # CLI mode - delegate to the platform-specific CLI agent
        sys.argv.remove("--cli-mode")
        try:
            cli_main = importlib.import_module(
                f"Auto_Use.{PLATFORM_PKG}.agent.cli.__main__"
            ).main
            cli_main()
        except Exception:
            debug_exception("CLI mode")
        return

    # Clean scratchpad on startup
    clean_scratchpad()

    # Set the frontend flag
    set_frontend_flag()

    # Prompt for required macOS permissions on first launch (no-op on Windows)
    request_macos_permissions()

    # Start Flask in a daemon thread
    t = threading.Thread(target=start_server)
    t.daemon = True
    t.start()

    # Wait until Flask is actually ready (not a fixed sleep)
    import urllib.request
    for _ in range(40):  # up to ~10 seconds
        try:
            urllib.request.urlopen('http://127.0.0.1:5000', timeout=0.5)
            break
        except Exception:
            time.sleep(0.25)

    # Create webview window
    global webview_window

    win_w, win_h = 900, 700
    center_x, center_y = _compute_window_center(win_w, win_h)

    webview_window = webview.create_window(
        'Auto use',
        'http://127.0.0.1:5000',
        width=win_w,
        height=win_h,
        x=center_x,
        y=center_y
    )

    # macOS needs pynput keyboard pre-initialized on the main thread
    # because Carbon APIs require the main dispatch queue.
    if IS_MAC:
        try:
            from Auto_Use.macOS_use.controller.key_combo.service import _get_keyboard
            _get_keyboard()
        except Exception:
            pass

    webview.start()

if __name__ == '__main__':
    try:
        main()
    except Exception:
        debug_exception("main entry point")
        raise
