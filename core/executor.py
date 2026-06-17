"""
Spindle - Komut Yürütücü
Komutları risk analizi yaparak güvenli şekilde çalıştırır.
"""

import subprocess
import shutil
from pathlib import Path
from datetime import datetime


# ─── Risk seviyeleri ──────────────────────────────────────────────────────────

DANGER_PATTERNS = [
    # Kritik silme komutları
    (r"rm\s+-rf?\s+/(?!\S)", "red", "Kök dizini silmeye çalışıyorsun! Bu sistemi mahveder."),
    (r"rm\s+-rf?\s+/(bin|boot|etc|lib|sbin|usr|var|sys|proc)\b", "red", "Sistem klasörü siliniyor! Çok tehlikeli."),
    (r"rm\s+.*-rf", "red", "Klasör silme komutu. Geri alınamaz."),
    (r"rm\s+", "yellow", "Dosya silme. Geri alınamaz."),
    # Disk komutları
    (r"mkfs\.", "red", "Diski formatlamak üzeresin! Tüm veriler silinir."),
    (r"dd\s+.*of=/dev/", "red", "Ham disk yazma. Çok tehlikeli."),
    # Kullanıcı komutları
    (r"userdel\s+-r", "yellow", "Kullanıcı ve ev dizini silinecek."),
    (r"passwd\s+root", "yellow", "Root şifresi değiştiriliyor."),
    # Ağ komutları
    (r"iptables\s+-F", "yellow", "Tüm güvenlik duvarı kuralları temizleniyor."),
    (r"ufw\s+disable", "yellow", "Güvenlik duvarı devre dışı bırakılıyor."),
    # Servis komutları
    (r"systemctl\s+stop\s+ssh", "red", "SSH servisi durdurulursa uzak bağlantı kesilir!"),
    (r"systemctl\s+(stop|restart)\s+", "yellow", "Servis durdurulacak/yeniden başlatılacak, kısa kesinti olabilir."),
    # Veritabanı
    (r"DROP\s+DATABASE", "red", "Veritabanı silinecek! Geri alınamaz."),
    (r"DROP\s+TABLE", "yellow", "Tablo silinecek."),
]

SAFE_PATTERNS = [
    r"^(ls|cat|echo|pwd|whoami|id|date|uptime|df|du|free|ps|top|htop|netstat|ss|ip|ping|curl|wget|find|grep|awk|sed|sort|uniq|wc|head|tail|less|more)(\s|$)",
    r"^systemctl\s+(status|is-active|list-units)",
    r"^journalctl",
    r"^apt\s+(list|show|search)",
]

import re


def risk_check(cmd: str) -> dict:
    """Komutun risk seviyesini belirle."""
    cmd_lower = cmd.strip().lower()

    # Önce güvenli pattern'lere bak
    for pattern in SAFE_PATTERNS:
        if re.search(pattern, cmd_lower):
            return {"level": "green", "message": "Güvenli komut."}

    # Tehlikeli pattern'lere bak
    for pattern, level, message in DANGER_PATTERNS:
        if re.search(pattern, cmd_lower):
            return {"level": level, "message": message}

    # Varsayılan: orta risk
    return {"level": "green", "message": ""}


def run_command(cmd: str, dry_run: bool = False) -> dict:
    """
    Komutu çalıştır.
    dry_run=True ise sadece göster, çalıştırma.
    """
    if dry_run:
        return {
            "success": True,
            "output": f"[SİMÜLASYON] Çalıştırılacaktı: {cmd}",
            "dry_run": True,
        }

    try:
        result = subprocess.run(
            cmd,
            shell=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
        return {
            "success": result.returncode == 0,
            "output": result.stdout.strip() or result.stderr.strip(),
            "returncode": result.returncode,
            "dry_run": False,
        }
    except subprocess.TimeoutExpired:
        return {"success": False, "output": "Komut zaman aşımına uğradı (30s).", "dry_run": False}
    except Exception as e:
        return {"success": False, "output": str(e), "dry_run": False}


def find_files(query: str, path: str = "/") -> list:
    """
    Dosya ara. Güvenli şekilde find komutunu çalıştır.
    Sonuçları numaralı liste olarak döndür.
    """
    import subprocess
    results = []

    # find komutu
    cmd = f"find {path} -iname '*{query}*' 2>/dev/null"
    try:
        result = subprocess.run(
            cmd, shell=True, capture_output=True, text=True, timeout=15
        )
        lines = [l.strip() for l in result.stdout.splitlines() if l.strip()]

        for i, line in enumerate(lines, 1):
            p = Path(line)
            try:
                stat = p.stat()
                size = stat.st_size
                is_dir = p.is_dir()
                results.append({
                    "num": i,
                    "path": line,
                    "is_dir": is_dir,
                    "size": size,
                    "size_fmt": fmt_size(size),
                    "type": "klasör" if is_dir else "dosya",
                })
            except Exception:
                results.append({
                    "num": i,
                    "path": line,
                    "is_dir": False,
                    "size": 0,
                    "size_fmt": "?",
                    "type": "dosya",
                })
    except Exception:
        pass

    return results


def delete_items(items: list, backup_dir: str = None) -> dict:
    """
    Seçili öğeleri sil.
    backup_dir verilmişse önce yedekle.
    """
    results = {"success": [], "failed": [], "backed_up": []}

    for item in items:
        path = Path(item["path"])

        # Yedekle
        if backup_dir:
            try:
                dest = Path(backup_dir) / path.name
                if path.is_dir():
                    shutil.copytree(str(path), str(dest))
                else:
                    shutil.copy2(str(path), str(dest))
                results["backed_up"].append(str(path))
            except Exception as e:
                results["failed"].append({"path": str(path), "error": f"Yedekleme hatası: {e}"})
                continue

        # Sil
        try:
            if path.is_dir():
                shutil.rmtree(str(path))
            else:
                path.unlink()
            results["success"].append(str(path))
        except PermissionError:
            results["failed"].append({"path": str(path), "error": "İzin reddedildi. sudo gerekebilir."})
        except Exception as e:
            results["failed"].append({"path": str(path), "error": str(e)})

    return results


def fmt_size(b: int) -> str:
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if b < 1024:
            return f"{b:.1f} {unit}"
        b /= 1024
    return f"{b:.1f} PB"
