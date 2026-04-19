from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Awaitable, Callable

BroadcastCallback = Callable[[dict], Awaitable[None]]


def _utc_timestamp() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


@dataclass
class SessionState:
    event_data: dict = field(default_factory=dict)
    is_running: bool = False
    elevenlabs_connected: bool = False
    last_image_description: str = ""
    last_error: str = ""
    kickoff_state: str = "idle"
    last_agent_response: str = ""
    conversation_id: str = ""
    audio_diagnosis: str = ""
    agent_text_only: bool = False
    agent_client_events: list[str] = field(default_factory=list)
    agent_voice_id: str = ""
    agent_first_message_status: str = "not_checked"
    agent_preflight_status: str = "unknown"
    audio_events_received: int = 0
    audio_bytes_received: int = 0
    last_audio_event_at: str = ""
    audio_output_device: str = ""
    recent_elevenlabs_events: list[str] = field(default_factory=list)
    description_history: list[str] = field(default_factory=list)
    log: list[dict[str, str]] = field(default_factory=list)
    _broadcaster: BroadcastCallback | None = None

    def set_broadcaster(self, broadcaster: BroadcastCallback) -> None:
        self._broadcaster = broadcaster

    def append_log(self, message: str) -> dict[str, str]:
        entry = {"timestamp": _utc_timestamp(), "message": message}
        self.log.append(entry)
        self.log = self.log[-200:]
        broadcaster = self._broadcaster
        if broadcaster is not None:
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = None
            if loop is not None:
                loop.create_task(
                    broadcaster(
                        {
                            "type": "log",
                            "timestamp": entry["timestamp"],
                            "message": entry["message"],
                        }
                    )
                )
        return entry

    def recent_logs(self, limit: int = 20) -> list[dict[str, str]]:
        return self.log[-limit:]

    def set_error(self, message: str) -> None:
        self.last_error = message

    def clear_error(self) -> None:
        self.last_error = ""

    def reset_runtime_state(self) -> None:
        self.is_running = False
        self.elevenlabs_connected = False
        self.last_image_description = ""
        self.last_error = ""
        self.kickoff_state = "idle"
        self.last_agent_response = ""
        self.conversation_id = ""
        self.audio_diagnosis = ""
        self.agent_text_only = False
        self.agent_client_events = []
        self.agent_voice_id = ""
        self.agent_first_message_status = "not_checked"
        self.agent_preflight_status = "unknown"
        self.audio_events_received = 0
        self.audio_bytes_received = 0
        self.last_audio_event_at = ""
        self.audio_output_device = ""
        self.recent_elevenlabs_events = []
        self.description_history = []

    def mark_audio_event(self, byte_count: int) -> None:
        self.audio_events_received += 1
        self.audio_bytes_received += byte_count
        self.last_audio_event_at = _utc_timestamp()
        broadcaster = self._broadcaster
        if broadcaster is not None:
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = None
            if loop is not None:
                loop.create_task(
                    broadcaster(
                        {
                            "type": "audio_activity",
                            "audio_events_received": self.audio_events_received,
                            "audio_bytes_received": self.audio_bytes_received,
                            "last_audio_event_at": self.last_audio_event_at,
                        }
                    )
                )

    def push_elevenlabs_event(self, summary: str) -> None:
        if not summary:
            return
        self.recent_elevenlabs_events.append(summary)
        self.recent_elevenlabs_events = self.recent_elevenlabs_events[-10:]

    def reset_runtime_flags(self) -> None:
        self.is_running = False
        self.elevenlabs_connected = False


session_state = SessionState()
