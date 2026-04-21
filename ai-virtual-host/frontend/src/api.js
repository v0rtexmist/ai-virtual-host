const JSON_HEADERS = {
  "Content-Type": "application/json",
};

const LOCAL_BACKEND_ORIGIN = "http://127.0.0.1:8000";
const CONFIGURED_API_ORIGIN = normalizeOrigin(import.meta.env.VITE_API_ORIGIN);
const CONFIGURED_WS_ORIGIN = normalizeOrigin(import.meta.env.VITE_WS_ORIGIN);

function normalizeOrigin(value) {
  return String(value || "").trim().replace(/\/+$/, "");
}

function isLocalFrontend() {
  return (
    window.location.hostname === "127.0.0.1" ||
    window.location.hostname === "localhost"
  );
}

function getApiOrigin() {
  if (CONFIGURED_API_ORIGIN) {
    return CONFIGURED_API_ORIGIN;
  }

  if (isLocalFrontend()) {
    return "";
  }

  return LOCAL_BACKEND_ORIGIN;
}

function getWsOrigin() {
  if (CONFIGURED_WS_ORIGIN) {
    return CONFIGURED_WS_ORIGIN;
  }

  const apiOrigin = getApiOrigin();
  if (apiOrigin) {
    return apiOrigin.replace(/^http:/, "ws:").replace(/^https:/, "wss:");
  }

  const protocol = window.location.protocol === "https:" ? "wss" : "ws";
  return `${protocol}://${window.location.host}`;
}

function backendHint(targetOrigin) {
  const frontendOrigin = window.location.origin;
  if (
    targetOrigin === LOCAL_BACKEND_ORIGIN ||
    (isLocalFrontend() && !CONFIGURED_API_ORIGIN)
  ) {
    return `Start the FastAPI backend on ${LOCAL_BACKEND_ORIGIN} and add FRONTEND_ORIGINS=${frontendOrigin} to ai-virtual-host/.env.`;
  }

  return "Check VITE_API_ORIGIN and make sure the FastAPI backend is running.";
}

async function parseResponse(response, path, url) {
  const contentType = response.headers.get("content-type") || "";
  const data = contentType.includes("application/json")
    ? await response.json().catch(() => ({}))
    : {};

  if (!response.ok) {
    let detail = data?.detail || `Request failed with status ${response.status}.`;
    if (!data?.detail && response.status === 404 && path.startsWith("/api")) {
      const targetOrigin = new URL(url, window.location.origin).origin;
      detail = `Backend API was not found at ${targetOrigin}. ${backendHint(targetOrigin)}`;
    }
    throw new Error(detail);
  }

  return data;
}

async function fetchApi(path, options = {}) {
  const apiOrigin = getApiOrigin();
  const url = `${apiOrigin}${path}`;

  try {
    const response = await fetch(url, options);
    return parseResponse(response, path, url);
  } catch (err) {
    if (!(err instanceof TypeError)) {
      throw err;
    }

    const targetOrigin = apiOrigin || window.location.origin;
    throw new Error(`Backend is unreachable at ${targetOrigin}. ${backendHint(targetOrigin)}`);
  }
}

export async function launchSession(eventData) {
  return fetchApi("/api/launch", {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify(eventData),
  });
}

export async function stopSession() {
  return fetchApi("/api/stop", {
    method: "POST",
    headers: JSON_HEADERS,
  });
}

export async function getStatus() {
  return fetchApi("/api/status");
}

export async function getLogs(limit = 200) {
  return fetchApi(`/api/logs?limit=${encodeURIComponent(limit)}`);
}

export function createStatusSocket() {
  return new WebSocket(`${getWsOrigin()}/ws/status`);
}
