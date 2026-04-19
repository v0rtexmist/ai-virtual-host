import { useEffect, useRef } from "react";

function CameraIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M7 7h3l1.2-2h1.6L14 7h3a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V9a2 2 0 0 1 2-2Z" />
      <circle cx="12" cy="13" r="3.5" />
    </svg>
  );
}

function BrainIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M9 4a3 3 0 0 0-3 3v1.2A3.8 3.8 0 0 0 4 11.6c0 1.3.7 2.5 1.8 3.1A4 4 0 0 0 9 20h1v-8H9V4Zm6 0h-1v8h1a2 2 0 0 1 0 4h-1v4h1a4 4 0 0 0 3.2-5.3 3.8 3.8 0 0 0 1.8-3.1A3.8 3.8 0 0 0 18 8.2V7a3 3 0 0 0-3-3Z" />
    </svg>
  );
}

function SpeakerIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M5 10h4l5-4v12l-5-4H5z" />
      <path d="M17 9a4 4 0 0 1 0 6" />
      <path d="M19.5 6.5a7.5 7.5 0 0 1 0 11" />
    </svg>
  );
}

function WarningIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M12 3 2.7 19h18.6L12 3Z" />
      <path d="M12 9v5" />
      <circle cx="12" cy="17" r="1" />
    </svg>
  );
}

function chooseIcon(message) {
  const lowered = message.toLowerCase();
  if (
    lowered.includes("error") ||
    lowered.includes("failed") ||
    lowered.includes("aborted") ||
    lowered.includes("warning") ||
    lowered.includes("stopped")
  ) {
    return WarningIcon;
  }
  if (lowered.includes("captured image") || lowered.includes("camera")) {
    return CameraIcon;
  }
  if (
    lowered.includes("description") ||
    lowered.includes("vision") ||
    lowered.includes("llama")
  ) {
    return BrainIcon;
  }
  if (
    lowered.includes("audio") ||
    lowered.includes("elevenlabs") ||
    lowered.includes("playback")
  ) {
    return SpeakerIcon;
  }
  return WarningIcon;
}

function LogFeed({ entries }) {
  const containerRef = useRef(null);

  useEffect(() => {
    if (containerRef.current) {
      containerRef.current.scrollTop = 0;
    }
  }, [entries]);

  return (
    <div className="log-feed" ref={containerRef}>
      {entries.length > 0 ? (
        entries.map((entry, index) => {
          const Icon = chooseIcon(entry.message);
          return (
            <article className="log-entry" key={`${entry.timestamp}-${index}`}>
              <div className="log-icon">
                <Icon />
              </div>
              <div className="log-copy">
                <time>{new Date(entry.timestamp).toLocaleTimeString()}</time>
                <p>{entry.message}</p>
              </div>
            </article>
          );
        })
      ) : (
        <div className="empty-state">Live logs will appear here once the session starts.</div>
      )}
    </div>
  );
}

export default LogFeed;
