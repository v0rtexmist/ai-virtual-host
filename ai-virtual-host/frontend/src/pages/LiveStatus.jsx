import { useEffect, useRef, useState } from "react";

import { createStatusSocket, getStatus, stopSession } from "../api";

const FORM_KEY = "ai-virtual-host-form";
const SPEAKING_WINDOW_MS = 1200;

const STATUS_DEFAULTS = {
  event_data: {},
  kickoff_state: "idle",
  last_agent_response: "",
  conversation_id: "",
  audio_diagnosis: "",
  agent_text_only: false,
  agent_client_events: [],
  agent_voice_id: "",
  agent_first_message_status: "not_checked",
  agent_preflight_status: "unknown",
  audio_events_received: 0,
  audio_bytes_received: 0,
  last_audio_event_at: "",
  audio_output_device: "",
  recent_elevenlabs_events: [],
};

const moodOptions = [
  { value: "warm", title: "warm", desc: "candlelight - intimate" },
  { value: "playful", title: "playful", desc: "bubbly - party energy" },
  { value: "sharp", title: "sharp", desc: "witty - networking" },
  { value: "ember", title: "ember", desc: "late night - close gathering" },
];

function getStoredForm() {
  const stored = window.localStorage.getItem(FORM_KEY);
  if (!stored) {
    return {};
  }

  try {
    return JSON.parse(stored);
  } catch {
    return {};
  }
}

function extractDescription(message) {
  const prefix = "Crowd description received:";
  if (message.startsWith(prefix)) {
    return message.slice(prefix.length).trim();
  }
  return "";
}

function extractAgentResponse(message) {
  const prefixes = ["Agent response corrected:", "Agent response:"];
  for (const prefix of prefixes) {
    if (message.startsWith(prefix)) {
      return message.slice(prefix.length).trim();
    }
  }
  return "";
}

function extractOutputDevice(message) {
  const prefix = "Using audio output device:";
  if (message.startsWith(prefix)) {
    return message.slice(prefix.length).trim().replace(/\.$/, "");
  }
  return "";
}

function inferErrorFromLog(message) {
  const lowered = message.toLowerCase();
  if (
    lowered.includes("error") ||
    lowered.includes("failed") ||
    lowered.includes("aborted") ||
    lowered.includes("unable to") ||
    lowered.includes("session stopping")
  ) {
    return message;
  }
  return "";
}

function buildCrowdPlaceholder(kickoffState) {
  switch (kickoffState) {
    case "waiting_for_opening":
      return "Waiting for the dashboard-configured opening commentary to begin.";
    case "first_snapshot_buffered":
      return "The first crowd snapshot is buffered until opening commentary begins.";
    case "agent_text_received":
      return "Agent text arrived. Waiting for first audio packets.";
    case "opening_live":
      return "Opening commentary is live. Crowd updates are still buffered.";
    case "fallback_sent":
      return "A fallback kickoff message was sent because opening audio was delayed.";
    case "opening_complete":
      return "Opening turn complete. Crowd updates can now flow.";
    case "audio_received":
      return "Opening commentary audio is live.";
    case "reconnecting":
      return "Reconnecting before crowd updates resume.";
    default:
      return "Waiting for the first crowd snapshot.";
  }
}

function buildKickoffSummary(kickoffState, lastAgentResponse) {
  if (lastAgentResponse) {
    return lastAgentResponse;
  }

  switch (kickoffState) {
    case "waiting_for_opening":
      return "waiting for the first spoken line from the ElevenLabs agent.";
    case "first_snapshot_buffered":
      return "first crowd snapshot is held back until the host opens.";
    case "agent_text_received":
      return "text arrived, but audio has not reached the output device yet.";
    case "opening_live":
      return "opening commentary is speaking now.";
    case "fallback_sent":
      return "fallback kickoff sent with the full event details.";
    case "opening_complete":
      return "opening complete. the room can start feeding in.";
    case "audio_received":
      return "audio is reaching the speaker output.";
    case "reconnecting":
      return "reconnecting to ElevenLabs.";
    default:
      return "ready when the room is.";
  }
}

function buildAgentConfigSummary(diagnostics) {
  if (diagnostics.agent_preflight_status === "permission_unavailable") {
    return "convai_read permission is missing, so deep agent diagnostics are unavailable.";
  }
  if (diagnostics.agent_text_only) {
    return "agent reports text-only mode. Voice playback may not start.";
  }
  if (!diagnostics.agent_voice_id) {
    return "waiting for a configured ElevenLabs voice.";
  }
  if (!diagnostics.agent_client_events.includes("audio")) {
    return "audio client events are not enabled on the ElevenLabs agent.";
  }
  return "agent configuration is ready for voice playback.";
}

function buildAudioDiagnosisSummary(audioDiagnosis) {
  switch (audioDiagnosis) {
    case "insufficient_api_permissions":
      return "diagnosis unavailable: missing convai_read permission.";
    case "agent_text_only_mode":
      return "agent is configured for text-only mode.";
    case "agent_generated_text_but_no_response_audio":
      return "agent produced text, but ElevenLabs reports no response audio.";
    case "response_audio_exists_but_websocket_stream_missing":
      return "response audio exists, but it did not reach this WebSocket stream.";
    case "audio_stream_received_but_playback_failed":
      return "audio reached the backend, but local playback failed.";
    case "conversation_diagnosis_unavailable":
      return "conversation detail was not available for audio diagnosis.";
    default:
      return "no active audio issue.";
  }
}

function formatKickoffLabel(kickoffState) {
  switch (kickoffState) {
    case "waiting_for_opening":
      return "waiting";
    case "first_snapshot_buffered":
      return "buffered";
    case "agent_text_received":
      return "text only";
    case "opening_live":
      return "speaking";
    case "fallback_sent":
      return "fallback";
    case "opening_complete":
      return "open";
    case "audio_received":
      return "audio live";
    case "reconnecting":
      return "reconnecting";
    default:
      return "present";
  }
}

function formatBytes(byteCount) {
  if (!byteCount) {
    return "0 B";
  }
  if (byteCount < 1024) {
    return `${byteCount} B`;
  }
  if (byteCount < 1024 * 1024) {
    return `${(byteCount / 1024).toFixed(1)} KB`;
  }
  return `${(byteCount / (1024 * 1024)).toFixed(1)} MB`;
}

function formatVoiceId(voiceId) {
  if (!voiceId) {
    return "agent default";
  }
  if (voiceId.length <= 18) {
    return voiceId;
  }
  return `${voiceId.slice(0, 8)}...${voiceId.slice(-6)}`;
}

function getOrbMode({ sessionActive, connectionState, diagnostics, isSpeaking }) {
  if (!sessionActive) {
    return "idle";
  }
  if (isSpeaking) {
    return "speaking";
  }
  if (
    connectionState === "reconnecting" ||
    diagnostics.kickoff_state === "reconnecting"
  ) {
    return "thinking";
  }
  if (
    diagnostics.kickoff_state === "waiting_for_opening" ||
    diagnostics.kickoff_state === "first_snapshot_buffered" ||
    diagnostics.kickoff_state === "agent_text_received" ||
    diagnostics.kickoff_state === "opening_live" ||
    diagnostics.kickoff_state === "audio_received"
  ) {
    return "listening";
  }
  return "thinking";
}

function SidDefs() {
  return (
    <svg width="0" height="0" className="sid-defs" aria-hidden="true">
      <defs>
        <radialGradient id="blobGrad" cx="36%" cy="30%" r="85%">
          <stop offset="0%" stopColor="var(--blob-a)" />
          <stop offset="48%" stopColor="var(--blob-b)" />
          <stop offset="100%" stopColor="var(--blob-c)" />
        </radialGradient>
        <radialGradient id="blobHighlight" cx="50%" cy="50%" r="50%">
          <stop offset="0%" stopColor="rgba(255,255,255,0.65)" />
          <stop offset="55%" stopColor="rgba(255,255,255,0.14)" />
          <stop offset="100%" stopColor="rgba(255,255,255,0)" />
        </radialGradient>
      </defs>
    </svg>
  );
}

function SidOrb({ mode, ringCount }) {
  const stageRef = useRef(null);
  const faceRef = useRef(null);
  const cursorRef = useRef(null);
  const gazeRef = useRef({
    ex: 0,
    ey: 0,
    tx: 0,
    ty: 0,
    lastMoveAt: 0,
    wanderAt: 0,
    wanderX: 0,
    wanderY: 0,
  });

  useEffect(() => {
    let animationFrame = 0;

    function updateFace(now) {
      const gaze = gazeRef.current;
      if (now - gaze.lastMoveAt > 2000 && now > gaze.wanderAt) {
        gaze.wanderX = (Math.random() - 0.5) * 24;
        gaze.wanderY = (Math.random() - 0.5) * 18;
        gaze.wanderAt = now + 1800 + Math.random() * 2600;
      }

      if (now - gaze.lastMoveAt > 2000) {
        gaze.tx = gaze.tx * 0.95 + gaze.wanderX * 0.05;
        gaze.ty = gaze.ty * 0.95 + gaze.wanderY * 0.05;
      }

      gaze.ex += (gaze.tx - gaze.ex) * 0.12;
      gaze.ey += (gaze.ty - gaze.ey) * 0.12;

      if (faceRef.current) {
        faceRef.current.style.transform = `translate(${gaze.ex}px, ${gaze.ey}px)`;
      }

      animationFrame = window.requestAnimationFrame(updateFace);
    }

    function handlePointerMove(event) {
      if (!stageRef.current) {
        return;
      }

      const rect = stageRef.current.getBoundingClientRect();
      const centerX = rect.left + rect.width / 2;
      const centerY = rect.top + rect.height / 2;
      const dx = event.clientX - centerX;
      const dy = event.clientY - centerY;
      const gaze = gazeRef.current;
      gaze.tx = Math.max(-9, Math.min(9, dx * 0.06));
      gaze.ty = Math.max(-9, Math.min(9, dy * 0.06));
      gaze.lastMoveAt = performance.now();

      if (cursorRef.current) {
        const distance = Math.sqrt(dx * dx + dy * dy);
        cursorRef.current.style.left = `${event.clientX}px`;
        cursorRef.current.style.top = `${event.clientY}px`;
        cursorRef.current.classList.toggle("show", distance < rect.width / 2 + 28);
        cursorRef.current.classList.toggle("active", distance < rect.width / 2 + 28);
      }
    }

    window.addEventListener("pointermove", handlePointerMove);
    animationFrame = window.requestAnimationFrame(updateFace);

    return () => {
      window.removeEventListener("pointermove", handlePointerMove);
      window.cancelAnimationFrame(animationFrame);
    };
  }, []);

  const rings = Array.from({ length: Math.max(1, Math.min(6, ringCount || 1)) });

  return (
    <>
      <div className={`orb-stage orb-state-${mode}`} ref={stageRef}>
        <div className="aura-stack">
          <div className="aurora-halo" />
          <div className="aura-rings">
            {rings.map((_, index) => (
              <div
                className="aura-ring"
                key={index}
                style={{ animationDelay: `${index * 0.7}s` }}
              />
            ))}
          </div>
        </div>
        <div className="orb-glow" />
        <div className="listen-pulse" />
        <div className="ripples">
          <div className="ripple r1" />
          <div className="ripple r2" />
          <div className="ripple r3" />
        </div>
        <div className="orb-body">
          <div className="orb">
            <svg className="sid-blob" viewBox="-150 -150 300 300" aria-hidden="true">
              <circle className="body" cx="0" cy="0" r="78" fill="url(#blobGrad)" />
              <ellipse
                className="blob-shine"
                cx="-24"
                cy="-34"
                rx="30"
                ry="22"
                fill="url(#blobHighlight)"
                opacity=".9"
              />
            </svg>
            <div className="orb-face" ref={faceRef}>
              <div className="eye left" />
              <div className="eye right" />
            </div>
          </div>
          <div className="orb-floor" />
        </div>
      </div>
      <div className="custom-cursor" ref={cursorRef} />
    </>
  );
}

function LiveStatus() {
  const [storedForm] = useState(getStoredForm);
  const [lastDescription, setLastDescription] = useState(
    "Waiting for the first crowd snapshot."
  );
  const [banner, setBanner] = useState("");
  const [connectionState, setConnectionState] = useState("connecting");
  const [sessionActive, setSessionActive] = useState(true);
  const [sessionEnded, setSessionEnded] = useState(false);
  const [statusError, setStatusError] = useState("");
  const [diagnostics, setDiagnostics] = useState(STATUS_DEFAULTS);
  const [eventData, setEventData] = useState(storedForm);
  const [mood, setMood] = useState(storedForm.mood || "warm");
  const [moodOpen, setMoodOpen] = useState(false);
  const [isStopping, setIsStopping] = useState(false);
  const [speakingUntil, setSpeakingUntil] = useState(0);
  const [now, setNow] = useState(() => Date.now());
  const audioActivityRef = useRef({
    initialized: false,
    count: 0,
    lastAt: "",
  });
  const reconnectTimerRef = useRef(null);
  const socketRef = useRef(null);
  const stoppedByOperatorRef = useRef(false);

  useEffect(() => {
    document.body.dataset.mood = mood || "warm";
  }, [mood]);

  useEffect(() => {
    const timer = window.setInterval(() => {
      setNow(Date.now());
    }, 180);

    return () => {
      window.clearInterval(timer);
    };
  }, []);

  function markSpeakingActivity(activity, animateInitial = false) {
    const previous = audioActivityRef.current;
    const nextCount = Number(activity.audio_events_received || 0);
    const nextLastAt = activity.last_audio_event_at || "";
    const hasCountChange = nextCount > previous.count;
    const hasTimestampChange = Boolean(nextLastAt && nextLastAt !== previous.lastAt);
    const shouldAnimate =
      (previous.initialized && (hasCountChange || hasTimestampChange)) ||
      (!previous.initialized && animateInitial && (nextCount > 0 || nextLastAt));

    audioActivityRef.current = {
      initialized: true,
      count: Math.max(previous.count, nextCount),
      lastAt: nextLastAt || previous.lastAt,
    };

    if (shouldAnimate) {
      setSpeakingUntil(Date.now() + SPEAKING_WINDOW_MS);
    }
  }

  function applyStatus(status) {
    const nextDiagnostics = {
      event_data: status.event_data || {},
      kickoff_state: status.kickoff_state || "idle",
      last_agent_response: status.last_agent_response || "",
      conversation_id: status.conversation_id || "",
      audio_diagnosis: status.audio_diagnosis || "",
      agent_text_only: Boolean(status.agent_text_only),
      agent_client_events: Array.isArray(status.agent_client_events)
        ? status.agent_client_events
        : [],
      agent_voice_id: status.agent_voice_id || "",
      agent_first_message_status: status.agent_first_message_status || "not_checked",
      agent_preflight_status: status.agent_preflight_status || "unknown",
      audio_events_received: Number(status.audio_events_received || 0),
      audio_bytes_received: Number(status.audio_bytes_received || 0),
      last_audio_event_at: status.last_audio_event_at || "",
      audio_output_device: status.audio_output_device || "",
      recent_elevenlabs_events: Array.isArray(status.recent_elevenlabs_events)
        ? status.recent_elevenlabs_events
        : [],
    };

    markSpeakingActivity(nextDiagnostics);
    setDiagnostics(nextDiagnostics);
    setStatusError(status.last_error || "");
    setSessionActive(Boolean(status.is_running));

    if (status.event_data && Object.keys(status.event_data).length > 0) {
      setEventData((current) => ({ ...current, ...status.event_data }));
    }

    if (status.last_description) {
      setLastDescription(status.last_description);
    } else if (status.is_running) {
      setLastDescription(buildCrowdPlaceholder(nextDiagnostics.kickoff_state));
    } else {
      setLastDescription("Waiting for the first crowd snapshot.");
    }
  }

  useEffect(() => {
    let mounted = true;

    async function hydrate() {
      try {
        const status = await getStatus();
        if (!mounted) {
          return;
        }

        applyStatus(status);

        if (!status.is_running) {
          setConnectionState("idle");
        }
      } catch (err) {
        if (mounted) {
          setBanner(err.message || "Unable to load live status.");
          setConnectionState("reconnecting");
        }
      }
    }

    hydrate();

    return () => {
      mounted = false;
    };
  }, []);

  useEffect(() => {
    const timer = window.setInterval(async () => {
      try {
        const status = await getStatus();
        applyStatus(status);
      } catch {
        // The WebSocket lifecycle drives the reconnect UX. Polling is only a fallback.
      }
    }, 3000);

    return () => {
      window.clearInterval(timer);
    };
  }, []);

  useEffect(() => {
    function connectSocket() {
      if (stoppedByOperatorRef.current) {
        return;
      }

      setConnectionState("connecting");
      const socket = createStatusSocket();
      socketRef.current = socket;

      socket.onopen = () => {
        setConnectionState("connected");
        setBanner("");
      };

      socket.onmessage = (event) => {
        try {
          const message = JSON.parse(event.data);
          if (message.type === "status_snapshot") {
            applyStatus(message);
            return;
          }

          if (message.type === "audio_activity") {
            markSpeakingActivity(message, true);
            setDiagnostics((current) => ({
              ...current,
              audio_events_received: Number(message.audio_events_received || 0),
              audio_bytes_received: Number(message.audio_bytes_received || 0),
              last_audio_event_at: message.last_audio_event_at || "",
              kickoff_state:
                current.kickoff_state === "reconnecting"
                  ? current.kickoff_state
                  : "audio_received",
            }));
            return;
          }

          if (message.type === "log") {
            const description = extractDescription(message.message);
            const agentResponse = extractAgentResponse(message.message);
            const outputDevice = extractOutputDevice(message.message);
            const lowered = message.message.toLowerCase();
            const inferredError = inferErrorFromLog(message.message);

            if (description) {
              setLastDescription(description);
            }
            if (agentResponse) {
              setDiagnostics((current) => ({
                ...current,
                last_agent_response: agentResponse,
              }));
            }
            if (outputDevice) {
              setDiagnostics((current) => ({
                ...current,
                audio_output_device: outputDevice,
              }));
            }
            if (lowered.includes("launch requested")) {
              setSessionActive(true);
              setSessionEnded(false);
              setDiagnostics((current) => ({
                ...current,
                kickoff_state: "connecting",
              }));
            }
            if (lowered.includes("sent elevenlabs dynamic variables")) {
              setDiagnostics((current) => ({
                ...current,
                kickoff_state: "waiting_for_opening",
              }));
            }
            if (lowered.includes("first crowd snapshot buffered")) {
              setDiagnostics((current) => ({
                ...current,
                kickoff_state:
                  current.kickoff_state === "agent_text_received"
                    ? current.kickoff_state
                    : "first_snapshot_buffered",
              }));
            }
            if (lowered.includes("opening agent text received")) {
              setDiagnostics((current) => ({
                ...current,
                kickoff_state: "agent_text_received",
              }));
            }
            if (
              lowered.includes(
                "sending kickoff message to elevenlabs (opening fallback)"
              ) ||
              lowered.includes("fallback message sent")
            ) {
              setDiagnostics((current) => ({
                ...current,
                kickoff_state: "fallback_sent",
              }));
            }
            if (
              lowered.includes("first audio packet received") ||
              lowered.includes("opening commentary is live")
            ) {
              setDiagnostics((current) => ({
                ...current,
                kickoff_state: "opening_live",
              }));
            }
            if (lowered.includes("opening host commentary finished")) {
              setDiagnostics((current) => ({
                ...current,
                kickoff_state: "opening_complete",
              }));
            }
            if (lowered.includes("auto-reconnect triggered")) {
              setDiagnostics((current) => ({
                ...current,
                kickoff_state: "reconnecting",
              }));
            }
            if (inferredError) {
              setStatusError(inferredError);
            }
            if (
              lowered.includes("connection failed") ||
              lowered.includes("session stopping") ||
              lowered.includes("camera loop aborted")
            ) {
              setSessionActive(false);
            }
            return;
          }

          if (message.type === "session_stopped") {
            stoppedByOperatorRef.current = true;
            setSessionEnded(true);
            setSessionActive(false);
            setConnectionState("stopped");
            setBanner("The session was stopped by the operator.");
            socket.close();
          }
        } catch {
          setBanner("Received an unreadable live status message.");
        }
      };

      socket.onclose = () => {
        if (stoppedByOperatorRef.current) {
          return;
        }
        setConnectionState("reconnecting");
        reconnectTimerRef.current = window.setTimeout(connectSocket, 5000);
      };

      socket.onerror = () => {
        setConnectionState("reconnecting");
      };
    }

    connectSocket();

    return () => {
      stoppedByOperatorRef.current = true;
      if (reconnectTimerRef.current) {
        window.clearTimeout(reconnectTimerRef.current);
      }
      if (socketRef.current && socketRef.current.readyState < 2) {
        socketRef.current.close();
      }
    };
  }, []);

  async function handleStop() {
    setIsStopping(true);
    setStatusError("");
    setBanner("");
    try {
      await stopSession();
      setSessionActive(false);
      setSessionEnded(true);
      setConnectionState("stopped");
      setBanner("The session was stopped by the operator.");
    } catch (err) {
      setStatusError(err.message || "Unable to stop session.");
      setBanner(err.message || "Unable to stop session.");
    } finally {
      setIsStopping(false);
    }
  }

  const personaName =
    eventData.persona_name || storedForm.persona_name || "AI Virtual Host";
  const eventName = eventData.event_name || storedForm.event_name || "your event";
  const hosts = (eventData.hosts || storedForm.hosts || "")
    .split(",")
    .map((host) => host.trim())
    .filter(Boolean);
  const roomCount = hosts.length || (sessionActive ? 1 : 0);
  const isSpeaking = now < speakingUntil;
  const orbMode = getOrbMode({
    sessionActive,
    connectionState,
    diagnostics,
    isSpeaking,
  });
  const vibeLabel = sessionActive
    ? formatKickoffLabel(diagnostics.kickoff_state)
    : "quiet";
  const stateBadge = sessionEnded
    ? "stopped"
    : sessionActive
      ? formatKickoffLabel(diagnostics.kickoff_state)
      : "idle";

  let headerState = "connecting";
  if (sessionEnded) {
    headerState = "session ended";
  } else if (!sessionActive) {
    headerState = "waiting for launch";
  } else if (
    connectionState === "reconnecting" ||
    diagnostics.kickoff_state === "reconnecting"
  ) {
    headerState = "reconnecting";
  } else if (orbMode === "speaking") {
    headerState = "live";
  } else if (connectionState === "connected") {
    headerState = "opening";
  }

  return (
    <div className="sid-shell live-view">
      <div className="ambient" aria-hidden="true" />
      <div className="grain" aria-hidden="true" />
      <SidDefs />

      <div className="app active">
        <header className="sid-header">
          <div className="mark">
            <span className="dot" />
            <span>the virtual host</span>
            <small>- {stateBadge}</small>
          </div>

          <div className="hdr-r">
            <div className="chip room-chip">
              <span className="room-dots" aria-hidden="true">
                {Array.from({ length: Math.min(3, Math.max(1, roomCount)) }).map(
                  (_, index) => (
                    <span className="room-dot" key={index} />
                  )
                )}
              </span>
              <span>
                <b>{roomCount}</b> host{roomCount === 1 ? "" : "s"}
              </span>
            </div>
            <a className="chip" href="/logs">
              logs
            </a>
            <a className="chip" href="/">
              setup
            </a>
            <button
              className="chip danger-chip"
              type="button"
              onClick={handleStop}
              disabled={isStopping}
            >
              {isStopping ? "stopping" : "stop"}
            </button>

            <div className="mood-menu">
              <button
                className="chip"
                type="button"
                onClick={() => setMoodOpen((current) => !current)}
              >
                <span className="swatch" />
                <span>{mood}</span>
                <svg
                  width="10"
                  height="10"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2.2"
                  strokeLinecap="round"
                  aria-hidden="true"
                >
                  <polyline points="6 9 12 15 18 9" />
                </svg>
              </button>
              <div className={`mood-drop ${moodOpen ? "open" : ""}`}>
                {moodOptions.map((option) => (
                  <button
                    className="mood-opt"
                    data-mood={option.value}
                    key={option.value}
                    onClick={() => {
                      setMood(option.value);
                      setMoodOpen(false);
                    }}
                    type="button"
                  >
                    <span className="msw" />
                    <span>
                      <strong>{option.title}</strong>
                      <span className="desc">{option.desc}</span>
                    </span>
                  </button>
                ))}
              </div>
            </div>
          </div>
        </header>

        <main className="live-main">
          <div className="name-wrap">
            <div className="name-label">tonight, you are with</div>
            <h1 className="name">{personaName}</h1>
            <div className="tagline">{eventName}</div>
          </div>

          <SidOrb mode={orbMode} ringCount={roomCount} />

          <div className="vibe-wrap">
            <span className="vibe-dot" />
            <span>
              the room is <em>{vibeLabel}</em>
            </span>
          </div>

          {banner ? <div className="info-banner floating-banner">{banner}</div> : null}
        </main>

        <div className="bottom">
          <div className="quicks">
            <div className="quick live-pill">
              <span>state</span>
              <strong>{headerState}</strong>
            </div>
            <div className="quick live-pill">
              <span>audio packets</span>
              <strong>{diagnostics.audio_events_received}</strong>
            </div>
            <div className="quick live-pill">
              <span>audio bytes</span>
              <strong>{formatBytes(diagnostics.audio_bytes_received)}</strong>
            </div>
            <div
              className="quick live-pill"
              title={diagnostics.agent_voice_id || "Using the ElevenLabs agent default voice"}
            >
              <span>voice</span>
              <strong>{formatVoiceId(diagnostics.agent_voice_id)}</strong>
            </div>
            <a className="quick" href="/logs">
              open logs
            </a>
          </div>

          <section className="live-panels" aria-label="Live session details">
            <article className="glass-panel">
              <span className="panel-label">current crowd snapshot</span>
              <p>{lastDescription || buildCrowdPlaceholder(diagnostics.kickoff_state)}</p>
            </article>
            <article className="glass-panel">
              <span className="panel-label">audio output</span>
              <p>{diagnostics.audio_output_device || "Waiting for output device."}</p>
            </article>
            <article className="glass-panel">
              <span className="panel-label">host signal</span>
              <p>
                {sessionActive
                  ? "Sid is watching the room and will react when fresh voice audio arrives."
                  : "Launch a session from setup when you are ready."}
              </p>
            </article>
          </section>

          <div className="input-footer live-footer">
            <span className={`api-dot ${sessionActive ? "live" : ""}`}>
              <span>{connectionState}</span>
            </span>
            <span>
              conversation: {diagnostics.conversation_id || "waiting"}
              {diagnostics.recent_elevenlabs_events.length > 0
                ? ` | ${diagnostics.recent_elevenlabs_events.join(" -> ")}`
                : ""}
            </span>
          </div>
        </div>
      </div>
    </div>
  );
}

export default LiveStatus;
