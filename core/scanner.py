"""
Spindle - Sistem Tarayıcısı
Sunucunun anlık durumunu okur.
"""

import os
import re
import shutil
import socket
import subprocess
from datetime import datetime
from pathlib import Path


def run(cmd: str) -> str:
    """Komutu çalıştır, çıktıyı döndür."""
    try:
        result = subprocess.run(
            cmd, shell=True, capture_output=True, text=True, timeout=10
        )
        return result.stdout.strip()
    except Exception:
        return ""


def get_cpu_usage() -> float:
    try:
        import psutil
        return psutil.cpu_percent(interval=0.5)
    except ImportError:
        out = run("top -bn1 | grep 'Cpu(s)'")
        match = re.search(r"(\d+\.\d+)\s+id", out)
        if match:
            return round(100 - float(match.group(1)), 1)
        return 0.0


def get_ram() -> dict:
    try:
        import psutil
        m = psutil.virtual_memory()
        return {
            "total": m.total,
            "used": m.used,
            "free": m.available,
            "percent": m.percent,
        }
    except ImportError:
        out = run("free -b")
        lines = out.splitlines()
        if len(lines) > 1:
            parts = lines[1].split()
            total = int(parts[1])
            used = int(parts[2])
            free = int(parts[3])
            return {
                "total": total,
                "used": used,
                "free": free,
                "percent": round(used / total * 100, 1) if total else 0,
            }
        return {"total": 0, "used": 0, "free": 0, "percent": 0}


def get_disks() -> list:
    try:
        import psutil
        disks = []
        for part in psutil.disk_partitions():
            if part.mountpoint.startswith("/snap") or part.mountpoint.startswith("/var/lib/snapd"):
                continue
            if part.fstype in ("squashfs", "tmpfs", "devtmpfs", "overlay"):
                continue
            try:
                usage = psutil.disk_usage(part.mountpoint)
                disks.append({
                    "mount": part.mountpoint,
                    "total": usage.total,
                    "used": usage.used,
                    "free": usage.free,
                    "percent": usage.percent,
                    "fs": part.fstype,
                })
            except Exception:
                continue
        return disks
    except ImportError:
        out = run("df -B1 --output=target,size,used,avail,pcent,fstype")
        disks = []
        for line in out.splitlines()[1:]:
            parts = line.split()
            if len(parts) >= 6:
                disks.append({
                    "mount": parts[0],
                    "total": int(parts[1]),
                    "used": int(parts[2]),
                    "free": int(parts[3]),
                    "percent": float(parts[4].replace("%", "")),
                    "fs": parts[5],
                })
        return disks


def get_uptime() -> str:
    out = run("uptime -p")
    return out.replace("up ", "") if out else "bilinmiyor"


def get_hostname() -> str:
    return socket.gethostname()


def get_os() -> str:
    for f in ["/etc/os-release", "/etc/lsb-release"]:
        if Path(f).exists():
            content = Path(f).read_text()
            match = re.search(r'PRETTY_NAME="(.+)"', content)
            if match:
                return match.group(1)
    return run("uname -s -r")


def get_kernel() -> str:
    return run("uname -r")


def get_load() -> str:
    return run("cat /proc/loadavg").split()[:3]


def get_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "bilinmiyor"


def get_services() -> list:
    """Yaygın servislerin durumunu kontrol et."""
    common = [
        "nginx", "apache2", "mysql", "mariadb", "postgresql",
        "redis", "mongodb", "ssh", "ufw", "fail2ban",
        "docker", "cron", "postfix", "php-fpm",
    ]
    services = []
    for svc in common:
        out = run(f"systemctl is-active {svc} 2>/dev/null")
        if out in ("active", "inactive", "failed"):
            services.append({
                "name": svc,
                "status": out,
                "active": out == "active",
            })
    return services


def get_open_ports() -> list:
    out = run("ss -tlnp 2>/dev/null || netstat -tlnp 2>/dev/null")
    ports = []
    for line in out.splitlines()[1:]:
        parts = line.split()
        if len(parts) < 4:
            continue
        addr = parts[3] if "ss" in run("which ss") else parts[3]
        port_match = re.search(r":(\d+)$", addr)
        if port_match:
            port = int(port_match.group(1))
            # servis adını bul
            svc = run(f"grep -w {port} /etc/services 2>/dev/null | head -1 | awk '{{print $1}}'")
            ports.append({"port": port, "service": svc or "?"})
    return sorted(ports, key=lambda x: x["port"])


def get_logged_users() -> list:
    out = run("who")
    users = []
    for line in out.splitlines():
        parts = line.split()
        if parts:
            users.append({
                "user": parts[0],
                "tty": parts[1] if len(parts) > 1 else "",
                "from": parts[4] if len(parts) > 4 else "lokal",
            })

    if not users:
        out2 = run("loginctl list-sessions --no-legend")
        for line in out2.splitlines():
            parts = line.split()
            if len(parts) >= 3:
                users.append({"user": parts[2], "tty": parts[3] if len(parts) > 3 else "", "from": "lokal"})
    return users


def get_last_logins(n=5) -> list:
    out = run(f"last -n {n} --time-format iso 2>/dev/null || last -n {n}")
    logins = []
    for line in out.splitlines():
        if line and not line.startswith("wtmp"):
            logins.append(line.strip())
    return logins[:n]


def fmt_bytes(b: int) -> str:
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if b < 1024:
            return f"{b:.1f} {unit}"
        b /= 1024
    return f"{b:.1f} PB"


def health_score(cpu: float, ram: dict, disks: list, services: list) -> dict:
    """0-100 arası sağlık skoru hesapla."""
    score = 100
    warnings = []
    criticals = []

    # CPU
    if cpu > 90:
        score -= 20
        criticals.append(f"CPU çok yüksek: %{cpu}")
    elif cpu > 70:
        score -= 10
        warnings.append(f"CPU yüksek: %{cpu}")

    # RAM
    if ram["percent"] > 90:
        score -= 20
        criticals.append(f"RAM kritik: %{ram['percent']}")
    elif ram["percent"] > 75:
        score -= 10
        warnings.append(f"RAM yüksek: %{ram['percent']}")

    # Disk
    for disk in disks:
        if disk["percent"] > 90:
            score -= 15
            criticals.append(f"Disk dolu: {disk['mount']} %{disk['percent']}")
        elif disk["percent"] > 75:
            score -= 5
            warnings.append(f"Disk dolmak üzere: {disk['mount']} %{disk['percent']}")

    # Failed servisler
    failed = [s for s in services if s["status"] == "failed"]
    if failed:
        score -= len(failed) * 10
        criticals.append(f"Servis hatası: {', '.join(s['name'] for s in failed)}")

    score = max(0, score)

    if score >= 80:
        level = "good"
        color = "green"
    elif score >= 60:
        level = "warning"
        color = "yellow"
    else:
        level = "critical"
        color = "red"

    return {
        "score": score,
        "level": level,
        "color": color,
        "warnings": warnings,
        "criticals": criticals,
    }


def full_scan() -> dict:
    """Tam sistem taraması yap."""
    cpu = get_cpu_usage()
    ram = get_ram()
    disks = get_disks()
    services = get_services()

    return {
        "hostname": get_hostname(),
        "os": get_os(),
        "kernel": get_kernel(),
        "ip": get_ip(),
        "uptime": get_uptime(),
        "load": get_load(),
        "cpu": cpu,
        "ram": ram,
        "disks": disks,
        "services": services,
        "ports": get_open_ports(),
        "users": get_logged_users(),
        "health": health_score(cpu, ram, disks, services),
        "scanned_at": datetime.now().strftime("%d %b %Y %H:%M:%S"),
    }
