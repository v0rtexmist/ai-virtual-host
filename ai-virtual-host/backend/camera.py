from __future__ import annotations

import asyncio
import base64
import os

import cv2

from .elevenlabs_ws import elevenlabs_manager
from .session import session_state
from .vision import describe_image

CAMERA_INDEX = int(os.getenv("CAMERA_INDEX", "0"))
IMAGE_CAPTURE_INTERVAL = int(os.getenv("IMAGE_CAPTURE_INTERVAL", "60"))


def _capture_frame_blocking() -> str | None:
    camera = cv2.VideoCapture(CAMERA_INDEX)
    if not camera.isOpened():
        return None

    try:
        ok, frame = camera.read()
        if not ok:
            return None
        ok, encoded = cv2.imencode(".jpg", frame)
        if not ok:
            return None
        return base64.b64encode(encoded.tobytes()).decode("ascii")
    finally:
        camera.release()


async def capture_frame() -> str | None:
    return await asyncio.to_thread(_capture_frame_blocking)


async def run_camera_loop() -> None:
    wait_started = asyncio.get_running_loop().time()
    while session_state.is_running and not session_state.elevenlabs_connected:
        if asyncio.get_running_loop().time() - wait_started >= 15:
            message = (
                "Camera loop aborted: ElevenLabs connection was not confirmed within 15 seconds."
            )
            session_state.set_error(message)
            session_state.append_log(message)
            session_state.is_running = False
            return
        await asyncio.sleep(1)

    while session_state.is_running:
        try:
            image = await capture_frame()
            if not image:
                message = (
                    f"Camera error: unable to capture image from camera index {CAMERA_INDEX}."
                )
                session_state.set_error(message)
                session_state.append_log(message)
            else:
                session_state.append_log("Camera captured image.")
                description = await describe_image(image, session_state.event_data)
                if description:
                    session_state.last_image_description = description
                    session_state.append_log(
                        f"Crowd description received: {description}"
                    )
                    await elevenlabs_manager.feed_description(description)
        except Exception as exc:
            message = f"Camera loop error: {exc}"
            session_state.set_error(message)
            session_state.append_log(message)

        if not session_state.is_running:
            break
        await asyncio.sleep(IMAGE_CAPTURE_INTERVAL)