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

Required ElevenLabs values stay server-side in `.env`:

```powershell
ELEVENLABS_AGENT_ID=your_agent_id
ELEVENLABS_API_KEY=your_api_key
```

Optional default voice override:

```powershell
ELEVENLABS_VOICE_ID=2BsEFcU7jUhLaUwV4h7l
```

If you open the frontend from Vercel while the backend runs on your laptop, also allow that exact Vercel URL:

```powershell
FRONTEND_ORIGINS=https://your-vercel-app.vercel.app
```

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

## Vercel Frontend

Vercel can host the React frontend, but this backend controls your camera, speakers, and long-running ElevenLabs session, so it still needs to run on the machine at the event.

For the Vercel frontend to launch the local backend:

1. Add your Vercel app URL to `FRONTEND_ORIGINS` in `ai-virtual-host/.env`.
2. Start the backend locally with `uvicorn backend.main:app --host 127.0.0.1 --port 8000`.
3. Open the Vercel frontend in the same laptop browser.

If you deploy the backend somewhere else, set these Vercel environment variables before building the frontend:

```powershell
VITE_API_ORIGIN=https://your-backend.example.com
VITE_WS_ORIGIN=wss://your-backend.example.com
```

## ElevenLabs Agent Configuration

Configure the agent persona and commentary behavior inside ElevenLabs itself. Use [elevenlabs_agent_system_prompt.md](./elevenlabs_agent_system_prompt.md) as the starting point for your agent prompt and first message. The application never reads that file directly.

Important:

- The backend now sends runtime `dynamic_variables` named `persona_name`, `event_name`, `event_description`, `hosts`, `sponsors`, `agenda`, and `notes`.
- Your ElevenLabs dashboard prompt and first message should reference those placeholders directly, for example `{{event_name}}` and `{{hosts}}`.
- Disable text-only chat mode for this agent.
- Make sure the agent's client events include `audio`.
- The setup page defaults to the ElevenLabs voice ID `2BsEFcU7jUhLaUwV4h7l`.
- Enable the `Voice ID` override in the agent's Security settings. ElevenLabs will close the WebSocket with policy violation `1008` if this override is sent before that setting is enabled.
- If you do not want to enable runtime overrides, set `2BsEFcU7jUhLaUwV4h7l` as the agent's dashboard voice and clear the setup-page Voice ID field.
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
- If a launch fails with `Override for field 'voice_id' is not allowed by config`, enable Voice ID overrides in the agent's Security settings, or clear the Voice ID field and set that voice as the agent's dashboard voice.
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
