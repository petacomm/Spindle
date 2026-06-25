#!/usr/bin/env python3
"""
Spindle - Linux Management Tool
Usage:
    spindle status                    -> System status
    spindle health                    -> Health score
    spindle ls services               -> List services
    spindle config --model modelname (ex: spindle config --model opus) -> Configure LLM model
    spindle ls ports                  -> Open ports
    spindle ls backups                -> List backups
    spindle ls processes              -> List processes
    spindle -r "your request"         -> Ask AI
    spindle find "keyword"            -> Find and delete files
    spindle backup now                -> Take backup now
    spindle restore <name>            -> Restore backup
    spindle login                     -> Set API key
"""

import sys
import os
import re
import getpass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from core import scanner, executor, claude_api, backup
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.prompt import Prompt, Confirm
from rich import box
from rich.columns import Columns
from rich.progress import Progress, SpinnerColumn, TextColumn

console = Console()


def print_response_panel(text, title=""):
    """Show response in a panel if terminal is wide enough, otherwise plain text."""
    width = console.size.width
    if width < 90:
        if title:
            console.print(f"[cyan bold]{title}[/]")
            console.print()
        console.print(text)
    else:
        console.print(Panel(
            text,
            title=f"[cyan]{title}[/]" if title else None,
            border_style="cyan",
            padding=(1, 2),
            width=min(width - 4, 120),
        ))


# ─── Helpers ─────────────────────────────────────────────────────────────────

def risk_color(level: str) -> str:
    return {"green": "bright_green", "yellow": "yellow", "red": "red"}.get(level, "white")

def pct_color(pct: float) -> str:
    if pct >= 90: return "red"
    if pct >= 75: return "yellow"
    return "bright_green"

def bar(pct: float, width: int = 20) -> str:
    filled = int(pct / 100 * width)
    color = pct_color(pct)
    bar_str = "█" * filled + "░" * (width - filled)
    return f"[{color}]{bar_str}[/] [dim]{pct:.1f}%[/]"

def status_icon(active: bool, status: str = "") -> str:
    if status == "failed": return "[red]✗[/]"
    if active: return "[bright_green]●[/]"
    return "[dim]○[/]"


# ─── Commands ─────────────────────────────────────────────────────────────────

def cmd_status():
    with Progress(SpinnerColumn(), TextColumn("[cyan]Scanning system..."), transient=True) as p:
        p.add_task("")
        data = scanner.full_scan()

    h = data["health"]
    score_color = {"good": "bright_green", "warning": "yellow", "critical": "red"}.get(h["level"], "white")

    console.print()
    console.print(Panel(
        f"[bold cyan]Spindle[/] — Linux Management Tool\n"
        f"[dim]{data['scanned_at']}[/]",
        border_style="cyan", padding=(0, 2)
    ))

    info = Table(box=None, show_header=False, padding=(0, 2))
    info.add_column(style="dim", width=16)
    info.add_column()
    info.add_row("Hostname", f"[bold]{data['hostname']}[/]")
    info.add_row("IP", data["ip"])
    info.add_row("OS", data["os"])
    info.add_row("Kernel", data["kernel"])
    info.add_row("Uptime", data["uptime"])
    load = data.get("load", ["-", "-", "-"])
    info.add_row("Load Avg", f"{' '.join(load)}")

    score_panel = Panel(
        f"\n[{score_color} bold]{h['score']}[/][dim]/100[/]\n\n[{score_color}]{h['level'].upper()}[/]\n",
        title="Health Score", border_style=score_color, width=20
    )

    console.print(Columns([info, score_panel]))

    console.print()
    console.print("[bold]Resources[/]")
    res = Table(box=box.SIMPLE, show_header=False, padding=(0, 1))
    res.add_column(style="dim", width=6)
    res.add_column(width=30)
    res.add_column()
    res.add_row("CPU", bar(data["cpu"]), f"[dim]{data['cpu']:.1f}%[/]")
    ram = data["ram"]
    res.add_row("RAM", bar(ram["percent"]),
                f"[dim]{scanner.fmt_bytes(ram['used'])} / {scanner.fmt_bytes(ram['total'])}[/]")
    for disk in data["disks"][:3]:
        res.add_row(disk["mount"][:6], bar(disk["percent"]),
                    f"[dim]{scanner.fmt_bytes(disk['used'])} / {scanner.fmt_bytes(disk['total'])}[/]")
    console.print(res)

    if h["criticals"]:
        console.print()
        for c in h["criticals"]:
            console.print(f"  [red]🔴 {c}[/]")
    if h["warnings"]:
        for w in h["warnings"]:
            console.print(f"  [yellow]🟡 {w}[/]")

    active_svcs = [s for s in data["services"] if s["active"]]
    failed_svcs = [s for s in data["services"] if s["status"] == "failed"]
    console.print()
    console.print(
        f"[dim]Services:[/] "
        f"[bright_green]{len(active_svcs)} running[/]"
        + (f"  [red]{len(failed_svcs)} failed[/]" if failed_svcs else "")
    )
    console.print()


def cmd_health():
    with Progress(SpinnerColumn(), TextColumn("[cyan]Analyzing..."), transient=True) as p:
        p.add_task("")
        data = scanner.full_scan()

    h = data["health"]
    score_color = {"good": "bright_green", "warning": "yellow", "critical": "red"}.get(h["level"], "white")

    console.print()
    console.print(Panel(
        f"[{score_color} bold]Health Score: {h['score']}/100 — {h['level'].upper()}[/]",
        border_style=score_color
    ))

    if not h["criticals"] and not h["warnings"]:
        console.print("[bright_green]✓ System looks healthy, no issues detected.[/]")
    else:
        if h["criticals"]:
            console.print("\n[bold red]Critical Issues:[/]")
            for c in h["criticals"]:
                console.print(f"  🔴 {c}")
        if h["warnings"]:
            console.print("\n[bold yellow]Warnings:[/]")
            for w in h["warnings"]:
                console.print(f"  🟡 {w}")
    console.print()


def cmd_ls(target: str):
    if target in ("services", "service"):
        with Progress(SpinnerColumn(), TextColumn("[cyan]Scanning services..."), transient=True) as p:
            p.add_task("")
            services = scanner.get_services()

        console.print()
        t = Table(title="Services", box=box.ROUNDED, border_style="cyan")
        t.add_column("", width=4)
        t.add_column("Service", style="bold")
        t.add_column("Status", width=12)
        for s in services:
            t.add_row(
                status_icon(s["active"], s["status"]),
                s["name"],
                f"[bright_green]{s['status']}[/]" if s["active"] else
                f"[red]{s['status']}[/]" if s["status"] == "failed" else
                f"[dim]{s['status']}[/]"
            )
        console.print(t)

    elif target in ("ports", "port"):
        with Progress(SpinnerColumn(), TextColumn("[cyan]Scanning ports..."), transient=True) as p:
            p.add_task("")
            ports = scanner.get_open_ports()

        console.print()
        t = Table(title="Open Ports", box=box.ROUNDED, border_style="cyan")
        t.add_column("Port", style="yellow", width=8)
        t.add_column("Service")
        for p in ports:
            t.add_row(str(p["port"]), p["service"] or "—")
        console.print(t)

    elif target in ("backups", "backup"):
        backups = backup.list_backups()
        console.print()
        if not backups:
            console.print("[dim]No backups yet.[/]")
            return
        t = Table(title="Backups", box=box.ROUNDED, border_style="cyan")
        t.add_column("#", width=4, style="dim")
        t.add_column("Name")
        t.add_column("Date", style="dim")
        t.add_column("Files", width=7, justify="right")
        t.add_column("Size", width=10, justify="right")
        for i, b in enumerate(backups, 1):
            t.add_row(str(i), b["name"], b["created_at"], str(b["files"]), b["size"])
        console.print(t)

    elif target in ("processes", "process", "ps"):
        with Progress(SpinnerColumn(), TextColumn("[cyan]Getting processes..."), transient=True) as p:
            p.add_task("")
            out = executor.run_command("ps aux --sort=-%cpu | head -20")

        console.print()
        console.print(Panel(out["output"], title="Top 20 Processes", border_style="cyan"))

    else:
        console.print(f"[yellow]Unknown target: {target}[/]")
        console.print("[dim]Available: services, ports, backups, processes[/]")


def cmd_logs(target: str, follow: bool = False):
    log_map = {
        "nginx": "/var/log/nginx/error.log",
        "apache": "/var/log/apache2/error.log",
        "mysql": "/var/log/mysql/error.log",
        "system": "/var/log/syslog",
        "auth": "/var/log/auth.log",
        "kern": "/var/log/kern.log",
    }
    log_file = log_map.get(target, f"/var/log/{target}.log")

    if follow:
        console.print(f"[dim]Live log: {log_file} (Ctrl+C to exit)[/]")
        os.execlp("tail", "tail", "-f", log_file)
    else:
        out = executor.run_command(f"tail -50 {log_file}")
        if out["success"]:
            console.print(Panel(out["output"], title=f"Log: {log_file}", border_style="cyan"))
        else:
            console.print(f"[red]Cannot read log: {log_file}[/]")


def cmd_find(query: str):
    console.print()
    with Progress(SpinnerColumn(), TextColumn(f"[cyan]Searching '{query}'..."), transient=True) as p:
        p.add_task("")
        results = executor.find_files(query)

    if not results:
        console.print(f"[dim]No files found matching '{query}'.[/]")
        return

    t = Table(box=box.SIMPLE, show_header=True)
    t.add_column("#", width=4, style="dim")
    t.add_column("Type", width=7)
    t.add_column("Path")
    t.add_column("Size", width=10, justify="right", style="dim")

    for r in results:
        icon = "📁" if r["is_dir"] else "📄"
        t.add_row(str(r["num"]), icon + " " + r["type"], r["path"], r["size_fmt"])

    console.print(t)
    console.print(f"[dim]{len(results)} results found.[/]")
    console.print()

    console.print("[dim]Type which to delete (e.g: delete 1,2,3) or Enter to exit:[/]")
    choice = Prompt.ask("", default="")

    if not choice.lower().startswith("delete"):
        return

    nums_str = choice.lower().replace("delete", "").strip()
    try:
        nums = [int(n.strip()) for n in nums_str.split(",") if n.strip().isdigit()]
    except Exception:
        console.print("[red]Invalid format.[/]")
        return

    selected = [r for r in results if r["num"] in nums]
    if not selected:
        console.print("[dim]No items selected.[/]")
        return

    console.print()
    console.print("[bold]Will be deleted:[/]")
    total_size = 0
    for item in selected:
        risk = executor.risk_check(f"rm {'-rf' if item['is_dir'] else ''} {item['path']}")
        color = risk_color(risk["level"])
        console.print(f"  [{color}]{'🔴' if risk['level'] == 'red' else '🟡' if risk['level'] == 'yellow' else '🟢'}[/] {item['path']}  [dim]{item['size_fmt']}[/]")
        total_size += item["size"]

    console.print(f"\n[dim]Total: {executor.fmt_size(total_size)}[/]")
    console.print()
    console.print("[bold]Are you sure?[/]")
    console.print("  [bright_green]Y[/]  → Delete")
    console.print("  [red]N[/]  → Cancel")
    console.print("  [cyan]B[/]  → Backup then delete")
    console.print()

    ans = Prompt.ask("Choice", choices=["Y", "y", "N", "n", "B", "b"], default="N")

    if ans.upper() == "N":
        console.print("[dim]Cancelled.[/]")
        return

    backup_dir = None
    if ans.upper() == "B":
        with Progress(SpinnerColumn(), TextColumn("[cyan]Backing up..."), transient=True) as p:
            p.add_task("")
            bk = backup.create_backup([r["path"] for r in selected], label=query)
        if bk["success"]:
            console.print(f"[bright_green]✓ Backup saved → {bk['backup_path']}[/]")
            backup_dir = bk["backup_path"]
        else:
            console.print("[red]Backup failed! Delete cancelled.[/]")
            return

    console.print()
    result = executor.delete_items(selected, backup_dir)

    for path in result["success"]:
        console.print(f"[bright_green]✓[/] {path}")
    for fail in result["failed"]:
        console.print(f"[red]✗[/] {fail['path']} — {fail['error']}")

    if result["success"]:
        console.print(f"\n[bright_green]✓ {len(result['success'])} items deleted.[/]")
        if backup_dir:
            console.print(f"[dim]To restore: spindle restore {Path(backup_dir).name}[/]")


def cmd_request(request: str, dry_run: bool = False, one_time_model: str = None):
    """Send a natural language request to Claude AI."""
    api_key = claude_api.get_api_key()
    if not api_key:
        console.print("[yellow]No API key found. Run: spindle login[/]")
        return

    # Test API key first
    with Progress(SpinnerColumn(), TextColumn("[cyan]Connecting to AI..."), transient=True) as p:
        p.add_task("")
        test = claude_api.test_api_key(api_key)

    if not test["success"]:
        console.print(f"[red]API key error: {test['error']}[/]")
        console.print("[dim]Run 'spindle login' to update your API key.[/]")
        return

    # Scan system
    with Progress(SpinnerColumn(), TextColumn("[cyan]Scanning system..."), transient=True) as p:
        p.add_task("")
        sys_data = scanner.full_scan()

    if one_time_model:
        original_model = claude_api.load_config().get("model", "sonnet")
        claude_api.set_model(one_time_model)
    model_name = claude_api.get_model_display_name()
    print(f"\033[36m⠿ Working on it... [{model_name}]\033[0m")
    result = claude_api.ask_claude(request, system_context=sys_data, api_key=api_key)
    if one_time_model:
        claude_api.set_model(original_model)

    if not result["success"]:
        console.print(f"[red]Error: {result['error']}[/]")
        return

    console.print()

    if result.get("command_ran"):
        console.print(f"[dim]▸ Ran:[/] [yellow]{result['command_ran']}[/]")
        console.print()

    print_response_panel(result["response"], title=f"Spindle Response — {request[:50]}")

    if dry_run:
        console.print("[dim][DRY RUN — Nothing was executed][/]")

    console.print()


def cmd_backup(action: str, target: str = ""):
    if action in ("now", "create"):
        paths = [target] if target else [str(Path.home())]
        with Progress(SpinnerColumn(), TextColumn("[cyan]Backing up..."), transient=True) as p:
            p.add_task("")
            result = backup.create_backup(paths, label=target or "manual")

        if result["success"]:
            console.print(f"[bright_green]✓ Backup saved → {result['backup_path']}[/]")
        else:
            console.print("[red]Backup failed.[/]")
    else:
        console.print(f"[yellow]Unknown backup command: {action}[/]")


def cmd_restore(name: str):
    backups = backup.list_backups()
    names = [b["name"] for b in backups]

    if name not in names:
        console.print(f"[red]Backup not found: {name}[/]")
        console.print("[dim]Available backups: spindle ls backups[/]")
        return

    if not Confirm.ask(f"Restore backup '{name}'?"):
        return

    with Progress(SpinnerColumn(), TextColumn("[cyan]Restoring..."), transient=True) as p:
        p.add_task("")
        result = backup.restore_backup(name)

    if result["success"]:
        for r in result["restored"]:
            console.print(f"[bright_green]✓[/] {r}")
        console.print(f"\n[bright_green]✓ Restore complete.[/]")
    else:
        console.print(f"[red]Error: {result.get('error', 'Unknown error')}[/]")


def cmd_login():
    console.print()
    console.print(Panel(
        "[bold]Claude API Key Setup[/]\n\n"
        "Get your API key at:\n"
        "  [cyan]https://console.anthropic.com[/]\n\n"
        "[dim]Key is saved to ~/.spindle/config.json[/]",
        border_style="cyan"
    ))
    console.print()

    key = getpass.getpass("API Key (sk-ant-...): ")
    if not key.startswith("sk-"):
        console.print("[yellow]Warning: Unusual format, but saving anyway.[/]")

    # Test the key
    console.print("[dim]Testing API key...[/]")
    test = claude_api.test_api_key(key.strip())
    if test["success"]:
        claude_api.set_api_key(key.strip())
        console.print("[bright_green]✓ API key is valid and saved.[/]")
    else:
        console.print(f"[red]API key test failed: {test['error']}[/]")
        console.print("[yellow]Key not saved. Please check and try again.[/]")
    console.print()


def cmd_config(args):
    """Show or change configuration."""
    from core.claude_api import get_model, set_model, MODELS, get_api_key

    if not args:
        # Show current config
        model = get_model()
        api_key = get_api_key()
        console.print()
        console.print(Panel(
            f"[bold]Current Configuration[/]\n\n"
            f"[dim]Model:[/]    [cyan]{model['name']}[/]\n"
            f"[dim]API Key:[/]  [green]{'✓ Set' if api_key else '✗ Not set'}[/]\n",
            border_style="cyan", title="spindle config"
        ))
        console.print("[dim]Available models:[/]")
        for key, m in MODELS.items():
            marker = " ← current" if m["id"] == model["id"] else ""
            console.print(f"  [yellow]{key}[/]  {m['name']}{marker}")
        console.print()
        console.print("[dim]Usage: spindle config --model sonnet|opus|haiku[/]")
        console.print()
        return

    if "--model" in args:
        idx = args.index("--model")
        if idx + 1 < len(args):
            model_key = args[idx + 1].lower()
            if set_model(model_key):
                model = get_model()
                console.print(f"[bright_green]✓ Model changed to: {model['name']}[/]")
            else:
                console.print(f"[red]Unknown model: {model_key}[/]")
                console.print("[dim]Available: sonnet, opus, haiku[/]")
        else:
            console.print("[red]Usage: spindle config --model sonnet|opus|haiku[/]")

    elif "--show" in args:
        cmd_config([])


def cmd_info():
    width = console.size.width
    console.print()
    if width < 90:
        console.print("[bold cyan]Spindle™[/]")
        console.print()
        console.print("[dim]Developed and maintained by[/] [bold]Petacomm[/]")
        console.print("[dim]Copyright (c) 2026 Kuzey ÖZDEMİR (Petacomm)[/]")
        console.print()
        console.print("[dim]GNU GPL v3 License.[/]")
        console.print("[dim]github.com/petacomm/spindle[/]")
    else:
        console.print(Panel(
            "[bold cyan]Spindle™[/]\n\n"
            "[dim]Developed and maintained by[/] [bold]Petacomm[/]\n"
            "[dim]Copyright (c) 2026 Kuzey ÖZDEMİR (Petacomm)[/]\n\n"
            "[dim]Released under the GNU GPL v3 License.[/]\n\n"
            "[dim]https://github.com/petacomm/spindle[/]",
            border_style="cyan", padding=(1, 2), width=min(width - 4, 70)
        ))
    console.print()


def cmd_help():
    console.print()
    console.print(Panel(
        "[bold cyan]Spindle[/] — Linux Management Tool\n\n"
        "[bold]Commands:[/]\n"
        "  [yellow]spindle status[/]                   System status\n"
        "  [yellow]spindle health[/]                   Health score\n"
        "  [yellow]spindle ls services[/]              List services\n"
        "  [yellow]spindle ls ports[/]                 List open ports\n"
        "  [yellow]spindle ls backups[/]               List backups\n"
        "  [yellow]spindle ls processes[/]             List processes\n"
        "  [yellow]spindle logs nginx[/]               Show nginx logs\n"
        "  [yellow]spindle logs nginx --follow[/]      Live log stream\n"
        "  [yellow]spindle find \"keyword\"[/]           Find and delete files\n"
        "  [yellow]spindle backup now[/]               Take backup now\n"
        "  [yellow]spindle restore <name>[/]           Restore a backup\n"
        "  [yellow]spindle -r \"your request\"[/]        Ask AI (Claude)\n"
        "  [yellow]spindle -r -m \"your request\"[/]     Ask AI and configure model for one time (Claude)\n"
        "  [yellow]spindle --dry-run -r \"..\"[/]        Simulate, don't run\n"
        "  [yellow]spindle login[/]                    Set API key\n"
        "  [yellow]spindle help[/]                     This help\n"
        "  [yellow]spindle clear[/]                    Clear conservation memory\n"
        "  [yellow]spindle config[/]                   Monitor available models\n"
        "  [yellow]spindle config --model modelname[/] Configure LLM model (ex: spindle config --model haiku)\n",
        border_style="cyan", padding=(1, 2)
    ))


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    args = sys.argv[1:]

    if not args:
        cmd_help()
        return

    dry_run = "--dry-run" in args
    args = [a for a in args if a != "--dry-run"]

    cmd = args[0]

    if cmd == "-r":
        remaining = args[1:]
        # Check for one-time model override
        one_time_model = None
        model_flags = {
            "-opus": "opus", "-o": "opus",
            "-sonnet": "sonnet", "-s": "sonnet",
            "-haiku": "haiku", "-h": "haiku",
        }
        for flag, model_key in model_flags.items():
            if remaining and remaining[0] == flag:
                one_time_model = model_key
                remaining = remaining[1:]
                break
        request = " ".join(remaining)
        if not request:
            console.print("[red]Error: Empty request.[/]")
            console.print("[dim]Example: spindle -r \"why is nginx not running\"[/]")
            return
        cmd_request(request, dry_run=dry_run, one_time_model=one_time_model)

    elif cmd == "status":
        cmd_status()

    elif cmd == "health":
        cmd_health()

    elif cmd == "ls":
        target = args[1] if len(args) > 1 else ""
        if not target:
            console.print("[yellow]What to list?[/]")
            console.print("[dim]Example: spindle ls services[/]")
        else:
            cmd_ls(target)

    elif cmd == "logs":
        target = args[1] if len(args) > 1 else "system"
        follow = "--follow" in args or "-f" in args
        cmd_logs(target, follow=follow)

    elif cmd == "find":
        query = " ".join(args[1:])
        if not query:
            console.print("[red]Error: Search term required.[/]")
            console.print("[dim]Example: spindle find \"gatebell\"[/]")
        else:
            cmd_find(query)

    elif cmd == "backup":
        action = args[1] if len(args) > 1 else "now"
        target = args[2] if len(args) > 2 else ""
        cmd_backup(action, target)

    elif cmd == "restore":
        name = args[1] if len(args) > 1 else ""
        if not name:
            console.print("[red]Error: Backup name required.[/]")
            console.print("[dim]Example: spindle restore 2026-04-17_09-22-00[/]")
        else:
            cmd_restore(name)

    elif cmd == "clear":
        claude_api.clear_history()
        console.print("[bright_green]✓ Conversation cleared.[/]")

    elif cmd == "login":
        cmd_login()

    elif cmd == "info":
        cmd_info()

    elif cmd == "config":
        cmd_config(args[1:] if len(args) > 1 else [])

    elif cmd in ("help", "--help", "-h"):
        cmd_help()

    else:
        console.print(f"[yellow]Unknown command: {cmd}[/]")
        console.print("[dim]For help: spindle help[/]")


if __name__ == "__main__":
    main()
