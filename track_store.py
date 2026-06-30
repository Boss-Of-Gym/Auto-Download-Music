"""
track_store.py — хранилище статусов треков (JSON-файл).

Единственное место, где происходит чтение и запись файла треков.
Формат записи: {"index": int, "track": str, "status": "pending"|"downloaded"|"not_found"}
"""

import asyncio
import json
from pathlib import Path

from utils import app_dir, safe_filename


def save_track_list(tracks: list[str], playlist_name: str) -> Path:
    """
    Сохраняет список треков в JSON рядом со скриптом.
    Если файл уже существует — сохраняет статусы downloaded/not_found
    для треков с совпадающими именами (resume-поддержка при повторном запуске).
    """
    path = app_dir() / (safe_filename(playlist_name) + "_tracks.json")

    # Восстанавливаем статусы из предыдущего прогона
    existing: dict[str, str] = {}
    if path.exists():
        try:
            for e in json.loads(path.read_text(encoding="utf-8")):
                existing[e["track"]] = e["status"]
        except Exception:
            pass

    data = [
        {"index": i + 1, "track": track,
         "status": existing.get(track, "pending")}
        for i, track in enumerate(tracks)
    ]
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def load_pending(path: Path) -> list[dict]:
    """Возвращает только записи со статусом 'pending'."""
    data = json.loads(path.read_text(encoding="utf-8"))
    return [entry for entry in data if entry["status"] == "pending"]


def load_all(path: Path) -> list[dict]:
    """Возвращает все записи из файла."""
    return json.loads(path.read_text(encoding="utf-8"))


async def update_status(path: Path, index: int, status: str, lock: asyncio.Lock) -> None:
    """Потокобезопасно обновляет статус одного трека в JSON-файле."""
    async with lock:
        data = json.loads(path.read_text(encoding="utf-8"))
        for entry in data:
            if entry["index"] == index:
                entry["status"] = status
                break
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def reset_not_found(path: Path) -> int:
    """Сбрасывает все not_found → pending. Возвращает количество сброшенных треков."""
    data = json.loads(path.read_text(encoding="utf-8"))
    count = 0
    for entry in data:
        if entry["status"] == "not_found":
            entry["status"] = "pending"
            count += 1
    if count:
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return count
