from __future__ import annotations

import json
import os
import threading
from collections import deque
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

import requests
import yaml
from medfire_watch.config import PROJECT_ROOT, get_setting


class TelegramDeliveryError(RuntimeError):
    """Safe delivery error with explicit retry policy; never includes a request URL."""

    def __init__(self, message: str, *, retryable: bool = True) -> None:
        super().__init__(message)
        self.retryable = retryable


class AlertManager:
    _history_lock = threading.RLock()
    _inflight: set[tuple[str, str]] = set()
    _camera_generations: dict[str, int] = {}

    def __init__(
        self,
        cooldown_minutes: int = 60,
        camera_cooldown_minutes: int = 5,
        state_path: Path | None = None,
    ) -> None:
        if cooldown_minutes < 0 or camera_cooldown_minutes < 0:
            raise ValueError("Alert cooldown cannot be negative.")
        self.cooldown_minutes = cooldown_minutes
        self.camera_cooldown_minutes = camera_cooldown_minutes
        self.state_path = state_path or PROJECT_ROOT / "runs" / "alerts" / "telegram_state.json"
        self.log_path = self.state_path.with_name("telegram_sent.jsonl")
        self.failure_log_path = self.state_path.with_name("telegram_failed.jsonl")
        self.history_clear_path = self.state_path.with_name("history_cleared.json")
        self.camera_settings_path = self.state_path.with_name("camera_settings.json")

    def camera_cooldown(self) -> int:
        """Read the saved camera interval, falling back to the YAML default."""
        with self._history_lock:
            if not self.camera_settings_path.exists():
                return self.camera_cooldown_minutes
            settings = json.loads(self.camera_settings_path.read_text(encoding="utf-8"))
            minutes = settings["camera_cooldown_minutes"]
            if type(minutes) is not int or not 0 <= minutes <= 1440:
                raise ValueError("Saved camera cooldown must be between 0 and 1440 minutes.")
            return minutes

    def set_camera_cooldown(self, minutes: int) -> int:
        """Persist a camera-only interval shared by API and delivery workers."""
        if type(minutes) is not int or not 0 <= minutes <= 1440:
            raise ValueError("Camera cooldown must be between 0 and 1440 minutes.")
        with self._history_lock:
            self.camera_settings_path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.camera_settings_path.with_suffix(".tmp")
            temporary.write_text(json.dumps({"camera_cooldown_minutes": minutes}), encoding="utf-8")
            temporary.replace(self.camera_settings_path)
        return minutes

    def reset_camera_cooldown(self) -> None:
        """Allow the next qualifying camera alert without removing delivery history."""
        with self._history_lock:
            state = self._read_state()
            state.pop("live_camera", None)
            key = str(self.state_path.resolve())
            self._camera_generations[key] = self._camera_generations.get(key, 0) + 1
            self.state_path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.state_path.with_suffix(".tmp")
            temporary.write_text(json.dumps(state, indent=2), encoding="utf-8")
            temporary.replace(self.state_path)

    def clear_history(self, snapshot_dir: Path) -> dict[str, int]:
        """Clear local attempts/photos while preserving credentials and cooldown settings."""
        directory = snapshot_dir.resolve()
        if snapshot_dir.is_symlink() or directory.parent != snapshot_dir.absolute().parent.resolve():
            raise OSError("Snapshot directory must not redirect outside its configured parent.")
        deleted = remaining = 0
        with self._history_lock:
            attempts = sum(
                len([line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()])
                for path in (self.log_path, self.failure_log_path)
                if path.exists()
            )
            self.history_clear_path.parent.mkdir(parents=True, exist_ok=True)
            self.history_clear_path.write_text(
                json.dumps(
                    {
                        "cleared_at": datetime.now(timezone.utc).isoformat(),
                        "snapshot_directory": str(directory),
                        "generation": uuid4().hex,
                    }
                ),
                encoding="utf-8",
            )
            for path in directory.glob("alert_*.jpg"):
                if path.is_symlink() or not path.is_file() or path.resolve().parent != directory:
                    continue
                try:
                    path.unlink()
                    deleted += 1
                except OSError:
                    remaining += 1
            for path in (self.log_path, self.failure_log_path):
                if path.exists():
                    path.write_text("", encoding="utf-8")
        return {"deleted_attempts": attempts, "deleted_snapshots": deleted, "remaining_snapshots": remaining}

    def _history_accepts(self, timestamp: datetime) -> bool:
        if not self.history_clear_path.exists():
            return True
        cleared = json.loads(self.history_clear_path.read_text(encoding="utf-8"))
        return timestamp >= datetime.fromisoformat(cleared["cleared_at"])

    def _history_generation(self) -> str | None:
        if not self.history_clear_path.exists():
            return None
        cleared = json.loads(self.history_clear_path.read_text(encoding="utf-8"))
        return cleared.get("generation", cleared["cleared_at"])

    @classmethod
    def from_config(cls, config_path: Path) -> AlertManager:
        """Construct an alert manager from its YAML configuration."""
        if not config_path.is_file():
            raise FileNotFoundError(f"Alert configuration is missing: {config_path}")
        config = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
        return cls(
            cooldown_minutes=int(config.get("cooldown_minutes", 60)),
            camera_cooldown_minutes=int(config.get("camera_cooldown_minutes", 5)),
        )

    def status(self) -> dict[str, Any]:
        """Return the current configuration and delivery status."""
        token = get_setting("TELEGRAM_BOT_TOKEN")
        chat_id = get_setting("TELEGRAM_CHAT_ID")
        return {
            "configured": bool(token and chat_id),
            "bot_token_present": bool(token),
            "chat_id_present": bool(chat_id),
            "cooldown_minutes": self.cooldown_minutes,
            "camera_cooldown_minutes": self.camera_cooldown(),
        }

    @staticmethod
    def _save_chat_id(chat_id: str) -> None:
        env_path = PROJECT_ROOT / ".env"
        lines = env_path.read_text(encoding="utf-8-sig").splitlines() if env_path.exists() else []
        key_line = f"TELEGRAM_CHAT_ID={chat_id}"
        for index, line in enumerate(lines):
            if line.startswith("TELEGRAM_CHAT_ID="):
                lines[index] = key_line
                break
        else:
            lines.append(key_line)
        env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        os.environ["TELEGRAM_CHAT_ID"] = chat_id

    def detect_chat(self) -> str:
        """Discover and save a Telegram chat from recent bot updates."""
        token = get_setting("TELEGRAM_BOT_TOKEN")
        if not token:
            raise RuntimeError("Telegram bot token is not configured.")
        try:
            response = requests.get(
                f"https://api.telegram.org/bot{token}/getUpdates",
                params={"timeout": 0, "allowed_updates": json.dumps(["message", "edited_message"])},
                timeout=(5, 20),
            )
            response.raise_for_status()
            payload = response.json()
        except (requests.RequestException, ValueError):
            raise RuntimeError("Telegram chat lookup failed; check the bot token and network.") from None
        if not payload.get("ok"):
            raise RuntimeError("Telegram rejected the chat lookup.")
        candidates = []
        for update in payload.get("result", []):
            message = update.get("message") or update.get("edited_message") or {}
            chat = message.get("chat") or {}
            if chat.get("type") == "private" and chat.get("id") is not None:
                candidates.append(str(chat["id"]))
        distinct_chats = sorted(set(candidates))
        if not distinct_chats:
            raise LookupError("No private chat was found. Open the bot and send it a message first.")
        if len(distinct_chats) > 1:
            raise LookupError("Multiple private chats found. Remove extra chats or set TELEGRAM_CHAT_ID manually.")
        chat_id = distinct_chats[0]
        self._save_chat_id(chat_id)
        return chat_id

    def _read_state(self) -> dict[str, str]:
        with self._history_lock:
            if not self.state_path.exists():
                return {}
            try:
                payload = json.loads(self.state_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise RuntimeError(f"Telegram alert state could not be read: {self.state_path}") from exc
            if not isinstance(payload, dict):
                raise RuntimeError(f"Telegram alert state has an invalid shape: {self.state_path}")
            return {str(key): str(value) for key, value in payload.items()}

    def send(self, message: str, kind: str, dedupe_key: str, photo: Path | None = None) -> dict[str, Any]:
        """Deliver a message or photo and record confirmed Telegram responses."""
        token = get_setting("TELEGRAM_BOT_TOKEN")
        chat_id = get_setting("TELEGRAM_CHAT_ID")
        if not token or not chat_id:
            raise TelegramDeliveryError(
                "Set TELEGRAM_BOT_TOKEN and detect a private Telegram chat first.", retryable=False
            )
        key = (str(self.state_path.resolve()), dedupe_key)
        with self._history_lock:
            if key in self._inflight:
                return {"sent": False, "reason": "in_flight"}
            state = self._read_state()
            now = datetime.now(timezone.utc)
            previous = state.get(dedupe_key)
            if previous:
                sent_at = datetime.fromisoformat(previous)
                cooldown = self.camera_cooldown() if kind == "live_camera" else self.cooldown_minutes
                if now - sent_at < timedelta(minutes=cooldown):
                    return {"sent": False, "reason": "cooldown"}
            generation = self._history_generation()
            camera_generation = self._camera_generations.get(key[0], 0)
            self._inflight.add(key)
        try:
            return self._deliver(message, kind, dedupe_key, photo, token, chat_id, now, generation, camera_generation)
        finally:
            with self._history_lock:
                self._inflight.discard(key)

    def _deliver(self, message, kind, dedupe_key, photo, token, chat_id, now, generation, camera_generation):
        """Perform network I/O outside the lock; a reset invalidates the timer update."""
        base_url = f"https://api.telegram.org/bot{token}"
        try:
            if photo is not None:
                # Release the file handle before the network wait so Delete all works on Windows.
                with self._history_lock:
                    image_bytes = photo.read_bytes()
                response = requests.post(
                    f"{base_url}/sendPhoto",
                    data={"chat_id": chat_id, "caption": message[:1024]},
                    files={"photo": (photo.name, image_bytes, "image/jpeg")},
                    timeout=(5, 30),
                )
            else:
                response = requests.post(
                    f"{base_url}/sendMessage",
                    json={"chat_id": chat_id, "text": message[:4096]},
                    timeout=(5, 30),
                )
            response.raise_for_status()
            result = response.json()
        except requests.HTTPError as exc:
            status = exc.response.status_code if exc.response is not None else None
            raise TelegramDeliveryError(
                "Telegram rejected delivery; check credentials, chat access and rate limits.",
                retryable=status in {408, 429, 500, 502, 503, 504},
            ) from None
        except (OSError, requests.RequestException, ValueError):
            raise TelegramDeliveryError("Telegram did not confirm delivery; no message was recorded as sent.") from None
        if not result.get("ok"):
            raise TelegramDeliveryError(
                "Telegram did not confirm delivery; no message was recorded as sent.",
                retryable=result.get("error_code") in {408, 429, 500, 502, 503, 504},
            )

        log_entry = {
            "sent_at_utc": now.isoformat(),
            "kind": kind,
            "chat_id": str(chat_id),
            "message_id": result.get("result", {}).get("message_id"),
            "confirmed": True,
            "photo_name": photo.name if photo is not None else None,
        }
        with self._history_lock:
            state = self._read_state()
            current_generation = self._camera_generations.get(str(self.state_path.resolve()), 0)
            if kind != "live_camera" or camera_generation == current_generation:
                state[dedupe_key] = datetime.now(timezone.utc).isoformat()
            self.state_path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.state_path.with_suffix(".tmp")
            temporary.write_text(json.dumps(state, indent=2), encoding="utf-8")
            temporary.replace(self.state_path)
            if generation == self._history_generation():
                with self.log_path.open("a", encoding="utf-8") as handle:
                    handle.write(json.dumps(log_entry, separators=(",", ":")) + "\n")
        return {"sent": True, **log_entry}

    def sent_log(self, limit: int = 100, kind: str | None = None) -> list[dict[str, Any]]:
        """List confirmed sends from the attempt log."""
        with self._history_lock:
            if not self.log_path.exists():
                return []
            entries: deque = deque(maxlen=max(0, limit))
            with self.log_path.open(encoding="utf-8") as handle:
                for line in handle:
                    if line.strip():
                        item = json.loads(line)
                        if item.get("confirmed") is True and (kind is None or item.get("kind") == kind):
                            entries.append(item)
            return list(reversed(entries))

    def record_failure(self, kind: str, attempt: int, reason: str, photo_name: str | None = None) -> None:
        """Persist a safe, fixed reason; never write the exception or request URL."""
        self.failure_log_path.parent.mkdir(parents=True, exist_ok=True)
        entry = {
            "sent_at_utc": datetime.now(timezone.utc).isoformat(),
            "kind": kind,
            "attempt": attempt,
            "confirmed": False,
            "reason": reason,
            "photo_name": photo_name,
        }
        with self._history_lock:
            if not self._history_accepts(datetime.fromisoformat(entry["sent_at_utc"])):
                return
            if photo_name and self.history_clear_path.exists():
                cleared = json.loads(self.history_clear_path.read_text(encoding="utf-8"))
                if not (Path(cleared["snapshot_directory"]) / photo_name).is_file():
                    return  # A retry for a deleted snapshot must not restore cleared history.
            with self.failure_log_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(entry, separators=(",", ":")) + "\n")

    def attempt_log(self, limit: int = 100, kind: str | None = None) -> list[dict[str, Any]]:
        """Load recent delivery attempts, optionally filtered by channel."""
        with self._history_lock:
            entries = self.sent_log(limit, kind=kind)
            if self.failure_log_path.exists():
                failures: deque = deque(maxlen=max(0, limit))
                with self.failure_log_path.open(encoding="utf-8") as handle:
                    for line in handle:
                        if line.strip():
                            item = json.loads(line)
                            if kind is None or item.get("kind") == kind:
                                failures.append(item)
                entries.extend(failures)
            return sorted(entries, key=lambda item: item["sent_at_utc"], reverse=True)[:limit]
