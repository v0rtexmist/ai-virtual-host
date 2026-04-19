from __future__ import annotations

import asyncio
import os
from typing import Any

from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from .camera import run_camera_loop
from .elevenlabs_api import (
    ElevenLabsAPIError,
    ElevenLabsPermissionError,
    fetch_agent_details,
)
from .elevenlabs_ws import elevenlabs_manager
from .session import session_state

app = FastAPI(title="AI Virtual Host")

DEFAULT_PERSONA_NAME = "AI Virtual Host"

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

status_clients: list[WebSocket] = []
camera_task: asyncio.Task | None = None
elevenlabs_task: asyncio.Task | None = None


class LaunchRequest(BaseModel):
    persona_name: str = ""
    event_name: str = Field(min_length=1)
    event_description: str = Field(min_length=1)
    hosts: str = Field(min_length=1)
    sponsors: str = ""
    agenda: str = Field(min_length=1)
    notes: str = ""


def _extract_agent_preflight(agent_payload: dict) -> dict[str, Any]:
    conversation_config = agent_payload.get("conversation_config") or {}
    conversation = conversation_config.get("conversation") or {}
    tts = conversation_config.get("tts") or {}
    client_events = conversation.get("client_events") or []

    return {
        "text_only": bool(conversation.get("text_only")),
        "client_events": [str(event) for event in client_events],
        "voice_id": str(tts.get("voice_id") or "").strip(),
        "agent_output_audio_format": str(
            tts.get("agent_output_audio_format") or ""
        ).strip(),
        "first_message_status": "not_checked",
    }


def _build_preflight_error(preflight: dict[str, Any]) -> str:
    if not preflight["voice_id"]:
        return (
            "ElevenLabs launch blocked: no TTS voice is configured for this agent."
        )
    if "audio" not in {event.lower() for event in preflight["client_events"]}:
        return (
            "ElevenLabs launch blocked: the agent's client events do not include audio."
        )
    return ""


def _build_text_only_warning(preflight: dict[str, Any]) -> str:
    if not preflight["text_only"]:
        return ""
    return (
        "ElevenLabs warning: the agent API still reports text_only=true. "
        "If you already disabled chat mode in the dashboard, the published or active config may not have updated yet. "
        "Launch will continue because voice and audio events are still configured."
    )


async def broadcast_to_clients(message: dict[str, Any]) -> None:
    disconnected_clients: list[WebSocket] = []
    for client in list(status_clients):
        try:
            await client.send_json(message)
        except Exception:
            disconnected_clients.append(client)

    for client in disconnected_clients:
        if client in status_clients:
            status_clients.remove(client)


session_state.set_broadcaster(broadcast_to_clients)


@app.post("/api/launch")
async def launch_session(payload: LaunchRequest) -> dict[str, str]:
    global camera_task, elevenlabs_task

    if session_state.is_running:
        raise HTTPException(status_code=409, detail="A session is already running.")

    await elevenlabs_manager.reset_state(clear_disconnect_flag=True)
    event_data = payload.model_dump()
    event_data["persona_name"] = event_data.get("persona_name") or DEFAULT_PERSONA_NAME
    session_state.event_data = event_data
    session_state.log = []
    session_state.reset_runtime_state()
    session_state.append_log(
        f"Launch requested for event: {session_state.event_data['event_name']}."
    )
    session_state.append_log(
        "Launch context received from frontend: "
        f"hosts={session_state.event_data['hosts']}; "
        f"sponsors={session_state.event_data['sponsors'] or 'none provided'}; "
        f"agenda_length={len(session_state.event_data['agenda'])}; "
        f"notes_present={'yes' if session_state.event_data['notes'] else 'no'}."
    )

    agent_id = os.getenv("ELEVENLABS_AGENT_ID", "")
    if not agent_id or agent_id == "your_elevenlabs_agent_id_here":
        message = "ElevenLabs error: ELEVENLABS_AGENT_ID is not configured."
        session_state.set_error(message)
        session_state.append_log(message)
        raise HTTPException(status_code=400, detail=message)

    try:
        agent_payload = await fetch_agent_details(agent_id)
    except ValueError as exc:
        message = f"ElevenLabs error: {exc}"
        session_state.set_error(message)
        session_state.append_log(message)
        raise HTTPException(status_code=400, detail=message) from exc
    except ElevenLabsPermissionError as exc:
        session_state.agent_preflight_status = "permission_unavailable"
        session_state.agent_first_message_status = "permission_unavailable"
        session_state.audio_diagnosis = "insufficient_api_permissions"
        session_state.append_log(
            "ElevenLabs preflight skipped: the current API key is missing "
            f"{exc.permission or 'convai_read'} permission. Launch will continue, "
            "but agent validation and conversation-level audio diagnosis will be unavailable."
        )
        agent_payload = None
    except ElevenLabsAPIError as exc:
        message = str(exc)
        session_state.set_error(message)
        session_state.append_log(message)
        raise HTTPException(status_code=502, detail=message) from exc

    if agent_payload is not None:
        preflight = _extract_agent_preflight(agent_payload)
        session_state.agent_preflight_status = "ok"
        session_state.agent_text_only = preflight["text_only"]
        session_state.agent_client_events = preflight["client_events"]
        session_state.agent_voice_id = preflight["voice_id"]
        session_state.agent_first_message_status = preflight["first_message_status"]
        session_state.audio_diagnosis = ""

        session_state.append_log(
            "ElevenLabs preflight loaded: "
            f"text_only={preflight['text_only']}, "
            f"voice_id={'set' if preflight['voice_id'] else 'missing'}, "
            f"audio_format={preflight['agent_output_audio_format'] or 'missing'}, "
            f"client_events={', '.join(preflight['client_events']) or 'none'}."
        )

        preflight_error = _build_preflight_error(preflight)
        if preflight_error:
            session_state.set_error(preflight_error)
            session_state.append_log(preflight_error)
            raise HTTPException(status_code=400, detail=preflight_error)

        text_only_warning = _build_text_only_warning(preflight)
        if text_only_warning:
            session_state.append_log(text_only_warning)

    session_state.is_running = True
    session_state.kickoff_state = "connecting"

    elevenlabs_task = asyncio.create_task(
        elevenlabs_manager.connect(session_state.event_data)
    )
    camera_task = asyncio.create_task(run_camera_loop())

    return {"status": "launched"}


@app.post("/api/stop")
async def stop_session() -> dict[str, str]:
    global camera_task, elevenlabs_task

    session_state.is_running = False
    await elevenlabs_manager.disconnect()

    if camera_task is not None:
        camera_task.cancel()
        try:
            await camera_task
        except asyncio.CancelledError:
            pass
        camera_task = None

    if elevenlabs_task is not None:
        if not elevenlabs_task.done():
            elevenlabs_task.cancel()
            try:
                await elevenlabs_task
            except asyncio.CancelledError:
                pass
        elevenlabs_task = None

    session_state.append_log("Session stopped by operator.")
    return {"status": "stopped"}


@app.get("/api/status")
async def get_status() -> dict[str, Any]:
    return {
        "event_data": session_state.event_data,
        "is_running": session_state.is_running,
        "elevenlabs_connected": session_state.elevenlabs_connected,
        "last_description": session_state.last_image_description,
        "last_error": session_state.last_error,
        "kickoff_state": session_state.kickoff_state,
        "last_agent_response": session_state.last_agent_response,
        "conversation_id": session_state.conversation_id,
        "audio_diagnosis": session_state.audio_diagnosis,
        "agent_text_only": session_state.agent_text_only,
        "agent_client_events": session_state.agent_client_events,
        "agent_voice_id": session_state.agent_voice_id,
        "agent_first_message_status": session_state.agent_first_message_status,
        "agent_preflight_status": session_state.agent_preflight_status,
        "audio_events_received": session_state.audio_events_received,
        "audio_bytes_received": session_state.audio_bytes_received,
        "last_audio_event_at": session_state.last_audio_event_at,
        "audio_output_device": session_state.audio_output_device,
        "recent_elevenlabs_events": session_state.recent_elevenlabs_events,
        "log": session_state.recent_logs(20),
    }


@app.get("/api/logs")
async def get_logs(limit: int = Query(default=200, ge=1, le=200)) -> dict[str, Any]:
    return {"log": session_state.recent_logs(limit)}


@app.websocket("/ws/status")
async def status_socket(websocket: WebSocket) -> None:
    await websocket.accept()
    status_clients.append(websocket)
    try:
        await websocket.send_json(
            {
                "type": "status_snapshot",
                "event_data": session_state.event_data,
                "is_running": session_state.is_running,
                "elevenlabs_connected": session_state.elevenlabs_connected,
                "last_description": session_state.last_image_description,
                "last_error": session_state.last_error,
                "kickoff_state": session_state.kickoff_state,
                "last_agent_response": session_state.last_agent_response,
                "conversation_id": session_state.conversation_id,
                "audio_diagnosis": session_state.audio_diagnosis,
                "agent_text_only": session_state.agent_text_only,
                "agent_client_events": session_state.agent_client_events,
                "agent_voice_id": session_state.agent_voice_id,
                "agent_first_message_status": session_state.agent_first_message_status,
                "agent_preflight_status": session_state.agent_preflight_status,
                "audio_events_received": session_state.audio_events_received,
                "audio_bytes_received": session_state.audio_bytes_received,
                "last_audio_event_at": session_state.last_audio_event_at,
                "audio_output_device": session_state.audio_output_device,
                "recent_elevenlabs_events": session_state.recent_elevenlabs_events,
                "log": session_state.recent_logs(20),
            }
        )
        while True:
            await asyncio.sleep(30)
    except WebSocketDisconnect:
        if websocket in status_clients:
            status_clients.remove(websocket)
    except Exception:
        if websocket in status_clients:
            status_clients.remove(websocket)
