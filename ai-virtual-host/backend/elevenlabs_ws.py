from __future__ import annotations

import asyncio
import base64
import json
import os
import re
from dataclasses import dataclass
from difflib import SequenceMatcher

import sounddevice as sd
import websockets
from websockets import ConnectionClosed

from .elevenlabs_api import (
    ElevenLabsPermissionError,
    fetch_conversation_details,
)
from .session import session_state

ELEVENLABS_URL = "wss://api.elevenlabs.io/v1/convai/conversation"
DEFAULT_PERSONA_NAME = "AI Virtual Host"
OPENING_GRACE_SECONDS = 5
OPENING_AUDIO_SILENCE_SECONDS = 1.5
OPENING_TEXT_RELEASE_SECONDS = 6
OPENING_FORCE_RELEASE_SECONDS = 18
FORMAT_MAP = {
    "pcm_16000": {"samplerate": 16000, "dtype": "int16", "channels": 1},
    "pcm_22050": {"samplerate": 22050, "dtype": "int16", "channels": 1},
    "pcm_24000": {"samplerate": 24000, "dtype": "int16", "channels": 1},
    "pcm_44100": {"samplerate": 44100, "dtype": "int16", "channels": 1},
}
BEHAVIOR_PATTERNS = {
    "phones": r"\b(phone|phones|mobile|mobiles|screen|screens|texting|scrolling)\b",
    "talking": r"\b(talking|chatting|conversation|conversing)\b",
    "seated": r"\b(seated|sitting|sat)\b",
    "standing": r"\b(standing|stood|standing room)\b",
    "distracted": r"\b(distracted|restless|wandering|unfocused|disengaged)\b",
    "engaged": r"\b(engaged|focused|attentive|locked in)\b",
    "applause": r"\b(applause|clapping|cheering|cheers)\b",
    "movement": r"\b(moving|movement|queue|queueing|lining up|walking around)\b",
}


@dataclass
class DescriptionSnapshot:
    text: str
    energy: str
    behaviors: set[str]


class ElevenLabsWSManager:
    def __init__(self) -> None:
        self.websocket = None
        self.audio_stream: sd.RawOutputStream | None = None
        self.audio_queue: asyncio.Queue[bytes | None] | None = None
        self.listener_task: asyncio.Task | None = None
        self.audio_writer_task: asyncio.Task | None = None
        self.fallback_task: asyncio.Task | None = None
        self.opening_release_task: asyncio.Task | None = None
        self.opening_force_release_task: asyncio.Task | None = None
        self.negotiated_format: str = "pcm_16000"
        self._last_sent_at: float | None = None
        self._last_sent_snapshot: DescriptionSnapshot | None = None
        self._reconnect_attempted = False
        self._disconnect_requested = False
        self._opening_gate_active = False
        self._opening_text_received = False
        self._opening_audio_received = False
        self._first_audio_logged = False
        self._buffered_opening_description: str | None = None
        self._last_opening_audio_at: float | None = None
        self._lock = asyncio.Lock()

    async def reset_state(self, clear_disconnect_flag: bool = False) -> None:
        if clear_disconnect_flag:
            self._disconnect_requested = False

        self._reconnect_attempted = False
        self._opening_gate_active = False
        self._opening_text_received = False
        self._opening_audio_received = False
        self._first_audio_logged = False
        self._last_sent_at = None
        self._last_sent_snapshot = None
        self._buffered_opening_description = None
        self._last_opening_audio_at = None

        await self._cancel_task(self.fallback_task)
        self.fallback_task = None
        await self._cancel_task(self.opening_release_task)
        self.opening_release_task = None
        await self._cancel_task(self.opening_force_release_task)
        self.opening_force_release_task = None

        listener = self.listener_task
        self.listener_task = None
        if listener is not None and listener is not asyncio.current_task():
            listener.cancel()
            try:
                await listener
            except asyncio.CancelledError:
                pass
            except Exception:
                pass

        websocket = self.websocket
        self.websocket = None
        if websocket is not None:
            try:
                await websocket.close()
            except Exception:
                pass

        await self._stop_audio_writer()
        await self._close_audio_stream()
        session_state.elevenlabs_connected = False

    async def connect(self, event_data: dict, reconnecting: bool = False) -> None:
        async with self._lock:
            if self.websocket is not None:
                return

            agent_id = os.getenv("ELEVENLABS_AGENT_ID", "")
            api_key = os.getenv("ELEVENLABS_API_KEY", "")
            if not agent_id or agent_id == "your_elevenlabs_agent_id_here":
                message = "ElevenLabs error: ELEVENLABS_AGENT_ID is not configured."
                session_state.set_error(message)
                session_state.append_log(message)
                session_state.is_running = False
                return
            if not api_key or api_key == "your_elevenlabs_api_key_here":
                message = "ElevenLabs error: ELEVENLABS_API_KEY is not configured."
                session_state.set_error(message)
                session_state.append_log(message)
                session_state.is_running = False
                return

            self._disconnect_requested = False
            self._opening_gate_active = False
            self._opening_text_received = False
            self._opening_audio_received = False
            self._first_audio_logged = False
            self._last_opening_audio_at = None
            session_state.audio_diagnosis = ""

            websocket = None
            try:
                session_state.kickoff_state = "connecting"
                session_state.append_log(
                    "Connecting to ElevenLabs agent WebSocket."
                    if not reconnecting
                    else "Attempting ElevenLabs reconnect."
                )
                websocket = await websockets.connect(
                    f"{ELEVENLABS_URL}?agent_id={agent_id}",
                    additional_headers={"xi-api-key": api_key},
                    max_size=None,
                )
                session_state.append_log(
                    "ElevenLabs WebSocket opened. Sending dynamic variables."
                )
                await websocket.send(
                    json.dumps(
                        {
                            "type": "conversation_initiation_client_data",
                            "dynamic_variables": self._build_dynamic_variables(
                                event_data
                            ),
                        }
                    )
                )
                session_state.kickoff_state = "waiting_for_opening"
                session_state.append_log(
                    "Sent ElevenLabs dynamic variables for launch context."
                )

                metadata = await asyncio.wait_for(websocket.recv(), timeout=10)
                if isinstance(metadata, bytes):
                    raise RuntimeError(
                        "Received binary payload before handshake metadata."
                    )

                parsed = json.loads(metadata)
                if parsed.get("type") != "conversation_initiation_metadata":
                    raise RuntimeError(
                        "Handshake metadata not received as the first message."
                    )
                self._record_event_summary(parsed)
                session_state.append_log("ElevenLabs handshake metadata received.")

                conversation_id = (
                    parsed.get("conversation_initiation_metadata_event", {}).get(
                        "conversation_id"
                    )
                    or ""
                )
                session_state.conversation_id = conversation_id
                if conversation_id:
                    session_state.append_log(
                        f"ElevenLabs conversation ID: {conversation_id}."
                    )

                format_name = (
                    parsed.get("conversation_initiation_metadata_event", {}).get(
                        "agent_output_audio_format"
                    )
                    or "pcm_16000"
                )
                audio_config = FORMAT_MAP.get(format_name, FORMAT_MAP["pcm_16000"])
                self.negotiated_format = format_name
                session_state.audio_output_device = self._describe_output_device()
                session_state.append_log(
                    f"Negotiated ElevenLabs audio format: {format_name}. Opening speaker output."
                )
                if session_state.audio_output_device:
                    session_state.append_log(
                        f"Using audio output device: {session_state.audio_output_device}."
                    )

                try:
                    self.audio_stream = await asyncio.to_thread(
                        self._open_stream_blocking, audio_config
                    )
                except Exception as exc:
                    raise RuntimeError(
                        "Audio output stream could not be opened. "
                        "Check your default speaker/output device. "
                        f"Details: {exc}"
                    ) from exc

                self.audio_queue = asyncio.Queue()
                self.audio_writer_task = asyncio.create_task(self._run_audio_writer())
                self.websocket = websocket
                self._opening_gate_active = not reconnecting
                self._reconnect_attempted = False
                session_state.clear_error()
                if not reconnecting:
                    await self._send_kickoff_message(event_data, "initial launch")
                self.listener_task = asyncio.create_task(self._listen())
                session_state.elevenlabs_connected = True
                session_state.append_log(
                    f"ElevenLabs agent connected. Audio format: {format_name}. Camera loop starting."
                )
                session_state.append_log("Audio playback started.")
                if not reconnecting:
                    self.fallback_task = asyncio.create_task(
                        self._await_opening_audio(event_data)
                    )
            except asyncio.TimeoutError:
                message = "ElevenLabs connection failed - no handshake received"
                session_state.set_error(message)
                session_state.append_log(message)
                session_state.elevenlabs_connected = False
                session_state.is_running = False
                if websocket is not None:
                    await websocket.close()
                await self._stop_audio_writer()
                await self._close_audio_stream()
            except Exception as exc:
                message = f"ElevenLabs connection error: {exc}"
                session_state.set_error(message)
                session_state.append_log(message)
                session_state.elevenlabs_connected = False
                session_state.is_running = False
                if websocket is not None:
                    await websocket.close()
                await self._stop_audio_writer()
                await self._close_audio_stream()

    async def disconnect(self) -> None:
        self._disconnect_requested = True
        try:
            from . import main as main_module

            await main_module.broadcast_to_clients(
                {
                    "type": "session_stopped",
                    "message": "Session stopped by operator.",
                }
            )
        except Exception as exc:
            session_state.append_log(f"Stop broadcast error: {exc}")

        session_state.is_running = False
        await self.reset_state()
        session_state.append_log("Audio playback stopped.")

    async def feed_description(self, description: str) -> None:
        session_state.description_history.append(description)
        session_state.description_history = session_state.description_history[-5:]

        if self._opening_gate_active:
            was_buffered = self._buffered_opening_description is not None
            self._buffered_opening_description = description
            if self._opening_text_received:
                session_state.append_log(
                    "First crowd snapshot buffered while waiting for opening audio packets."
                )
            elif was_buffered:
                session_state.append_log(
                    "Buffered crowd snapshot updated while waiting for opening commentary."
                )
            else:
                session_state.kickoff_state = "first_snapshot_buffered"
                session_state.append_log(
                    "First crowd snapshot buffered until opening commentary begins."
                )
            return

        await self._send_description_if_needed(description)

    async def _listen(self) -> None:
        try:
            while self.websocket is not None:
                message = await self.websocket.recv()
                if isinstance(message, str):
                    await self._handle_text_message(message)
                elif isinstance(message, bytes):
                    await self._enqueue_audio_bytes(
                        message, source="binary WebSocket frame"
                    )
        except asyncio.CancelledError:
            raise
        except ConnectionClosed as exc:
            await self._handle_disconnect(f"ElevenLabs socket closed: {exc}")
        except Exception as exc:
            await self._handle_disconnect(f"ElevenLabs listener error: {exc}")

    async def _handle_text_message(self, raw_message: str) -> None:
        try:
            payload = json.loads(raw_message)
        except json.JSONDecodeError:
            return

        message_type = payload.get("type", "")
        self._record_event_summary(payload)
        if message_type == "error":
            message = f"ElevenLabs error: {payload}"
            session_state.set_error(message)
            session_state.append_log(message)
        elif message_type == "audio":
            await self._handle_audio_event(payload)
        elif message_type == "agent_response":
            agent_response = (
                payload.get("agent_response_event", {}).get("agent_response", "").strip()
            )
            if agent_response:
                session_state.last_agent_response = agent_response
                session_state.append_log(f"Agent response: {agent_response}")
                if not self._opening_text_received:
                    self._opening_text_received = True
                    if self._opening_gate_active:
                        session_state.kickoff_state = "agent_text_received"
                        session_state.append_log(
                            "Opening agent text received. Waiting for audio packets."
                        )
        elif message_type == "agent_response_correction":
            corrected_response = (
                payload.get("agent_response_correction_event", {})
                .get("corrected_agent_response", "")
                .strip()
            )
            if corrected_response:
                session_state.last_agent_response = corrected_response
                session_state.append_log(
                    f"Agent response corrected: {corrected_response}"
                )
        elif message_type == "ping" and self.websocket is not None:
            event_id = self._extract_ping_event_id(payload)
            if event_id is None:
                session_state.append_log(
                    "Ping received from ElevenLabs without an event_id."
                )
                return
            await self.websocket.send(
                json.dumps({"type": "pong", "event_id": event_id})
            )
        elif message_type not in {
            "user_transcript",
            "vad_score",
            "internal_tentative_agent_response",
            "client_tool_call",
            "interruption",
            "conversation_initiation_metadata",
            "contextual_update",
        }:
            session_state.append_log(
                "Unexpected ElevenLabs event received: "
                f"{message_type or 'unknown'} "
                f"(keys: {', '.join(sorted(payload.keys())) or 'none'})."
            )

    async def _handle_audio_event(self, payload: dict) -> None:
        audio_base64 = payload.get("audio_event", {}).get("audio_base_64", "")
        if not audio_base64:
            session_state.append_log(
                "ElevenLabs audio event received without audio payload."
            )
            return

        try:
            audio_bytes = base64.b64decode(audio_base64)
        except Exception as exc:
            message = f"Audio decode error: {exc}"
            session_state.set_error(message)
            session_state.append_log(message)
            return

        await self._enqueue_audio_bytes(audio_bytes, source="audio event")

    async def _enqueue_audio_bytes(self, audio_bytes: bytes, source: str) -> None:
        if not audio_bytes:
            return

        if self.audio_stream is None or self.audio_queue is None:
            session_state.audio_diagnosis = "audio_stream_received_but_playback_failed"
            message = (
                "ElevenLabs audio arrived, but the speaker output stream is not ready."
            )
            session_state.set_error(message)
            session_state.append_log(message)
            return

        session_state.mark_audio_event(len(audio_bytes))
        if not self._first_audio_logged:
            self._first_audio_logged = True
            session_state.append_log(
                f"First audio packet received from ElevenLabs via {source} ({len(audio_bytes)} bytes)."
            )

        await self._mark_opening_audio_live()
        await self.audio_queue.put(audio_bytes)

    async def _mark_opening_audio_live(self) -> None:
        if not self._opening_audio_received:
            self._opening_audio_received = True
            session_state.audio_diagnosis = ""
            self._clear_opening_audio_error()
            await self._cancel_task(self.fallback_task)
            self.fallback_task = None
            session_state.append_log(
                "Audio packets received from ElevenLabs. Opening commentary is live."
            )
            if self._opening_gate_active:
                session_state.kickoff_state = "opening_live"
            else:
                session_state.kickoff_state = "audio_received"
        elif not self._opening_gate_active:
            session_state.kickoff_state = "audio_received"

        if self._opening_gate_active:
            self._last_opening_audio_at = asyncio.get_running_loop().time()
            await self._cancel_task(self.opening_release_task)
            self.opening_release_task = asyncio.create_task(
                self._release_after_opening_audio_silence()
            )

    async def _await_opening_audio(self, event_data: dict) -> None:
        try:
            await asyncio.sleep(OPENING_GRACE_SECONDS)
            if (
                not session_state.is_running
                or not session_state.elevenlabs_connected
                or self.websocket is None
                or not self._opening_gate_active
            ):
                return

            diagnosis_code, message = await self._diagnose_no_audio()
            session_state.audio_diagnosis = diagnosis_code
            session_state.set_error(message)
            session_state.append_log(message)
            await self._send_kickoff_message(event_data, "opening fallback")
            session_state.kickoff_state = "fallback_sent"
            await self._cancel_task(self.opening_release_task)
            self.opening_release_task = asyncio.create_task(
                self._release_after_opening_text_window()
            )
        except asyncio.CancelledError:
            raise

    async def _send_kickoff_message(self, event_data: dict, reason: str) -> None:
        if self.websocket is None:
            return

        session_state.append_log(f"Sending kickoff message to ElevenLabs ({reason}).")
        await self.websocket.send(
            json.dumps(
                {
                    "type": "user_message",
                    "text": self._build_launch_kickoff_message(event_data),
                }
            )
        )
        if reason == "initial launch":
            await self._cancel_task(self.opening_force_release_task)
            self.opening_force_release_task = asyncio.create_task(
                self._force_release_after_opening_timeout()
            )

        if reason == "initial launch":
            session_state.append_log(
                "Initial event context kickoff message sent to ElevenLabs before camera updates."
            )
        else:
            session_state.append_log(
                "Initial event context fallback message sent to ElevenLabs."
            )

    async def _release_after_opening_audio_silence(self) -> None:
        try:
            await asyncio.sleep(OPENING_AUDIO_SILENCE_SECONDS)
            if not self._opening_gate_active or not self._opening_audio_received:
                return

            last_audio_at = self._last_opening_audio_at
            if last_audio_at is None:
                return

            now = asyncio.get_running_loop().time()
            if now - last_audio_at < OPENING_AUDIO_SILENCE_SECONDS:
                return

            self._opening_gate_active = False
            self.opening_release_task = None
            await self._cancel_task(self.opening_force_release_task)
            self.opening_force_release_task = None
            session_state.kickoff_state = "opening_complete"
            session_state.append_log(
                "Opening host commentary finished. Releasing buffered crowd updates."
            )
            await self._flush_buffered_description(
                "the host finished the opening commentary"
            )
        except asyncio.CancelledError:
            raise

    async def _release_after_opening_text_window(self) -> None:
        try:
            await asyncio.sleep(OPENING_TEXT_RELEASE_SECONDS)
            if not self._opening_gate_active or self._opening_audio_received:
                return

            self._opening_gate_active = False
            self.opening_release_task = None
            await self._cancel_task(self.opening_force_release_task)
            self.opening_force_release_task = None
            session_state.kickoff_state = "opening_complete"
            session_state.append_log(
                "Opening host grace window finished without audio. Releasing buffered crowd updates."
            )
            await self._flush_buffered_description(
                "the host opening grace window elapsed"
            )
        except asyncio.CancelledError:
            raise

    async def _flush_buffered_description(self, reason: str) -> None:
        if not self._buffered_opening_description:
            return

        buffered_description = self._buffered_opening_description
        self._buffered_opening_description = None
        session_state.append_log(f"Releasing buffered crowd snapshot: {reason}.")
        await self._send_description_if_needed(buffered_description)

    async def _send_description_if_needed(self, description: str) -> None:
        should_send, reason, snapshot = self._should_send_description(description)
        if not should_send:
            session_state.append_log(f"Description skipped: {reason}")
            return

        if self.websocket is None or not session_state.elevenlabs_connected:
            message = "Description skipped: ElevenLabs connection is not active."
            session_state.set_error(message)
            session_state.append_log(message)
            return

        try:
            await self.websocket.send(
                json.dumps(
                    {
                        "type": "user_message",
                        "text": f"[CROWD UPDATE] {description}",
                    }
                )
            )
            self._last_sent_at = asyncio.get_running_loop().time()
            self._last_sent_snapshot = snapshot
            session_state.append_log(f"Description sent to ElevenLabs: {reason}")
        except Exception as exc:
            message = f"ElevenLabs send error: {exc}"
            session_state.set_error(message)
            session_state.append_log(message)

    async def _run_audio_writer(self) -> None:
        try:
            while self.audio_queue is not None:
                audio_bytes = await self.audio_queue.get()
                if audio_bytes is None:
                    break
                if self.audio_stream is None:
                    continue
                await asyncio.to_thread(self.audio_stream.write, audio_bytes)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            session_state.audio_diagnosis = "audio_stream_received_but_playback_failed"
            message = f"Audio playback error: {exc}"
            session_state.set_error(message)
            session_state.append_log(message)

    async def _stop_audio_writer(self) -> None:
        queue = self.audio_queue
        task = self.audio_writer_task
        self.audio_queue = None
        self.audio_writer_task = None

        if queue is not None:
            try:
                await queue.put(None)
            except Exception:
                pass

        if task is not None and task is not asyncio.current_task():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            except Exception:
                pass

    async def _handle_disconnect(self, message: str) -> None:
        session_state.set_error(message)
        session_state.append_log(message)
        session_state.elevenlabs_connected = False
        session_state.kickoff_state = "reconnecting" if session_state.is_running else "idle"
        self.websocket = None
        self._opening_gate_active = False
        self._opening_text_received = False
        self._opening_audio_received = False
        self._first_audio_logged = False
        self._last_opening_audio_at = None

        await self._cancel_task(self.fallback_task)
        self.fallback_task = None
        await self._cancel_task(self.opening_release_task)
        self.opening_release_task = None
        await self._cancel_task(self.opening_force_release_task)
        self.opening_force_release_task = None
        await self._stop_audio_writer()
        await self._close_audio_stream()

        if not session_state.is_running or self._disconnect_requested:
            return

        if self._reconnect_attempted:
            session_state.append_log(
                "ElevenLabs reconnect failed after one retry. Session stopping."
            )
            session_state.is_running = False
            return

        self._reconnect_attempted = True
        session_state.append_log("Auto-reconnect triggered.")
        await asyncio.sleep(3)
        if session_state.is_running and not self._disconnect_requested:
            await self.connect(session_state.event_data, reconnecting=True)

    def _should_send_description(
        self, description: str
    ) -> tuple[bool, str, DescriptionSnapshot]:
        snapshot = self._snapshot_description(description)
        now = asyncio.get_running_loop().time()
        previous = self._last_sent_snapshot

        if previous is None or self._last_sent_at is None:
            return True, "first crowd update", snapshot

        if now - self._last_sent_at >= 180:
            return True, "forced refresh after 3 minutes", snapshot

        if snapshot.energy != previous.energy:
            return True, "energy level changed", snapshot

        if snapshot.behaviors != previous.behaviors:
            appeared = snapshot.behaviors - previous.behaviors
            disappeared = previous.behaviors - snapshot.behaviors
            change_parts = []
            if appeared:
                change_parts.append(f"new behavior: {', '.join(sorted(appeared))}")
            if disappeared:
                change_parts.append(
                    f"behavior cleared: {', '.join(sorted(disappeared))}"
                )
            return True, "; ".join(change_parts), snapshot

        similarity = SequenceMatcher(
            None, previous.text.lower(), snapshot.text.lower()
        ).ratio()
        if similarity < 0.72:
            return True, "meaningful wording change detected", snapshot

        return False, "no meaningful crowd change", snapshot

    def _snapshot_description(self, description: str) -> DescriptionSnapshot:
        lowered = description.lower()
        energy = "moderate"
        if re.search(r"\bhigh energy\b|\bhigh\b", lowered):
            energy = "high"
        elif re.search(r"\b(?:low energy|low)\b", lowered):
            energy = "low"

        behaviors = {
            key
            for key, pattern in BEHAVIOR_PATTERNS.items()
            if re.search(pattern, lowered)
        }
        return DescriptionSnapshot(text=description, energy=energy, behaviors=behaviors)

    def _build_dynamic_variables(self, event_data: dict) -> dict[str, str]:
        return {
            "persona_name": event_data.get("persona_name") or DEFAULT_PERSONA_NAME,
            "event_name": event_data.get("event_name", ""),
            "event_description": event_data.get("event_description", ""),
            "hosts": event_data.get("hosts", ""),
            "sponsors": event_data.get("sponsors", "") or "none provided",
            "agenda": event_data.get("agenda", ""),
            "notes": event_data.get("notes", "") or "none provided",
        }

    def _build_launch_kickoff_message(self, event_data: dict) -> str:
        return (
            "[SESSION START] "
            "You already have the full event details below. Use them right now and begin hosting immediately. "
            f"Persona name: {event_data.get('persona_name') or DEFAULT_PERSONA_NAME}. "
            f"Event name: {event_data.get('event_name', '')}. "
            f"Event description: {event_data.get('event_description', '')}. "
            f"Hosts: {event_data.get('hosts', '')}. "
            f"Sponsors: {event_data.get('sponsors', '') or 'none provided'}. "
            f"Agenda: {event_data.get('agenda', '')}. "
            f"Additional notes: {event_data.get('notes', '') or 'none provided'}. "
            "Open with a warm emcee-style welcome for the crowd, reference the event naturally, "
            "and start engaging the room now. Do not ask for event details. "
            "Act like the live pre-show host and finish your opening turn before reacting to any crowd update."
        )

    async def _force_release_after_opening_timeout(self) -> None:
        try:
            await asyncio.sleep(OPENING_FORCE_RELEASE_SECONDS)
            if not self._opening_gate_active:
                return

            self._opening_gate_active = False
            self.opening_force_release_task = None
            session_state.kickoff_state = "opening_complete"
            session_state.append_log(
                "Opening host commentary hold window completed. Releasing buffered crowd updates."
            )
            await self._flush_buffered_description(
                "the opening hold window elapsed"
            )
        except asyncio.CancelledError:
            raise

    async def _diagnose_no_audio(self) -> tuple[str, str]:
        if session_state.agent_text_only:
            return (
                "agent_text_only_mode",
                "This ElevenLabs agent is configured in text-only mode, so it can return text responses without any audio output.",
            )

        if session_state.audio_events_received > 0:
            return (
                "audio_stream_received_but_playback_failed",
                "Audio packets reached the backend, but playback failed before they could be heard through the output device.",
            )

        if not session_state.conversation_id:
            if self._opening_text_received:
                return (
                    "conversation_diagnosis_unavailable",
                    f"Agent text was received, but no audio packets arrived within {OPENING_GRACE_SECONDS} seconds and no ElevenLabs conversation ID was available for diagnosis.",
                )
            return (
                "conversation_diagnosis_unavailable",
                f"No opening commentary audio arrived within {OPENING_GRACE_SECONDS} seconds and the conversation could not be diagnosed yet.",
            )

        try:
            details = await fetch_conversation_details(session_state.conversation_id)
        except ElevenLabsPermissionError as exc:
            session_state.agent_preflight_status = "permission_unavailable"
            session_state.append_log(
                "Conversation audio diagnosis is unavailable because the current API key "
                f"is missing {exc.permission or 'convai_read'} permission."
            )
            return (
                "insufficient_api_permissions",
                "This API key is missing ElevenLabs convai_read permission, so conversation-level audio diagnosis is unavailable.",
            )
        except Exception as exc:
            session_state.append_log(
                f"Unable to diagnose ElevenLabs conversation audio: {exc}"
            )
            if self._opening_text_received:
                return (
                    "conversation_diagnosis_unavailable",
                    f"Agent text was received, but no audio packets arrived within {OPENING_GRACE_SECONDS} seconds. Conversation diagnosis failed: {exc}",
                )
            return (
                "conversation_diagnosis_unavailable",
                f"No opening commentary audio arrived within {OPENING_GRACE_SECONDS} seconds. Conversation diagnosis failed: {exc}",
            )

        has_response_audio = bool(details.get("has_response_audio"))
        has_audio = bool(details.get("has_audio"))

        if has_response_audio:
            return (
                "response_audio_exists_but_websocket_stream_missing",
                "The agent produced response audio in ElevenLabs, but no audio event reached this backend WebSocket stream.",
            )

        if self._opening_text_received or has_audio:
            return (
                "agent_generated_text_but_no_response_audio",
                "The agent produced text, but ElevenLabs reports no response audio for this conversation.",
            )

        return (
            "agent_generated_text_but_no_response_audio",
            "No response audio was generated for this ElevenLabs conversation.",
        )

    def _record_event_summary(self, payload: dict) -> None:
        message_type = str(payload.get("type") or "unknown")
        summary = message_type
        if message_type == "audio":
            event_id = payload.get("audio_event", {}).get("event_id")
            if event_id is not None:
                summary = f"audio#{event_id}"
        elif message_type == "ping":
            event_id = self._extract_ping_event_id(payload)
            if event_id is not None:
                summary = f"ping#{event_id}"
        elif message_type == "agent_response":
            summary = "agent_response"
        elif message_type == "agent_response_correction":
            summary = "agent_response_correction"
        session_state.push_elevenlabs_event(summary)

    def _extract_ping_event_id(self, payload: dict) -> int | str | None:
        direct_event_id = payload.get("event_id")
        if isinstance(direct_event_id, (str, int)) and str(direct_event_id):
            return direct_event_id

        for key in ("ping_event", "ping", "event"):
            nested = payload.get(key)
            if isinstance(nested, dict):
                nested_event_id = nested.get("event_id")
                if isinstance(nested_event_id, (str, int)) and str(nested_event_id):
                    return nested_event_id

        return None

    def _describe_output_device(self) -> str:
        try:
            device = sd.query_devices(kind="output")
        except Exception:
            return "Default output device unavailable"

        if isinstance(device, dict):
            name = device.get("name", "").strip()
            hostapi = device.get("hostapi")
            if name and isinstance(hostapi, int):
                try:
                    hostapi_name = sd.query_hostapis(hostapi)["name"]
                    return f"{name} ({hostapi_name})"
                except Exception:
                    return name
            if name:
                return name

        return "Default output device"

    def _open_stream_blocking(self, audio_config: dict) -> sd.RawOutputStream:
        stream = sd.RawOutputStream(**audio_config)
        stream.start()
        return stream

    def _clear_opening_audio_error(self) -> None:
        lowered = session_state.last_error.lower()
        if "opening commentary audio" in lowered or "audio packets arrived within" in lowered:
            session_state.clear_error()

    async def _close_audio_stream(self) -> None:
        if self.audio_stream is None:
            return
        stream = self.audio_stream
        self.audio_stream = None
        try:
            await asyncio.to_thread(stream.stop)
        except Exception:
            pass
        try:
            await asyncio.to_thread(stream.close)
        except Exception:
            pass

    async def _cancel_task(self, task: asyncio.Task | None) -> None:
        if task is None or task is asyncio.current_task():
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        except Exception:
            pass


elevenlabs_manager = ElevenLabsWSManager()
