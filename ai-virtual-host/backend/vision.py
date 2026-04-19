from __future__ import annotations

import os

import httpx

from .session import session_state

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
VISION_MODEL = "meta-llama/llama-4-maverick"
VISION_PROMPT = (
    "You are an audience observer for a live event. Analyze this image of the audience "
    "and describe in 2-3 concise sentences: what people are doing (on phones, talking, "
    "seated, distracted, engaged, standing), the overall energy level (low/moderate/high), "
    "and any notable behaviors. Be specific and factual. Do not editorialize. Output only "
    "the description, nothing else."
)


async def describe_image(base64_image: str, event_data: dict) -> str | None:
    api_key = os.getenv("OPENROUTER_API_KEY", "")
    if not api_key or api_key == "your_openrouter_api_key_here":
        session_state.append_log("Vision error: OPENROUTER_API_KEY is not configured.")
        return None

    event_context = (
        "Event context:\n"
        f"- Event Name: {event_data.get('event_name', '')}\n"
        f"- Description: {event_data.get('event_description', '')}\n"
        f"- Hosts: {event_data.get('hosts', '')}\n"
        f"- Sponsors: {event_data.get('sponsors', '')}\n"
        f"- Agenda: {event_data.get('agenda', '')}\n"
        f"- Additional Notes: {event_data.get('notes', '')}"
    )

    payload = {
        "model": VISION_MODEL,
        "messages": [
            {"role": "system", "content": VISION_PROMPT},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": event_context},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/jpeg;base64,{base64_image}"
                        },
                    },
                ],
            },
        ],
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    try:
        async with httpx.AsyncClient(timeout=45) as client:
            response = await client.post(OPENROUTER_URL, headers=headers, json=payload)
            response.raise_for_status()
        data = response.json()
        content = (
            data.get("choices", [{}])[0]
            .get("message", {})
            .get("content", "")
            .strip()
        )
        if not content:
            session_state.append_log("Vision error: empty description received from OpenRouter.")
            return None
        return content
    except Exception as exc:
        session_state.append_log(f"Vision API error: {exc}")
        return None
