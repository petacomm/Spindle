"""
Spindle - Claude API Integration
With conversation memory + parallel execution + model selection.
"""

import json
import os
import re
import subprocess
import threading
import time
from datetime import datetime
from pathlib import Path


CONFIG_PATH = Path.home() / ".spindle" / "config.json"
HISTORY_PATH = Path.home() / ".spindle" / "history.json"
MAX_HISTORY = 6

MODELS = {
    "sonnet": {"id": "claude-sonnet-4-5", "name": "Claude Sonnet 4.5"},
    "opus":   {"id": "claude-opus-4-6",   "name": "Claude Opus 4.6"},
    "haiku":  {"id": "claude-haiku-4-5-20251001",  "name": "Claude Haiku 4.5"},
}
DEFAULT_MODEL = "sonnet"


def load_config():
    if CONFIG_PATH.exists():
        try:
            return json.loads(CONFIG_PATH.read_text())
        except Exception:
            return {}
    return {}


def save_config(data):
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False))


def get_api_key():
    config = load_config()
    return config.get("api_key") or os.environ.get("ANTHROPIC_API_KEY")


def set_api_key(key):
    config = load_config()
    config["api_key"] = key
    save_config(config)


def get_model():
    config = load_config()
    model_key = config.get("model", DEFAULT_MODEL)
    return MODELS.get(model_key, MODELS[DEFAULT_MODEL])


def set_model(model_key):
    if model_key not in MODELS:
        return False
    config = load_config()
    config["model"] = model_key
    save_config(config)
    return True


def get_model_display_name():
    return get_model()["name"]


# ─── Conversation memory ──────────────────────────────────────────────────────

def load_history():
    if HISTORY_PATH.exists():
        try:
            data = json.loads(HISTORY_PATH.read_text())
            cutoff = time.time() - 2 * 3600
            data = [h for h in data if h.get("ts", 0) > cutoff]
            return data[-MAX_HISTORY:]
        except Exception:
            return []
    return []


def save_history_turn(request, response, command_ran=None, command_output=None):
    history = []
    if HISTORY_PATH.exists():
        try:
            history = json.loads(HISTORY_PATH.read_text())
        except Exception:
            history = []

    turn = {"ts": time.time(), "request": request, "response": response[:500]}
    if command_ran:
        turn["command_ran"] = command_ran
    if command_output:
        turn["command_output"] = command_output[:800]

    history.append(turn)
    history = history[-MAX_HISTORY * 2:]
    HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    HISTORY_PATH.write_text(json.dumps(history, indent=2, ensure_ascii=False))


def clear_history():
    if HISTORY_PATH.exists():
        HISTORY_PATH.unlink()


def _history_to_messages(history):
    messages = []
    for h in history:
        messages.append({"role": "user", "content": h["request"]})
        assistant_content = h["response"]
        if h.get("command_ran"):
            assistant_content += f"\n[Ran command: {h['command_ran']}]"
        if h.get("command_output"):
            assistant_content += f"\n[Output: {h['command_output'][:300]}]"
        messages.append({"role": "assistant", "content": assistant_content})
    return messages


# ─── Claude API ───────────────────────────────────────────────────────────────

def _call_claude(messages, system, api_key, max_tokens=1024, model_id=None):
    import urllib.request, urllib.error
    if model_id is None:
        model_id = get_model()["id"]
    payload = json.dumps({
        "model": model_id,
        "max_tokens": max_tokens,
        "system": system,
        "messages": messages,
    }).encode("utf-8")
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=payload,
        headers={"Content-Type": "application/json", "x-api-key": api_key, "anthropic-version": "2023-06-01"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return {"success": True, "text": data["content"][0]["text"]}
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8")
        try:
            msg = json.loads(body).get("error", {}).get("message", body)
        except Exception:
            msg = body
        return {"success": False, "error": f"API Error: {msg}"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def test_api_key(api_key):
    return _call_claude(
        messages=[{"role": "user", "content": "ping"}],
        system="Reply with only: pong",
        api_key=api_key,
        max_tokens=5,
    )


def _needs_sudo(cmd):
    sudo_cmds = ["apt", "apt-get", "systemctl", "service", "ufw", "iptables",
                 "certbot", "useradd", "userdel", "usermod", "chmod", "chown",
                 "mount", "umount", "reboot", "shutdown", "dpkg", "snap",
                 "add-apt-repository", "mv", "rm", "cp", "mkdir", "tee",
                 "sed", "ln", "touch"]
    first_word = cmd.strip().split()[0] if cmd.strip() else ""
    return first_word in sudo_cmds and not cmd.strip().startswith("sudo")


def _apply_sudo(cmd):
    if _needs_sudo(cmd):
        return "sudo " + cmd
    return cmd


def _get_display_env():
    """Get DISPLAY variable for GUI apps."""
    import subprocess
    env = {}
    # Try to find active display
    try:
        result = subprocess.run("w -h | awk '{print $2}' | head -1", shell=True, capture_output=True, text=True)
        tty = result.stdout.strip()
        if tty:
            result2 = subprocess.run(f"cat /proc/$(pgrep -t {tty} | head -1)/environ 2>/dev/null | tr '\0' '\n' | grep DISPLAY", shell=True, capture_output=True, text=True)
            for line in result2.stdout.splitlines():
                if line.startswith("DISPLAY="):
                    env["DISPLAY"] = line.split("=", 1)[1]
    except Exception:
        pass
    if "DISPLAY" not in env:
        env["DISPLAY"] = ":0"
    return env


def _run_command(cmd):
    try:
        env = {**__import__("os").environ, **_get_display_env()}
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=60, env=env)
        out = result.stdout.strip()
        err = result.stderr.strip()
        return out if out else err
    except subprocess.TimeoutExpired:
        return "Command timed out after 60 seconds."
    except Exception as e:
        return str(e)


def _run_command_live(cmd):
    print()
    process = subprocess.Popen(
        cmd, shell=True, stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT, text=True, bufsize=1
    )
    output_lines = []
    for line in process.stdout:
        print(f"  {line}", end="", flush=True)
        output_lines.append(line)
    process.wait()
    print()
    return "".join(output_lines)


def _run_parallel(tasks):
    import sys
    results = {}
    status = {t["name"]: "pending" for t in tasks}
    lock = threading.Lock()

    COLORS = {"pending": "\033[90m", "running": "\033[36m", "done": "\033[32m", "error": "\033[31m"}
    ICONS = {"pending": "○", "running": "⠋", "done": "✓", "error": "✗"}
    SPIN = ["⠋","⠙","⠹","⠸","⠼","⠴","⠦","⠧","⠇","⠏"]
    NC = "\033[0m"
    n = len(tasks)

    def draw(spin_frame=0):
        sys.stdout.write(f"\033[{n}A\033[J")
        for t in tasks:
            s = status[t["name"]]
            color = COLORS[s]
            icon = SPIN[spin_frame % len(SPIN)] if s == "running" else ICONS[s]
            sys.stdout.write(f"  {color}{icon} {t['name']}{NC}\n")
        sys.stdout.flush()

    for t in tasks:
        sys.stdout.write(f"  \033[90m○ {t['name']}\033[0m\n")
    sys.stdout.flush()

    def run_task(task):
        name = task["name"]
        cmd = "sudo " + task["cmd"] if not task["cmd"].strip().startswith("sudo") else task["cmd"]
        with lock:
            status[name] = "running"
        try:
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=300)
            out = result.stdout.strip() or result.stderr.strip()
            with lock:
                status[name] = "done" if result.returncode == 0 else "error"
            results[name] = {"success": result.returncode == 0, "output": out}
        except Exception as e:
            with lock:
                status[name] = "error"
            results[name] = {"success": False, "output": str(e)}

    threads = []
    for task in tasks:
        t = threading.Thread(target=run_task, args=(task,))
        t.start()
        threads.append(t)

    frame = 0
    while any(t.is_alive() for t in threads):
        time.sleep(0.1)
        with lock:
            draw(frame)
        frame += 1
    with lock:
        draw(frame)
    print()
    return results


def _build_context(system_context):
    if not system_context:
        return ""
    ram = system_context.get("ram", {})
    services = system_context.get("services", [])
    health = system_context.get("health", {})
    disks = system_context.get("disks", [])
    disk_info = ""
    for d in disks[:5]:
        disk_info += f"\n  - {d['mount']}: {d['percent']}% used"
    return f"""
Current system state:
- Hostname: {system_context.get('hostname', '?')}
- OS: {system_context.get('os', '?')}
- Kernel: {system_context.get('kernel', '?')}
- IP: {system_context.get('ip', '?')}
- Uptime: {system_context.get('uptime', '?')}
- CPU usage: {system_context.get('cpu', '?')}%
- RAM: {ram.get('percent', '?')}% ({ram.get('used', 0) // 1024 // 1024}MB of {ram.get('total', 0) // 1024 // 1024}MB)
- Disks:{disk_info}
- Running services: {', '.join(s['name'] for s in services if s.get('active')) or 'none'}
- Failed services: {', '.join(s['name'] for s in services if s.get('status') == 'failed') or 'none'}
- Health score: {health.get('score', '?')}
- Warnings: {', '.join(health.get('warnings', [])) or 'none'}
- Critical issues: {', '.join(health.get('criticals', [])) or 'none'}
"""


def _detect_language(text, api_key):
    result = _call_claude(
        messages=[{"role": "user", "content": f"What language is this text written in? Reply with only the language name in English. Text: {text}"}],
        system="You are a language detector. Reply with only the language name in English (e.g. Turkish, English, German). Nothing else.",
        api_key=api_key,
        max_tokens=10,
    )
    return result.get("text", "English").strip()


def _confirmation_words(language):
    words = {
        "Turkish": {"yes": ["evet", "e", "tamam", "ok"], "no": ["hayir", "hayır", "h", "iptal"], "prompt": "Onaylıyor musunuz? (Evet/Hayır)"},
        "English": {"yes": ["yes", "y", "ok", "sure"], "no": ["no", "n", "cancel"], "prompt": "Do you confirm? (Yes/No)"},
        "German":  {"yes": ["ja", "j", "ok"], "no": ["nein", "n"], "prompt": "Bestätigen Sie? (Ja/Nein)"},
        "French":  {"yes": ["oui", "o", "ok"], "no": ["non", "n"], "prompt": "Confirmez-vous? (Oui/Non)"},
        "Spanish": {"yes": ["si", "sí", "s", "ok"], "no": ["no", "n"], "prompt": "¿Confirma? (Sí/No)"},
    }
    return words.get(language, words["English"])


def clean_response(text):
    text = re.sub(r'SPINDLE_RUN:.*$', '', text, flags=re.MULTILINE)
    text = re.sub(r'SPINDLE_CONFIRM:.*$', '', text, flags=re.MULTILINE)
    text = re.sub(r'SPINDLE_PARALLEL:.*$', '', text, flags=re.MULTILINE)
    text = re.sub(r'<function_calls>.*?</function_calls>', '', text, flags=re.DOTALL)
    text = re.sub(r'<invoke.*?</invoke>', '', text, flags=re.DOTALL)
    text = re.sub(r'<parameter.*?</parameter>', '', text, flags=re.DOTALL)
    text = re.sub(r'^#{1,6}\s+', '', text, flags=re.MULTILINE)
    text = re.sub(r'\*{1,3}([^*\n]+)\*{1,3}', r'\1', text)
    text = re.sub(r'_{1,3}([^_\n]+)_{1,3}', r'\1', text)
    text = re.sub(r'```[a-z]*\n?', '', text)
    text = re.sub(r'```', '', text)
    text = re.sub(r'`([^`\n]+)`', r'\1', text)
    text = re.sub(r'^[-*_]{3,}\s*$', '─' * 40, text, flags=re.MULTILINE)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


def ask_claude(request, system_context=None, api_key=None):
    key = api_key or get_api_key()
    if not key:
        return {"success": False, "error": "API key not found. Run: spindle login", "response": None}

    model = get_model()
    context_str = _build_context(system_context)
    language = _detect_language(request, key)
    history = load_history()
    history_messages = _history_to_messages(history)

    turn1_system = f"""You are Spindle, an AI-powered Linux management assistant, developed under Petacomm. If asked who's behind it, you can mention Petacomm is the name the developer uses for independent projects like this one.
The user language is: {language}. You MUST respond in {language}. NON-NEGOTIABLE.
Never switch to English or any other language. Even errors, warnings, technical terms — always in {language}.

{context_str}

You have memory of recent conversation. If the user refers to something from before (like choosing option A/B/C, or "do it", "yes the second one"), use the conversation history to understand what they mean.

RULES:
1. Always respond in {language}. Never switch languages.

2. To run ANY command (including launching apps like pycharm, firefox, petamonitor), put ONLY this on the very last line:
   SPINDLE_RUN: <full shell command>
   Chain multiple commands with &&. NEVER write anything after this line.
   NEVER use function_calls, invoke, or any XML tool format. ONLY use SPINDLE_RUN.
   To launch an app, just write its name: SPINDLE_RUN: petamonitor
   For GUI apps use setsid: SPINDLE_RUN: DISPLAY=:0 setsid firefox &>/dev/null
   For snap GUI apps (pycharm, etc.) use full path: SPINDLE_RUN: DISPLAY=:0 setsid /snap/bin/pycharm &>/dev/null
   When unsure if app is snap, use: DISPLAY=:0 setsid bash -c '<app> || /snap/bin/<app>' &>/dev/null
   Figure out the app name from what the user says (e.g. "firefox'u aç" -> firefox, "pycharm aç" -> pycharm).

3. For MULTIPLE INDEPENDENT modifying tasks that can run in PARALLEL (e.g. install nginx AND mysql AND redis):
   Explain what will happen, then end with EXACTLY this on the last line:
   SPINDLE_PARALLEL: [{{"name":"nginx","cmd":"apt install -y nginx"}},{{"name":"mysql","cmd":"apt install -y mysql-server"}}]

4. For a SINGLE modifying operation:
   Explain what will happen, list risks, then end with EXACTLY this on the last line:
   SPINDLE_CONFIRM: <exact command> | DANGER: low|medium|high
   THIS IS MANDATORY for any modifying operation. Never skip it.

5. If no command needed, answer directly in {language}.
6. Explain like talking to a complete beginner. Use simple analogies.
7. If a previous command failed, remember it and suggest fixing the root cause.
8. Before saying an application is not installed, always check with: which <app> || find /snap/bin /opt /usr/local/bin -name "<app>*" 2>/dev/null
9. For GUI applications: first try wmctrl -a '<AppName>' to bring existing window to front. If not open, launch with: DISPLAY=:0 nohup /snap/bin/<app> &>/dev/null & then wmctrl -a '<AppName>'"""

    messages = history_messages + [{"role": "user", "content": request}]

    turn1 = _call_claude(
        messages=messages,
        system=turn1_system,
        api_key=key,
        max_tokens=768,
        model_id=model["id"],
    )

    if not turn1["success"]:
        return {"success": False, "error": turn1["error"], "response": None}

    turn1_text = turn1["text"].strip()
    turn1_text = re.sub(r'Onaylıyor musunuz.*$', '', turn1_text, flags=re.IGNORECASE|re.DOTALL).strip()
    turn1_text = re.sub(r'Do you confirm.*$', '', turn1_text, flags=re.IGNORECASE|re.DOTALL).strip()

    command_ran = None
    command_output = None

    run_match = re.search(r'SPINDLE_RUN:\s*(.+?)$', turn1_text, re.MULTILINE)
    confirm_match = re.search(r'SPINDLE_CONFIRM:\s*(.+?)\s*\|\s*DANGER:\s*(low|medium|high)', turn1_text, re.IGNORECASE)
    parallel_match = re.search(r'SPINDLE_PARALLEL:\s*(\[.+?\])\s*$', turn1_text, re.MULTILINE | re.DOTALL)

    if run_match:
        command_ran = run_match.group(1).strip()
        command_output = _run_command(command_ran)

    elif parallel_match:
        try:
            tasks_raw = json.loads(parallel_match.group(1))
        except Exception:
            tasks_raw = []

        if tasks_raw:
            explanation = clean_response(turn1_text[:parallel_match.start()].strip())
            conf_words = _confirmation_words(language)

            print()
            print("─" * 60)
            if explanation:
                print(explanation)
                print()
            label = f"  📦 {len(tasks_raw)} işlem paralel çalışacak:" if language == "Turkish" else f"  📦 {len(tasks_raw)} tasks will run in parallel:"
            print(label)
            for t in tasks_raw:
                print(f"     • {t['name']}")
            print()
            print(f"⚠️  {conf_words['prompt']} ", end="", flush=True)

            try:
                answer = input().strip().lower()
            except (EOFError, KeyboardInterrupt):
                print()
                return {"success": True, "response": "Cancelled.", "command_ran": None, "command_output": None, "error": None}

            if answer in conf_words["yes"]:
                print()
                parallel_results = _run_parallel(tasks_raw)
                command_ran = " && ".join(t["cmd"] for t in tasks_raw)
                command_output = "\n".join(
                    f"[{t['name']}]: {'SUCCESS' if parallel_results.get(t['name'], {}).get('success') else 'FAILED'}\n{parallel_results.get(t['name'], {}).get('output', '')}"
                    for t in tasks_raw
                )
            else:
                cancelled = {"Turkish": "İptal edildi.", "English": "Cancelled."}
                resp = cancelled.get(language, "Cancelled.")
                save_history_turn(request, resp)
                return {"success": True, "response": resp, "command_ran": None, "command_output": None, "error": None}

    elif confirm_match:
        confirm_cmd = confirm_match.group(1).strip()
        danger = confirm_match.group(2).strip()
        explanation = clean_response(turn1_text[:confirm_match.start()].strip())
        conf_words = _confirmation_words(language)
        danger_icon = {"low": "⚠️", "medium": "⚠️", "high": "🔴"}.get(danger, "⚠️")

        print()
        print("─" * 60)
        if explanation:
            print(explanation)
            print()
        print(f"{danger_icon} {conf_words['prompt']} ", end="", flush=True)

        try:
            answer = input().strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            return {"success": True, "response": "Cancelled.", "command_ran": None, "command_output": None, "error": None}

        if answer in conf_words["yes"]:
            confirm_cmd = _apply_sudo(confirm_cmd)
            command_ran = confirm_cmd
            command_output = _run_command_live(command_ran)
        else:
            cancelled = {"Turkish": "İptal edildi.", "English": "Cancelled.", "German": "Abgebrochen.", "French": "Annulé.", "Spanish": "Cancelado."}
            resp = cancelled.get(language, "Cancelled.")
            save_history_turn(request, resp)
            return {"success": True, "response": resp, "command_ran": None, "command_output": None, "error": None}

    if command_output is not None:
        turn2_system = f"""You are Spindle, an AI-powered Linux management assistant, developed under Petacomm.
The user language is: {language}. You MUST respond in {language}. NON-NEGOTIABLE.
Never switch to English or any other language.

{context_str}

You just ran: {command_ran}
Raw output:
---
{command_output}
---

RULES:
1. Respond ONLY in {language}. Never use English.
2. Explain as if talking to a complete beginner who never used Linux.
3. Replace ALL technical terms with simple analogies.
4. Use ✅ for good, ⚠️ for warning, ❌ for problem.
5. Show sizes in human readable format (GB, MB).
6. If there is a problem, give simple next steps.
7. No markdown — no ##, no **, no backticks. Plain text only."""

        msg2 = [
            {"role": "user", "content": request},
            {"role": "assistant", "content": turn1_text},
            {"role": "user", "content": f"Command output:\n{command_output}"},
        ]
        turn2 = _call_claude(messages=msg2, system=turn2_system, api_key=key, max_tokens=1024, model_id=model["id"])

        if not turn2["success"]:
            return {"success": False, "error": turn2["error"], "response": None}

        final_resp = clean_response(turn2["text"])
        save_history_turn(request, final_resp, command_ran, command_output)
        return {"success": True, "response": final_resp, "command_ran": command_ran, "command_output": command_output, "error": None, "model": model["name"]}

    final_resp = clean_response(turn1_text)
    save_history_turn(request, final_resp)
    return {"success": True, "response": final_resp, "command_ran": None, "command_output": None, "error": None, "model": model["name"]}
