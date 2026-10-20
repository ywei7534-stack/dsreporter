const API_BASE = "/api/v1";

async function request(path, options = {}) {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: {
      "Content-Type": "application/json",
      ...(options.headers || {}),
    },
    ...options,
  });

  const contentType = response.headers.get("content-type") || "";
  const payload = contentType.includes("application/json")
    ? await response.json()
    : await response.text();

  if (!response.ok) {
    const message =
      payload?.error?.message || payload?.detail || payload || "Request failed";
    const error = new Error(message);
    error.status = response.status;
    error.code = payload?.error?.code;
    throw error;
  }

  return payload;
}

export function createResearchTask(payload) {
  return request("/research-tasks", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function getResearchTask(taskId) {
  return request(`/research-tasks/${taskId}`);
}

export function getPlanReview(taskId) {
  return request(`/research-tasks/${taskId}/plan-review`);
}

export function submitPlanReview(taskId, decision, feedback) {
  return request(`/research-tasks/${taskId}/plan-review`, {
    method: "POST",
    body: JSON.stringify({ decision, feedback }),
  });
}

export function getResearchResult(taskId) {
  return request(`/research-tasks/${taskId}/result`);
}

export function getArtifacts(taskId) {
  return request(`/research-tasks/${taskId}/artifacts`);
}
