function StatusBadge({ phase }) {
  const config = {
    idle: { label: "Idle", className: "status-badge status-idle" },
    connecting: {
      label: "Connecting...",
      className: "status-badge status-connecting",
    },
    live: { label: "Live", className: "status-badge status-live" },
    stopped: { label: "Stopped", className: "status-badge status-stopped" },
  };

  const status = config[phase] || config.idle;

  return (
    <div className={status.className}>
      <span className="status-dot" aria-hidden="true" />
      <span>{status.label}</span>
    </div>
  );
}

export default StatusBadge;
