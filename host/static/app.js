/**
 * HomeCare Copilot - Frontend Application Logic
 * Integrates chat with simulated Alexa+ host, Web Speech API TTS,
 * live telemetry polling, and safe order confirmation.
 */

let isVoiceEnabled = true;
let currentUtterance = null;
let pendingOrderTimers = {};

// DOM Elements
const chatForm = document.getElementById("chat-form");
const chatInput = document.getElementById("chat-input");
const btnSend = document.getElementById("btn-send");
const messagesContainer = document.getElementById("messages-container");
const connectionStatus = document.getElementById("connection-status");
const statusDot = connectionStatus.querySelector(".status-dot");
const statusLabel = connectionStatus.querySelector(".status-label");
const btnVoiceToggle = document.getElementById("btn-voice-toggle");
const voiceIcon = document.getElementById("voice-icon");
const voiceLabel = document.getElementById("voice-label");
const speechWave = document.getElementById("speech-wave");
const appliancesList = document.getElementById("appliances-list");
const pendingOrdersList = document.getElementById("pending-orders-list");
const auditStream = document.getElementById("audit-stream");
const auditCount = document.getElementById("audit-count");
const btnAdvanceWear = document.getElementById("btn-advance-wear");
const btnResetDb = document.getElementById("btn-reset-db");
const btnRefreshTelemetry = document.getElementById("btn-refresh-telemetry");

// Initialize on DOM Load
document.addEventListener("DOMContentLoaded", () => {
  setupSpeechSynthesis();
  setupEventListeners();
  checkConnection();
  refreshAllDashboardData();

  // Poll dashboard telemetry and audit logs periodically
  setInterval(refreshAllDashboardData, 3000);
});

// Setup Speech Synthesis
function setupSpeechSynthesis() {
  if (!("speechSynthesis" in window)) {
    isVoiceEnabled = false;
    btnVoiceToggle.style.display = "none";
    console.warn("Web Speech API not supported in this browser.");
  }
}

function speakText(text) {
  if (!isVoiceEnabled || !("speechSynthesis" in window)) return;

  try {
    window.speechSynthesis.cancel();
    if (!text || text.trim() === "") return;

    currentUtterance = new SpeechSynthesisUtterance(text);
    currentUtterance.rate = 1.05;
    currentUtterance.pitch = 1.0;

    currentUtterance.onstart = () => {
      speechWave.style.display = "flex";
    };

    currentUtterance.onend = () => {
      speechWave.style.display = "none";
    };

    currentUtterance.onerror = () => {
      speechWave.style.display = "none";
    };

    window.speechSynthesis.speak(currentUtterance);
  } catch (err) {
    console.error("SpeechSynthesis error:", err);
    speechWave.style.display = "none";
  }
}

// Event Listeners
function setupEventListeners() {
  // Chat form submit
  chatForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const message = chatInput.value.trim();
    if (!message) return;
    chatInput.value = "";
    await sendUserMessage(message);
  });

  // Voice toggle
  btnVoiceToggle.addEventListener("click", () => {
    isVoiceEnabled = !isVoiceEnabled;
    btnVoiceToggle.setAttribute("aria-pressed", isVoiceEnabled);
    if (isVoiceEnabled) {
      voiceIcon.textContent = "🔊";
      voiceLabel.textContent = "Voice: On";
    } else {
      voiceIcon.textContent = "🔇";
      voiceLabel.textContent = "Voice: Muted";
      if ("speechSynthesis" in window) {
        window.speechSynthesis.cancel();
      }
      speechWave.style.display = "none";
    }
  });

  // Scenario shortcut pills
  document.querySelectorAll(".scenario-pill").forEach((pill) => {
    pill.addEventListener("click", () => {
      const prompt = pill.getAttribute("data-prompt");
      if (prompt) {
        chatInput.value = prompt;
        sendUserMessage(prompt);
      }
    });
  });

  // Advance wear button (Scenario D)
  btnAdvanceWear.addEventListener("click", async () => {
    try {
      btnAdvanceWear.disabled = true;
      btnAdvanceWear.textContent = "⚡ Advancing Wear...";
      const res = await fetch("/api/advance_wear", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          device_id: "vacuum_01",
          wear_key: "main_roller_brush_wear",
          amount: 96,
        }),
      });
      const data = await res.json();
      if (data.success) {
        await refreshAllDashboardData();
        await sendUserMessage("Check proactive maintenance for all appliances.");
      }
    } catch (err) {
      console.error("Failed to advance wear:", err);
    } finally {
      btnAdvanceWear.disabled = false;
      btnAdvanceWear.textContent = "⚡ Advance Vacuum Wear (Scenario D)";
    }
  });

  // Reset DB button
  btnResetDb.addEventListener("click", async () => {
    if (!confirm("Reset demo database and appliance telemetry back to initial state?")) return;
    try {
      btnResetDb.disabled = true;
      const res = await fetch("/api/reset", { method: "POST" });
      const data = await res.json();
      if (data.success) {
        await refreshAllDashboardData();
        appendSystemNotification("Demo database reset to clean baseline state.");
      }
    } catch (err) {
      console.error("Failed to reset DB:", err);
    } finally {
      btnResetDb.disabled = false;
    }
  });

  // Manual refresh button
  btnRefreshTelemetry.addEventListener("click", refreshAllDashboardData);
}

// Connection Health Check
async function checkConnection() {
  try {
    const res = await fetch("/api/health");
    if (res.ok) {
      statusDot.className = "status-dot connected";
      statusLabel.textContent = "MCP: Streamable HTTP (Active)";
    } else {
      statusDot.className = "status-dot error";
      statusLabel.textContent = "MCP: Disconnected";
    }
  } catch (err) {
    statusDot.className = "status-dot error";
    statusLabel.textContent = "Host Offline";
  }
}

// Send Message to Host
async function sendUserMessage(message) {
  // Render user bubble
  appendUserMessage(message);
  setLoading(true);

  try {
    const res = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message }),
    });

    if (!res.ok) {
      throw new Error(`Server returned HTTP ${res.status}`);
    }

    const data = await res.json();
    appendAssistantMessage(data);

    // Speak response
    if (data.spoken_summary) {
      speakText(data.spoken_summary);
    }

    // Refresh telemetry immediately
    refreshAllDashboardData();
  } catch (err) {
    appendAssistantMessage({
      spoken_summary: "Sorry, I encountered an error communicating with the host.",
      display_text: `**Connection Error**: Could not complete request: ${err.message}`,
      tool_traces: [],
      suggested_actions: [],
    });
  } finally {
    setLoading(false);
  }
}

function setLoading(isLoading) {
  btnSend.disabled = isLoading;
  chatInput.disabled = isLoading;
  if (isLoading) {
    btnSend.innerHTML = `<span>Thinking...</span>`;
  } else {
    btnSend.innerHTML = `
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <line x1="22" y1="2" x2="11" y2="13"></line>
        <polygon points="22 2 15 22 11 13 2 9 22 2"></polygon>
      </svg>
      <span>Ask Alexa+</span>
    `;
    chatInput.focus();
  }
}

// UI Append Helpers
function appendUserMessage(text) {
  const wrapper = document.createElement("div");
  wrapper.className = "message-wrapper user-wrapper";
  wrapper.innerHTML = `
    <div class="avatar user-avatar">You</div>
    <div class="message-bubble user-bubble">
      <div class="bubble-header">
        <span class="sender-name">User</span>
        <span class="time-stamp">${formatTime(new Date())}</span>
      </div>
      <div class="bubble-body">
        <p>${escapeHtml(text)}</p>
      </div>
    </div>
  `;
  messagesContainer.appendChild(wrapper);
  scrollToBottom();
}

function appendAssistantMessage(data) {
  const wrapper = document.createElement("div");
  wrapper.className = "message-wrapper assistant-wrapper";

  const timeStr = formatTime(new Date());
  const spoken = data.spoken_summary || "";
  const displayHtml = markdownToHtml(data.display_text || spoken);

  // Tool trace HTML
  let traceHtml = "";
  if (data.tool_traces && data.tool_traces.length > 0) {
    const items = data.tool_traces
      .map((t) => {
        const isErr = t.status === "ERROR";
        return `
        <div class="trace-item">
          <div class="trace-header">
            <span class="trace-tool-name">⚡ Tool: ${escapeHtml(t.tool)}</span>
            <span class="trace-badge ${isErr ? "error" : ""}">${t.latency_ms}ms • ${t.status}</span>
          </div>
          <div class="trace-code"><strong>Arguments:</strong> ${escapeHtml(JSON.stringify(t.arguments, null, 2))}</div>
          <div class="trace-code" style="margin-top: 4px;"><strong>Result:</strong> ${escapeHtml(JSON.stringify(t.result, null, 2))}</div>
        </div>
      `;
      })
      .join("");

    traceHtml = `
      <div class="tool-trace-container">
        <button class="trace-toggle" onclick="toggleTrace(this)">
          ▶ View MCP Tool Execution Trace (${data.tool_traces.length} tool${data.tool_traces.length > 1 ? "s" : ""})
        </button>
        <div class="trace-list" style="display: none;">
          ${items}
        </div>
      </div>
    `;
  }

  // Suggested Action Buttons
  let actionsHtml = "";
  if (data.suggested_actions && data.suggested_actions.length > 0) {
    const pills = data.suggested_actions
      .map((a) => {
        return `<button class="btn-action-pill" onclick="handlePillAction('${escapeHtml(a.prompt)}')">${escapeHtml(a.label)}</button>`;
      })
      .join("");
    actionsHtml = `<div class="suggested-actions-tray">${pills}</div>`;
  }

  wrapper.innerHTML = `
    <div class="avatar alexa-avatar">A+</div>
    <div class="message-bubble assistant-bubble">
      <div class="bubble-header">
        <span class="sender-name">Alexa+ HomeCare</span>
        <div>
          <span class="time-stamp">${timeStr}</span>
          <button class="btn-speak-replay" title="Replay spoken response" onclick="speakText('${escapeForAttr(spoken)}')">🔊</button>
        </div>
      </div>
      <div class="bubble-body">
        ${displayHtml}
      </div>
      ${actionsHtml}
      ${traceHtml}
    </div>
  `;

  messagesContainer.appendChild(wrapper);
  scrollToBottom();
}

function appendSystemNotification(msg) {
  const div = document.createElement("div");
  div.style.textAlign = "center";
  div.style.fontSize = "0.75rem";
  div.style.color = "var(--alexa-cyan)";
  div.style.margin = "8px 0";
  div.textContent = `ℹ ${msg}`;
  messagesContainer.appendChild(div);
  scrollToBottom();
}

function handlePillAction(prompt) {
  chatInput.value = prompt;
  sendUserMessage(prompt);
}

function toggleTrace(btn) {
  const list = btn.nextElementSibling;
  const isHidden = list.style.display === "none";
  list.style.display = isHidden ? "flex" : "none";
  btn.textContent = (isHidden ? "▼ Hide " : "▶ View ") + btn.textContent.substring(btn.textContent.indexOf("MCP"));
}

// Dashboard Telemetry and Orders Refresh
async function refreshAllDashboardData() {
  await Promise.all([loadAppliances(), loadOrders(), loadAuditLogs()]);
}

async function loadAppliances() {
  try {
    const res = await fetch("/api/appliances");
    if (!res.ok) return;
    const data = await res.json();
    const apps = data.appliances || [];

    if (apps.length === 0) {
      appliancesList.innerHTML = `<p class="empty-state">No connected appliances detected.</p>`;
      return;
    }

    appliancesList.innerHTML = apps
      .map((app) => {
        const health = app.health_score || 0;
        let healthClass = "health-good";
        if (health < 70) healthClass = "health-crit";
        else if (health < 85) healthClass = "health-warn";

        let statusBadge = "badge-success";
        if (app.status === "needs_maintenance") statusBadge = "badge-danger";
        else if (app.status === "running") statusBadge = "badge-info";

        const errors = app.error_codes || [];
        const wear = app.wear_counters || {};

        const wearHtml = Object.entries(wear)
          .map(([key, val]) => {
            const isHigh = val >= 80;
            const cleanKey = key.replace(/_/g, " ");
            return `
            <div class="wear-row">
              <span style="text-transform: capitalize;">${cleanKey}:</span>
              <div class="wear-bar-track">
                <div class="wear-bar-fill ${isHigh ? "high-wear" : ""}" style="width: ${Math.min(val, 100)}%;"></div>
              </div>
              <span style="font-weight: 600; color: ${isHigh ? "var(--accent-danger)" : "inherit"};">${val}%</span>
            </div>
          `;
          })
          .join("");

        return `
        <div class="appliance-item">
          <div class="appliance-item-top">
            <div>
              <div class="appliance-item-name">${escapeHtml(app.name)}</div>
              <div class="appliance-item-id">${escapeHtml(app.id)} • ${escapeHtml(app.type)}</div>
            </div>
            <span class="badge ${statusBadge}">${escapeHtml(app.status)}</span>
          </div>

          <div class="appliance-meta-row">
            <div class="health-meter">
              <span>Health:</span>
              <div class="meter-track">
                <div class="meter-fill ${healthClass}" style="width: ${health}%;"></div>
              </div>
              <strong>${health}%</strong>
            </div>
            ${errors.length > 0 ? `<span class="badge badge-danger">${errors[0]}</span>` : ""}
          </div>

          <div class="wear-indicators">
            ${wearHtml}
          </div>

          <div class="appliance-actions-row">
            <button class="btn btn-xs btn-outline" onclick="diagnoseAppliance('${app.id}', '${escapeHtml(app.name)}')">Diagnose</button>
            <button class="btn btn-xs btn-outline" onclick="inspectAppliance('${app.id}')">Inspect Telemetry</button>
          </div>
        </div>
      `;
      })
      .join("");
  } catch (err) {
    console.error("Error loading appliances:", err);
  }
}

async function loadOrders() {
  try {
    const res = await fetch("/api/orders");
    if (!res.ok) return;
    const data = await res.json();
    const orders = data.orders || [];

    const pending = orders.filter((o) => o.status === "PENDING");

    if (pending.length === 0) {
      pendingOrdersList.innerHTML = `<p class="empty-state">No pending orders waiting for confirmation.</p>`;
      return;
    }

    pendingOrdersList.innerHTML = pending
      .map((ord) => {
        const remaining = Math.max(0, Math.floor(ord.expires_at - Date.now() / 1000));
        return `
        <div class="pending-order-item" id="order-card-${ord.order_id}">
          <div class="pending-order-top">
            <span class="pending-order-id">${ord.order_id}</span>
            <span class="countdown-badge" id="timer-${ord.order_id}">⏳ ${remaining}s left</span>
          </div>
          <div class="pending-order-details">
            <div><strong>Part:</strong> ${escapeHtml(ord.part_id)} (Qty: ${ord.quantity})</div>
            <div><strong>Total:</strong> $${ord.total_price.toFixed(2)} (Simulated Payment)</div>
          </div>
          <div class="pending-order-actions">
            <button class="btn btn-xs btn-success" onclick="confirmOrder('${ord.order_id}', '${ord.confirmation_token}')">
              ✓ Authorize & Confirm
            </button>
          </div>
        </div>
      `;
      })
      .join("");
  } catch (err) {
    console.error("Error loading orders:", err);
  }
}

async function confirmOrder(orderId, confirmationToken) {
  try {
    const idempotencyKey = `IDEM-${orderId}`;
    const res = await fetch("/api/confirm_order", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        order_id: orderId,
        confirmation_token: confirmationToken,
        idempotency_key: idempotencyKey,
      }),
    });
    const data = await res.json();
    const result = data.result || {};
    appendAssistantMessage({
      spoken_summary: result.spoken_summary || "Order confirmed.",
      display_text: `### Order ${orderId} Confirmed\n\n- **Status**: Approved\n- **Idempotency Key**: \`${idempotencyKey}\`\n\n${result.spoken_summary}`,
      tool_traces: [
        {
          tool: "confirm_purchase",
          arguments: { order_id: orderId, idempotency_key: idempotencyKey },
          latency_ms: data.latency_ms || 32,
          status: data.status || "SUCCESS",
          result: result,
        },
      ],
      suggested_actions: [],
    });
    if (result.spoken_summary) {
      speakText(result.spoken_summary);
    }
    refreshAllDashboardData();
  } catch (err) {
    alert(`Confirmation failed: ${err.message}`);
  }
}

async function loadAuditLogs() {
  try {
    const res = await fetch("/api/audit");
    if (!res.ok) return;
    const data = await res.json();
    const logs = data.audit_logs || [];
    auditCount.textContent = `${logs.length} Events`;

    if (logs.length === 0) {
      auditStream.innerHTML = `<p class="empty-state">No audit events logged yet.</p>`;
      return;
    }

    auditStream.innerHTML = logs
      .slice(0, 15)
      .map((entry) => {
        const isRefused = entry.status === "REFUSED";
        const dateStr = new Date(entry.timestamp * 1000).toLocaleTimeString();
        const detailsStr = entry.details ? JSON.stringify(entry.details) : "";

        return `
        <div class="audit-entry">
          <div class="audit-entry-top">
            <span class="audit-op">${escapeHtml(entry.operation)}</span>
            <span class="audit-status ${isRefused ? "status-refused" : "status-success"}">${entry.status}</span>
          </div>
          <div class="audit-time">${dateStr} • ${entry.device_id || "system"}</div>
          <div class="audit-desc">${escapeHtml(detailsStr.substring(0, 120))}${detailsStr.length > 120 ? "..." : ""}</div>
        </div>
      `;
      })
      .join("");
  } catch (err) {
    console.error("Error loading audit logs:", err);
  }
}

function diagnoseAppliance(deviceId, deviceName) {
  const prompt = `Diagnose issue for ${deviceName} (${deviceId})`;
  chatInput.value = prompt;
  sendUserMessage(prompt);
}

function inspectAppliance(deviceId) {
  const prompt = `Show status of ${deviceId}`;
  chatInput.value = prompt;
  sendUserMessage(prompt);
}

// Utility Helpers
function scrollToBottom() {
  messagesContainer.scrollTop = messagesContainer.scrollHeight;
}

function formatTime(d) {
  return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

function escapeHtml(str) {
  if (!str) return "";
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

function escapeForAttr(str) {
  if (!str) return "";
  return String(str).replace(/'/g, "\\'").replace(/"/g, "&quot;");
}

function markdownToHtml(md) {
  if (!md) return "";
  let html = escapeHtml(md);

  // Headers
  html = html.replace(/^### (.*$)/gim, '<h3 style="font-size: 0.95rem; font-weight: 600; margin: 8px 0 4px 0; color: var(--alexa-cyan);">$1</h3>');
  html = html.replace(/^## (.*$)/gim, '<h2 style="font-size: 1.05rem; font-weight: 700; margin: 10px 0 6px 0;">$1</h2>');

  // Bold & Italic
  html = html.replace(/\*\*(.*?)\*\*/g, "<strong>$1</strong>");
  html = html.replace(/\*(.*?)\*/g, "<em>$1</em>");

  // Inline code
  html = html.replace(/`(.*?)`/g, '<code style="background: rgba(0,202,224,0.1); color: var(--alexa-cyan); padding: 1px 4px; border-radius: 4px; font-family: var(--font-mono); font-size: 0.8rem;">$1</code>');

  // Blockquotes
  html = html.replace(/^> (.*$)/gim, '<blockquote style="border-left: 3px solid var(--alexa-cyan); padding-left: 8px; margin: 6px 0; color: #cbd5e1;">$1</blockquote>');

  // Unordered lists
  html = html.replace(/^\- (.*$)/gim, '<li style="margin-left: 16px;">$1</li>');

  // Line breaks
  html = html.replace(/\n\n/g, "<br><br>");

  return html;
}
