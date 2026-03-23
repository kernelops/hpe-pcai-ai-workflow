const API_BASE = "http://localhost:8000";

const startBtn = document.getElementById("start-deployment-btn");
const nodesTableBody = document.getElementById("nodes-table-body");
const addNodeForm = document.getElementById("add-node-form");
const logOutput = document.getElementById("log-output");
const globalStatusPill = document.getElementById("global-status-pill");
const currentRunIdEl = document.getElementById("current-run-id");
const lastUpdatedEl = document.getElementById("last-updated");
const clearLogsBtn = document.getElementById("clear-logs-btn");
const refreshStatusBtn = document.getElementById("refresh-status-btn");
const totalNodesCountEl = document.getElementById("total-nodes-count");
const connectedNodesCountEl = document.getElementById("connected-nodes-count");
const unreachableNodesCountEl = document.getElementById("unreachable-nodes-count");
const overviewTotalNodesEl = document.getElementById("overview-total-nodes");
const overviewConnectedNodesEl = document.getElementById("overview-connected-nodes");
const overviewLastRunIdEl = document.getElementById("overview-last-run-id");
const overviewLastStatusEl = document.getElementById("overview-last-status");

const navItems = document.querySelectorAll(".nav-item");
const views = {
  overview: document.getElementById("view-overview"),
  nodes: document.getElementById("view-nodes"),
  health: document.getElementById("view-health"),
  deployment: document.getElementById("view-deployment"),
};
const toastEl = document.getElementById("toast");

let currentRunId = null;
let logsPollInterval = null;

function showToast(message, kind = "success") {
  toastEl.textContent = message;
  toastEl.classList.remove("hidden", "toast-success", "toast-error");
  toastEl.classList.add(kind === "success" ? "toast-success" : "toast-error");
  setTimeout(() => {
    toastEl.classList.add("hidden");
  }, 3500);
}

async function api(path, options = {}) {
  const res = await fetch(API_BASE + path, {
    headers: {
      "Content-Type": "application/json",
    },
    ...options,
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(text || res.statusText);
  }
  return res.json();
}

function setStatus(status) {
  globalStatusPill.classList.remove("status-idle", "status-running", "status-failed");
  if (status === "running") {
    globalStatusPill.classList.add("status-running");
    globalStatusPill.textContent = "Running";
    if (overviewLastStatusEl) overviewLastStatusEl.textContent = "Running";
  } else if (status === "failed") {
    globalStatusPill.classList.add("status-failed");
    globalStatusPill.textContent = "Failed";
    if (overviewLastStatusEl) overviewLastStatusEl.textContent = "Failed";
  } else if (status === "success") {
    globalStatusPill.classList.add("status-running");
    globalStatusPill.textContent = "Completed";
    if (overviewLastStatusEl) overviewLastStatusEl.textContent = "Completed";
  } else {
    globalStatusPill.classList.add("status-idle");
    globalStatusPill.textContent = "Idle";
    if (overviewLastStatusEl) overviewLastStatusEl.textContent = "Idle";
  }
}

function updateTimestamp() {
  const now = new Date();
  lastUpdatedEl.textContent = now.toLocaleTimeString();
}

function formatNodeStatus(status) {
  if (!status || status === "unknown") return { label: "Unknown", className: "node-status-unknown" };
  if (status === "reachable") return { label: "Connected", className: "node-status-ok" };
  if (status === "unreachable") return { label: "Unreachable", className: "node-status-bad" };
  return { label: status, className: "node-status-unknown" };
}

async function refreshNodes() {
  try {
    const nodes = await api("/nodes");
    if (!Array.isArray(nodes)) {
      console.error("Unexpected /nodes response", nodes);
      return;
    }

    nodesTableBody.innerHTML = "";
    let connected = 0;
    let unreachable = 0;

    nodes.forEach((node) => {
      const tr = document.createElement("tr");
      const ipTd = document.createElement("td");
      const userTd = document.createElement("td");
      const statusTd = document.createElement("td");

      ipTd.textContent = node.ip;
      userTd.textContent = node.username;
      const statusInfo = formatNodeStatus(node.status);
      const statusChip = document.createElement("span");
      statusChip.className = `node-status ${statusInfo.className}`;
      statusChip.textContent = statusInfo.label;
      if (node.last_checked) {
        const dt = new Date(node.last_checked);
        statusChip.title = `Last checked: ${dt.toLocaleString()}`;
      }
      statusTd.appendChild(statusChip);

      if (node.status === "reachable") connected += 1;
      if (node.status === "unreachable") unreachable += 1;

      tr.appendChild(ipTd);
      tr.appendChild(userTd);
      tr.appendChild(statusTd);
      nodesTableBody.appendChild(tr);
    });

    if (totalNodesCountEl) totalNodesCountEl.textContent = String(nodes.length);
    if (connectedNodesCountEl) connectedNodesCountEl.textContent = String(connected);
    if (unreachableNodesCountEl) unreachableNodesCountEl.textContent = String(unreachable);
    if (overviewTotalNodesEl) overviewTotalNodesEl.textContent = String(nodes.length);
    if (overviewConnectedNodesEl) overviewConnectedNodesEl.textContent = String(connected);
  } catch (err) {
    console.error("Failed to load nodes", err);
  }
}

async function startDeployment() {
  try {
    startBtn.disabled = true;
    setStatus("running");
    logOutput.textContent = "";
    const resp = await api("/deployments/start", { method: "POST", body: JSON.stringify({}) });
    currentRunId = resp.run_id;
    currentRunIdEl.textContent = currentRunId || "—";
    if (overviewLastRunIdEl) overviewLastRunIdEl.textContent = currentRunId || "—";
    updateTimestamp();
    showToast("Deployment started.");
    startLogsPolling();
  } catch (err) {
    console.error(err);
    setStatus("failed");
    showToast("Failed to start deployment: " + err.message, "error");
  } finally {
    startBtn.disabled = false;
  }
}

async function fetchLogs() {
  if (!currentRunId) return;
  
  // Get selected task from dropdown
  const taskSelector = document.getElementById("task-selector");
  const selectedTask = taskSelector.value;
  
  try {
    // For expanded tasks, try both base task ID and numbered versions
    let data = null;
    
    // Try base task ID first
    try {
      data = await api(`/deployments/${encodeURIComponent(currentRunId)}/logs/${selectedTask}/direct`);
    } catch (e) {
      // If not found, try numbered versions (for expanded tasks)
      for (let i = 0; i < 10; i++) {
        try {
          data = await api(`/deployments/${encodeURIComponent(currentRunId)}/logs/${selectedTask}__${i}/direct`);
          if (data && (data.log || data.state)) {
            break;
          }
        } catch (e2) {
          // Continue trying next number
          continue;
        }
      }
    }
    
    if (data && data.log) {
      logOutput.textContent = data.log;
      logOutput.scrollTop = logOutput.scrollHeight;
    }
    if (data && data.state) {
      if (["success", "failed"].includes(data.state)) {
        setStatus(data.state === "success" ? "success" : "failed");
        stopLogsPolling();
        return;
      } else {
        setStatus("running");
      }
    }
    updateTimestamp();
  } catch (err) {
    console.error("Error fetching logs", err);
  }
}

function startLogsPolling() {
  stopLogsPolling();
  logsPollInterval = setInterval(fetchLogs, 3000);
}

function stopLogsPolling() {
  if (logsPollInterval) {
    clearInterval(logsPollInterval);
    logsPollInterval = null;
  }
}

addNodeForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  const ip = document.getElementById("node-ip").value.trim();
  const username = document.getElementById("node-username").value.trim();
  const password = document.getElementById("node-password").value;
  if (!ip || !username || !password) return;
  try {
    await api("/nodes", {
      method: "POST",
      body: JSON.stringify({ ip, username, password }),
    });
    showToast("Worker node added.");
    addNodeForm.reset();
    refreshNodes();
  } catch (err) {
    console.error(err);
    showToast("Failed to add node: " + err.message, "error");
  }
});

startBtn.addEventListener("click", () => {
  startDeployment();
});

clearLogsBtn.addEventListener("click", () => {
  logOutput.textContent = "";
});

if (refreshStatusBtn) {
  refreshStatusBtn.addEventListener("click", async () => {
    try {
      await api("/nodes/refresh_status", { method: "POST", body: JSON.stringify({}) });
      await refreshNodes();
      showToast("Node statuses refreshed.");
    } catch (err) {
      console.error("Failed to refresh node status", err);
      showToast("Failed to refresh node status: " + err.message, "error");
    }
  });
}

function setActiveView(target) {
  Object.entries(views).forEach(([key, el]) => {
    if (!el) return;
    if (key === target) {
      el.classList.add("view-active");
    } else {
      el.classList.remove("view-active");
    }
  });

  navItems.forEach((item) => {
    const view = item.getAttribute("data-view-target");
    if (view === target) {
      item.classList.add("nav-item-active");
    } else {
      item.classList.remove("nav-item-active");
    }
  });
}

navItems.forEach((item) => {
  item.addEventListener("click", () => {
    const target = item.getAttribute("data-view-target");
    if (!target) return;
    setActiveView(target);
  });
});

refreshNodes();

