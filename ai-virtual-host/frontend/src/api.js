const JSON_HEADERS = {
  "Content-Type": "application/json",
};

const DIRECT_API_ORIGIN = "http://127.0.0.1:8000";

async function parseResponse(response) {
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = data?.detail || "Request failed.";
    throw new Error(detail);
  }
  return data;
}

async function fetchWithLocalFallback(path, options = {}) {
  try {
    return await fetch(path, options);
  } catch (err) {
    if (window.location.hostname === "127.0.0.1" || window.location.hostname === "localhost") {
      return fetch(`${DIRECT_API_ORIGIN}${path}`, options);
    }
    throw err;
  }
}

export async function launchSession(eventData) {
  const response = await fetchWithLocalFallback("/api/launch", {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify(eventData),
  });
  return parseResponse(response);
}

export async function stopSession() {
  const response = await fetchWithLocalFallback("/api/stop", {
    method: "POST",
    headers: JSON_HEADERS,
  });
  return parseResponse(response);
}

export async function getStatus() {
  const response = await fetchWithLocalFallback("/api/status");
  return parseResponse(response);
}

export async function getLogs(limit = 200) {
  const response = await fetchWithLocalFallback(`/api/logs?limit=${encodeURIComponent(limit)}`);
  return parseResponse(response);
}

export function createStatusSocket() {
  const protocol = window.location.protocol === "https:" ? "wss" : "ws";
  return new WebSocket(`${protocol}://${window.location.host}/ws/status`);
}
