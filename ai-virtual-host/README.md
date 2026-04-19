# AI Virtual Host

AI Virtual Host is a full-stack event tool that watches the audience through a laptop camera, summarizes the crowd with Llama 4 Maverick through OpenRouter, and forwards meaningful live updates into an ElevenLabs Conversational AI agent that speaks commentary through the laptop speakers before the main host takes the stage.

## Prerequisites

- Python 3.11+
- Node 18+
- A working laptop camera
- Speakers or headphones connected to the machine running the app
- OpenRouter and ElevenLabs credentials

## Setup

1. Clone this project and open the `ai-virtual-host` folder.
2. Fill in the root `.env` file with your OpenRouter and ElevenLabs credentials.
3. Install backend dependencies:

```powershell
cd ai-virtual-host\backend
python -m pip install -r requirements.txt
```

4. Install frontend dependencies:

```powershell
cd ..\frontend
npm.cmd install
```

5. Run the backend from the project root:

```powershell
cd ..
uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000
```

6. Run the frontend:

```powershell
cd frontend
npm.cmd run dev
```

The frontend will be available at `http://localhost:5173`, and the backend will run at `http://localhost:8000`.

## ElevenLabs Agent Configuration

Configure the agent persona and commentary behavior inside ElevenLabs itself. Use [elevenlabs_agent_system_prompt.md](./elevenlabs_agent_system_prompt.md) as the starting point for your agent prompt and first message. The application never reads that file directly.

Important:

- The backend now sends runtime `dynamic_variables` named `persona_name`, `event_name`, `event_description`, `hosts`, `sponsors`, `agenda`, and `notes`.
- Your ElevenLabs dashboard prompt and first message should reference those placeholders directly, for example `{{event_name}}` and `{{hosts}}`.
- Disable text-only chat mode for this agent.
- Make sure the agent's client events include `audio`.
- If your ElevenLabs API key also has `convai_read`, the app can preflight-check the agent and diagnose missing audio more deeply. Without that permission, launch still works, but advanced diagnostics are limited.
- Do not rely on code-side prompt or first-message overrides unless you explicitly enable them in the ElevenLabs agent security settings.

## How To Use

1. Open the main page at `http://localhost:5173/`.
2. Fill in the event details form.
3. Click `LAUNCH` to start the ElevenLabs connection and open the `/live` monitor page in a new tab.
4. Watch the `Live` page to track crowd descriptions and system events in real time.
5. Click `STOP` on the main page when the pre-show hosting session should end.

## Troubleshooting

### ElevenLabs connection fails

- Confirm `ELEVENLABS_AGENT_ID` and `ELEVENLABS_API_KEY` are correct in `.env`.
- Verify the agent exists and is enabled in ElevenLabs.
- Make sure the ElevenLabs agent prompt and first message use the dynamic variables listed in [elevenlabs_agent_system_prompt.md](./elevenlabs_agent_system_prompt.md).
- If launch warns that `convai_read` is missing, the host can still run, but agent preflight and conversation-level audio diagnosis will be unavailable.
- If your agent rejects prompt overrides, that is expected with the current build because this app now relies on dynamic variables instead of prompt or first-message overrides.
- Make sure local firewalls allow outbound WebSocket connections.
- Check the Live Status log for handshake or reconnect errors.

### Camera not found

- Try changing `CAMERA_INDEX` in `.env` from `0` to another available device index.
- Confirm no other application is holding the camera.
- Make sure OpenCV can access the camera in your operating system permissions settings.

### No audio playback

- Verify the machine has an active default output device.
- Verify the ElevenLabs agent is not configured in text-only mode.
- Verify the ElevenLabs agent exposes `audio` in its client events and has a voice ID configured.
- Confirm the ElevenLabs handshake completed and negotiated an audio format in the log.
- Check the Live page for `Opening commentary`, `Audio packets`, `Audio bytes`, the detected `Output` device, the `Conversation` ID, and the `Diagnosis` summary.
- If you see agent text but `Audio packets: 0`, the agent is replying in text but audio is not arriving from ElevenLabs yet.
- If audio packets are arriving but you still hear nothing, check whether your sound output device supports the negotiated PCM sample rate.
