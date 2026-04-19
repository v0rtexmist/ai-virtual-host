import { useEffect, useState } from "react";

import StatusBadge from "../components/StatusBadge";
import { getStatus, launchSession, stopSession } from "../api";

const RUNNING_KEY = "ai-virtual-host-running";
const SESSION_SEEN_KEY = "ai-virtual-host-session-seen";
const FORM_KEY = "ai-virtual-host-form";

const emptyForm = {
  persona_name: "Sid",
  event_name: "",
  event_description: "",
  hosts: "",
  sponsors: "",
  agenda: "",
  notes: "",
  mood: "warm",
};

const moodOptions = [
  { value: "warm", label: "warm" },
  { value: "playful", label: "playful" },
  { value: "sharp", label: "sharp" },
  { value: "ember", label: "ember" },
];

function EventForm() {
  const [formData, setFormData] = useState(() => {
    const stored = window.localStorage.getItem(FORM_KEY);
    if (!stored) {
      return emptyForm;
    }

    try {
      return { ...emptyForm, ...JSON.parse(stored) };
    } catch {
      return emptyForm;
    }
  });
  const [phase, setPhase] = useState("idle");
  const [isRunning, setIsRunning] = useState(false);
  const [error, setError] = useState("");
  const [statusError, setStatusError] = useState("");
  const [isLaunching, setIsLaunching] = useState(false);
  const [isStopping, setIsStopping] = useState(false);

  useEffect(() => {
    document.body.dataset.mood = formData.mood || "warm";
  }, [formData.mood]);

  useEffect(() => {
    let active = true;

    async function hydrate() {
      try {
        const status = await getStatus();
        if (!active) {
          return;
        }

        if (status.is_running) {
          setIsRunning(true);
          setPhase(status.elevenlabs_connected ? "live" : "connecting");
          setStatusError(status.last_error || "");
          window.localStorage.setItem(RUNNING_KEY, "true");
          window.localStorage.setItem(SESSION_SEEN_KEY, "true");
        } else {
          const sessionSeen = window.localStorage.getItem(SESSION_SEEN_KEY) === "true";
          setIsRunning(false);
          setPhase(sessionSeen ? "stopped" : "idle");
          setStatusError(status.last_error || "");
          window.localStorage.setItem(RUNNING_KEY, "false");
        }
      } catch (err) {
        if (active) {
          setError(err.message || "Unable to load session status.");
        }
      }
    }

    hydrate();

    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    window.localStorage.setItem(FORM_KEY, JSON.stringify(formData));
  }, [formData]);

  useEffect(() => {
    if (!isRunning) {
      return undefined;
    }

    const timer = window.setInterval(async () => {
      try {
        const status = await getStatus();
        if (!status.is_running) {
          setIsRunning(false);
          setPhase("stopped");
          setStatusError(status.last_error || "");
          window.localStorage.setItem(RUNNING_KEY, "false");
          return;
        }
        setStatusError(status.last_error || "");
        setPhase(status.elevenlabs_connected ? "live" : "connecting");
      } catch (err) {
        setError(err.message || "Unable to refresh session status.");
      }
    }, 3000);

    return () => {
      window.clearInterval(timer);
    };
  }, [isRunning]);

  const isReadOnly = isRunning || isLaunching || isStopping;

  function handleChange(event) {
    const { name, value } = event.target;
    setFormData((current) => ({ ...current, [name]: value }));
  }

  function handleMoodChange(mood) {
    setFormData((current) => ({ ...current, mood }));
  }

  async function handleLaunch(event) {
    event.preventDefault();
    setError("");
    setIsLaunching(true);

    try {
      const { mood, ...launchPayload } = formData;
      await launchSession(launchPayload);
      setIsRunning(true);
      setPhase("connecting");
      setStatusError("");
      window.localStorage.setItem(RUNNING_KEY, "true");
      window.localStorage.setItem(SESSION_SEEN_KEY, "true");
      window.localStorage.setItem(FORM_KEY, JSON.stringify(formData));
      window.open("/live", "_blank", "noopener,noreferrer");
    } catch (err) {
      setError(err.message || "Unable to launch session.");
    } finally {
      setIsLaunching(false);
    }
  }

  async function handleStop() {
    setError("");
    setIsStopping(true);

    try {
      await stopSession();
      setIsRunning(false);
      setPhase("stopped");
      setStatusError("");
      window.localStorage.setItem(RUNNING_KEY, "false");
      window.localStorage.setItem(SESSION_SEEN_KEY, "true");
    } catch (err) {
      setError(err.message || "Unable to stop session.");
    } finally {
      setIsStopping(false);
    }
  }

  return (
    <div className="sid-shell setup-view">
      <div className="ambient" aria-hidden="true" />
      <div className="grain" aria-hidden="true" />

      <main className="setup-screen">
        <section className="setup-card">
          <div className="setup-topline">
            <div className="setup-eyebrow">
              <span className="dot-sm" />
              ai virtual host
            </div>
            <StatusBadge phase={phase} />
          </div>

          <h1 className="setup-title">set the stage</h1>
          <p className="setup-sub">
            Fill in your event details. Your host will be ready in seconds.
          </p>

          <form className="event-form" onSubmit={handleLaunch}>
            <div className="sf">
              <label className="sl" htmlFor="persona_name">
                host display name
              </label>
              <input
                className="si"
                id="persona_name"
                name="persona_name"
                value={formData.persona_name}
                onChange={handleChange}
                readOnly={isReadOnly}
                maxLength={32}
                placeholder="Sid"
              />
            </div>

            <div className="sf">
              <label className="sl" htmlFor="event_name">
                event name
              </label>
              <input
                className="si"
                id="event_name"
                name="event_name"
                value={formData.event_name}
                onChange={handleChange}
                required
                readOnly={isReadOnly}
                maxLength={80}
                placeholder="North Summit 2026"
              />
            </div>

            <div className="sf">
              <label className="sl" htmlFor="event_description">
                event description
              </label>
              <textarea
                className="sta"
                id="event_description"
                name="event_description"
                value={formData.event_description}
                onChange={handleChange}
                required
                readOnly={isReadOnly}
                rows={4}
                placeholder="Tell the host what this event is about."
              />
            </div>

            <div className="form-pair">
              <div className="sf">
                <label className="sl" htmlFor="hosts">
                  host names
                </label>
                <input
                  className="si"
                  id="hosts"
                  name="hosts"
                  value={formData.hosts}
                  onChange={handleChange}
                  required
                  readOnly={isReadOnly}
                  placeholder="Jamie Ortiz, Kira Stone"
                />
              </div>

              <div className="sf">
                <label className="sl" htmlFor="sponsors">
                  sponsors
                </label>
                <input
                  className="si"
                  id="sponsors"
                  name="sponsors"
                  value={formData.sponsors}
                  onChange={handleChange}
                  readOnly={isReadOnly}
                  placeholder="Comma separated sponsors"
                />
              </div>
            </div>

            <div className="sf">
              <label className="sl" htmlFor="agenda">
                agenda / schedule
              </label>
              <textarea
                className="sta"
                id="agenda"
                name="agenda"
                value={formData.agenda}
                onChange={handleChange}
                required
                readOnly={isReadOnly}
                rows={5}
                placeholder="Share the key moments you want the host to reference."
              />
            </div>

            <div className="sf">
              <label className="sl" htmlFor="notes">
                additional notes
              </label>
              <textarea
                className="sta"
                id="notes"
                name="notes"
                value={formData.notes}
                onChange={handleChange}
                readOnly={isReadOnly}
                rows={4}
                placeholder="Optional timing notes, sponsor shout-outs, or crowd guidance."
              />
            </div>

            <div className="sf">
              <span className="sl">mood</span>
              <div className="mood-row">
                {moodOptions.map((option) => (
                  <button
                    className={`mswatch ${
                      formData.mood === option.value ? "active" : ""
                    }`}
                    data-mood={option.value}
                    disabled={isReadOnly}
                    key={option.value}
                    onClick={() => handleMoodChange(option.value)}
                    type="button"
                  >
                    {option.label}
                  </button>
                ))}
              </div>
            </div>

            {error ? <div className="error-banner">{error}</div> : null}
            {statusError ? <div className="error-banner">{statusError}</div> : null}

            <button className="launch-btn" type="submit" disabled={isReadOnly}>
              <svg
                width="14"
                height="14"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2.2"
                strokeLinecap="round"
                strokeLinejoin="round"
                aria-hidden="true"
              >
                <path d="M12 2l1.8 5.4L19 9l-5.2 1.8L12 16l-1.8-5.2L5 9l5.2-1.6L12 2z" />
              </svg>
              {isLaunching ? "launching..." : "launch your host"}
            </button>

            <div className="setup-actions">
              <button
                className="chip danger-chip"
                type="button"
                onClick={handleStop}
                disabled={isStopping}
              >
                {isStopping ? "stopping..." : "stop"}
              </button>
              <a className="chip" href="/live">
                live room
              </a>
              <a className="chip" href="/logs">
                logs
              </a>
            </div>
          </form>
        </section>
      </main>
    </div>
  );
}

export default EventForm;
