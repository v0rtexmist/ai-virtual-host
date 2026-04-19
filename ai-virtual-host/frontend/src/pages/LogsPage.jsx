import { useEffect, useRef, useState } from "react";

import LogFeed from "../components/LogFeed";
import { createStatusSocket, getLogs } from "../api";

const FORM_KEY = "ai-virtual-host-form";

function getStoredMood() {
  const stored = window.localStorage.getItem(FORM_KEY);
  if (!stored) {
    return "warm";
  }

  try {
    return JSON.parse(stored).mood || "warm";
  } catch {
    return "warm";
  }
}

function LogsPage() {
  const [entries, setEntries] = useState([]);
  const [banner, setBanner] = useState("");
  const [connectionState, setConnectionState] = useState("connecting");
  const reconnectTimerRef = useRef(null);
  const socketRef = useRef(null);
  const stoppedByOperatorRef = useRef(false);

  useEffect(() => {
    document.body.dataset.mood = getStoredMood();
  }, []);

  useEffect(() => {
    let mounted = true;

    async function hydrate() {
      try {
        const data = await getLogs(200);
        if (mounted) {
          setEntries([...(data.log || [])].reverse());
        }
      } catch (err) {
        if (mounted) {
          setBanner(err.message || "Unable to load logs.");
        }
      }
    }

    hydrate();

    return () => {
      mounted = false;
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
            if (Array.isArray(message.log)) {
              setEntries((current) =>
                current.length > 0 ? current : [...message.log].reverse()
              );
            }
            return;
          }

          if (message.type === "log") {
            setEntries((current) => [message, ...current].slice(0, 200));
            return;
          }

          if (message.type === "session_stopped") {
            setBanner("The session was stopped by the operator.");
            stoppedByOperatorRef.current = true;
            setConnectionState("stopped");
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

  return (
    <div className="sid-shell logs-view">
      <div className="ambient" aria-hidden="true" />
      <div className="grain" aria-hidden="true" />

      <main className="logs-screen">
        <section className="logs-hero">
          <div>
            <div className="setup-eyebrow">
              <span className="dot-sm" />
              live operations
            </div>
            <h1 className="setup-title">activity logs</h1>
            <p className="setup-sub">
              The operational feed now has its own page, with retained session
              history and live WebSocket updates.
            </p>
          </div>
          <div className="hdr-r logs-actions">
            <span className={`chip ${connectionState === "connected" ? "chip-live" : ""}`}>
              {connectionState}
            </span>
            <a className="chip" href="/live">
              live room
            </a>
            <a className="chip" href="/">
              setup
            </a>
          </div>
        </section>

        {banner ? <div className="info-banner">{banner}</div> : null}

        <section className="logs-panel">
          <div className="card-heading">
            <span>latest events</span>
            <span className="feed-indicator">{entries.length} retained</span>
          </div>
          <LogFeed entries={entries} />
        </section>
      </main>
    </div>
  );
}

export default LogsPage;
