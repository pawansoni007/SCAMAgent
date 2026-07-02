const API_BASE = import.meta.env.VITE_API_BASE_URL || "";

async function handle(res) {
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail || `Request failed (${res.status})`);
  }
  return res.json();
}

export const api = {
  health: () => fetch(`${API_BASE}/api/health`).then(handle),
  referenceData: () => fetch(`${API_BASE}/api/reference-data`).then(handle),
  agents: () => fetch(`${API_BASE}/api/agents`).then(handle),
  analyze: (payload) =>
    fetch(`${API_BASE}/api/procurement/analyze`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }).then(handle),
  decide: (decision) =>
    fetch(`${API_BASE}/api/approval/decision`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(decision),
    }).then(handle),
  chat: (payload) =>
    fetch(`${API_BASE}/api/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }).then(handle),

      getExceptionHistory: () => fetch(`${API_BASE}/api/approval/history`).then(handle),
  getExceptions: () => fetch(`${API_BASE}/api/approval/list`).then(handle),
  getOrchestrationStatus: (requestId) =>
    fetch(`${API_BASE}/api/approval/status/${requestId}`).then(handle),
  submitApproval: (requestId, decision) =>
    fetch(`${API_BASE}/api/approval/decision`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ request_id: requestId, ...decision }),
    }).then(handle),


  listConversations: (
    includeArchived = false
  ) =>
    fetch(
      `/api/chat/conversations?include_archived=${includeArchived}`
    ).then(handle),

  getConversation: (conversationId) =>
    fetch(`/api/chat/conversations/${conversationId}`)
      .then(handle),

  renameConversation: (conversationId, title) =>
    fetch(
      `/api/conversations/${conversationId}/title`,
      {
        method: "PATCH",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          title,
        }),
      }
    ).then(handle),

  archiveConversation: (conversationId) =>
    fetch(
      `/api/conversations/${conversationId}/archive`,
      {
        method: "POST",
      }
    ).then(handle),

  deleteConversation: (conversationId) =>
    fetch(
      `/api/conversations/${conversationId}`,
      {
        method: "DELETE",
      }
    ).then(handle),

  unarchiveConversation: (
    conversationId
  ) =>
    fetch(
      `/api/conversations/${conversationId}/unarchive`,
      {
        method: "POST",
      }
    ).then(handle),

};



