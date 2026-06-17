# Spindle

🌀 AI-powered Linux management — just tell it what you want in plain language.

Spindle lets you manage a Linux system the way you'd explain it to a friend. Ask it to check your disks, install a package, find what's eating your CPU, or fix a broken repo — Spindle figures out the right command, runs it safely, and explains the result like you've never touched a terminal before.

Built on Claude, developed by [Petacomm](https://github.com/petacomm).

---

## Why Spindle

Most CLI tools assume you already know the command. Spindle assumes you don't — and that's fine.

- **Natural language in, plain explanation out.** Ask "why is my disk full" instead of memorizing `du -sh --max-depth=1`.
- **Confirms before anything risky.** Read-only commands run instantly; anything that modifies your system asks first, in your own language.
- **Remembers the conversation.** Reference "option B" or "do it" from a few messages ago — Spindle keeps context.
- **Runs things in parallel when it makes sense.** "Install nginx, postgres, and redis" runs all three at once with live progress.
- **Speaks your language.** Detects what language you're writing in and replies in that language — no settings to dig through.

## Installation

```bash
git clone https://github.com/petacomm/spindle.git
cd spindle
chmod +x install.sh
sudo ./install.sh
```

Then set your Claude API key (get one at [console.anthropic.com](https://console.anthropic.com)):

```bash
spindle login
```

## Usage

```bash
# Talk to it
spindle -r "why is my disk full"
spindle -r "install nginx and certbot"
spindle -r "what's using all my memory"

# Force a specific model for one request
spindle -r -opus "do a deep security audit of this system"
spindle -r -haiku "is nginx running"

# Built-in commands
spindle status          # snapshot of CPU, RAM, disk, services
spindle health           # health score with warnings/critical issues
spindle ls services       # list services and their state
spindle ls ports          # list open ports
spindle ls processes      # top processes by CPU
spindle logs nginx        # tail a service's logs
spindle logs nginx --follow

# Search and clean up files
spindle find "old-backup"

# Backups
spindle backup now
spindle restore <name>

# Conversation & config
spindle clear            # forget recent conversation
spindle config           # show or change the default model
spindle config --model opus
spindle info             # about Spindle
spindle help             # full command list
```

## How it works

Every request goes through two steps:

1. **Decide.** Spindle scans your system (CPU, RAM, disk, services, ports) and sends that snapshot plus your request to Claude, which decides whether to run a read-only command, ask for confirmation on something riskier, or just answer directly.
2. **Explain.** If a command ran, the raw output goes back to Claude, which turns it into a plain-language explanation — no jargon left unexplained.

Modifying operations (installs, restarts, deletions, config changes) always pause for a yes/no confirmation in your language before doing anything. Independent tasks that can run at the same time (like installing three unrelated packages) run in parallel with live status per task.

## Requirements

- Linux (tested on Ubuntu)
- Python 3.10+
- A Claude API key

## Models

Spindle defaults to Claude Sonnet, but you can switch per-request or permanently:

| Flag | Model |
|------|-------|
| `-s` / `-sonnet` | Claude Sonnet |
| `-o` / `-opus` | Claude Opus |
| `-h` / `-haiku` | Claude Haiku |

```bash
spindle config --model haiku   # change the default
spindle -r -opus "..."          # override for one request only
```

## License

GNU GPL v3. See [LICENSE](LICENSE).

---

Spindle™ — developed under [Petacomm](https://github.com/petacomm).
