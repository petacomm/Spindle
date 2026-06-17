"""
Spindle - Yedekleme Sistemi
"""

import json
import shutil
from datetime import datetime
from pathlib import Path


BACKUP_DIR = Path.home() / ".spindle" / "backups"


def create_backup(paths: list, label: str = "") -> dict:
    """Verilen dosya/klasörlerin yedeğini al."""
    ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    name = f"{ts}_{label}" if label else ts
    backup_path = BACKUP_DIR / name
    backup_path.mkdir(parents=True, exist_ok=True)

    backed = []
    failed = []

    for p in paths:
        src = Path(p)
        if not src.exists():
            failed.append({"path": p, "error": "Bulunamadı"})
            continue
        try:
            dest = backup_path / src.name
            if src.is_dir():
                shutil.copytree(str(src), str(dest))
            else:
                shutil.copy2(str(src), str(dest))
            backed.append(str(src))
        except Exception as e:
            failed.append({"path": p, "error": str(e)})

    # Meta dosyası
    meta = {
        "label": label,
        "created_at": ts,
        "paths": backed,
        "failed": failed,
    }
    (backup_path / "meta.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False))

    return {
        "success": len(backed) > 0,
        "backup_path": str(backup_path),
        "name": name,
        "backed": backed,
        "failed": failed,
    }


def list_backups() -> list:
    """Mevcut yedekleri listele."""
    if not BACKUP_DIR.exists():
        return []

    backups = []
    for d in sorted(BACKUP_DIR.iterdir(), reverse=True):
        if not d.is_dir():
            continue
        meta_file = d / "meta.json"
        if meta_file.exists():
            try:
                meta = json.loads(meta_file.read_text())
                size = sum(f.stat().st_size for f in d.rglob("*") if f.is_file())
                backups.append({
                    "name": d.name,
                    "path": str(d),
                    "label": meta.get("label", ""),
                    "created_at": meta.get("created_at", ""),
                    "files": len(meta.get("paths", [])),
                    "size": fmt_size(size),
                })
            except Exception:
                pass
        else:
            backups.append({
                "name": d.name,
                "path": str(d),
                "label": "",
                "created_at": d.name,
                "files": 0,
                "size": "?",
            })
    return backups


def restore_backup(name: str, dest: str = None) -> dict:
    """Yedeği geri yükle."""
    backup_path = BACKUP_DIR / name
    if not backup_path.exists():
        return {"success": False, "error": f"Yedek bulunamadı: {name}"}

    meta_file = backup_path / "meta.json"
    restored = []
    failed = []

    if meta_file.exists():
        meta = json.loads(meta_file.read_text())
        for original_path in meta.get("paths", []):
            src_name = Path(original_path).name
            src = backup_path / src_name
            dst = Path(dest or original_path)
            try:
                if src.is_dir():
                    if dst.exists():
                        shutil.rmtree(str(dst))
                    shutil.copytree(str(src), str(dst))
                else:
                    shutil.copy2(str(src), str(dst))
                restored.append(str(dst))
            except Exception as e:
                failed.append({"path": str(dst), "error": str(e)})
    else:
        return {"success": False, "error": "Meta dosyası bulunamadı."}

    return {
        "success": len(restored) > 0,
        "restored": restored,
        "failed": failed,
    }


def delete_backup(name: str) -> dict:
    backup_path = BACKUP_DIR / name
    if not backup_path.exists():
        return {"success": False, "error": "Yedek bulunamadı."}
    try:
        shutil.rmtree(str(backup_path))
        return {"success": True}
    except Exception as e:
        return {"success": False, "error": str(e)}


def fmt_size(b: int) -> str:
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if b < 1024:
            return f"{b:.1f} {unit}"
        b /= 1024
    return f"{b:.1f} PB"
