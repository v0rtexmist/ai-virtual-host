from __future__ import annotations

import os

import httpx

ELEVENLABS_API_BASE = "https://api.elevenlabs.io/v1/convai"
DEFAULT_TIMEOUT = 15.0


class ElevenLabsAPIError(RuntimeError):
    pass


class ElevenLabsPermissionError(ElevenLabsAPIError):
    def __init__(self, permission: str | None, message: str) -> None:
        super().__init__(message)
        self.permission = permission or ""


def _raise_api_error(prefix: str, exc: httpx.HTTPStatusError) -> None:
    response = exc.response
    permission = ""
    try:
        payload = response.json()
    except ValueError:
        payload = {}

    detail = payload.get("detail") if isinstance(payload, dict) else None
    if isinstance(detail, dict) and detail.get("status") == "missing_permissions":
        message = str(detail.get("message") or "").strip() or response.text
        for token in message.replace(",", " ").split():
            if token.startswith("convai_"):
                permission = token
                break
        raise ElevenLabsPermissionError(
            permission,
            f"{prefix}: {message}",
        ) from exc

    raise ElevenLabsAPIError(
        f"{prefix}: {response.status_code} {response.text}"
    ) from exc


async def fetch_agent_details(
    agent_id: str, api_key: str | None = None
) -> dict:
    resolved_api_key = api_key or os.getenv("ELEVENLABS_API_KEY", "")
    if not agent_id:
        raise ValueError("ELEVENLABS_AGENT_ID is not configured.")
    if not resolved_api_key or resolved_api_key == "your_elevenlabs_api_key_here":
        raise ValueError("ELEVENLABS_API_KEY is not configured.")

    try:
        async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
            response = await client.get(
                f"{ELEVENLABS_API_BASE}/agents/{agent_id}",
                headers={"xi-api-key": resolved_api_key},
            )
            response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        _raise_api_error("Unable to fetch ElevenLabs agent details", exc)
    except httpx.HTTPError as exc:
        raise ElevenLabsAPIError(
            f"Unable to reach ElevenLabs agent API: {exc}"
        ) from exc

    return response.json()


async def fetch_conversation_details(
    conversation_id: str, api_key: str | None = None
) -> dict:
    resolved_api_key = api_key or os.getenv("ELEVENLABS_API_KEY", "")
    if not conversation_id:
        raise ValueError("No ElevenLabs conversation ID is available yet.")
    if not resolved_api_key or resolved_api_key == "your_elevenlabs_api_key_here":
        raise ValueError("ELEVENLABS_API_KEY is not configured.")

    try:
        async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
            response = await client.get(
                f"{ELEVENLABS_API_BASE}/conversations/{conversation_id}",
                headers={"xi-api-key": resolved_api_key},
            )
            response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        _raise_api_error("Unable to fetch ElevenLabs conversation details", exc)
    except httpx.HTTPError as exc:
        raise ElevenLabsAPIError(
            f"Unable to reach ElevenLabs conversation API: {exc}"
        ) from exc

    return response.json()
