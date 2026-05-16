import React, { useEffect, useMemo, useRef, useState } from "react";
import secureInfraLogo from "./assets/secureinfra-logo.svg";
import workflowLogo from "./assets/workflow-logo.svg";

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

const TABS = [
  { id: "overview", label: "Dashboard", icon: "📊" },
  { id: "nodes", label: "Worker Nodes", icon: "🖥" },
  { id: "health", label: "SSH Validation", icon: "🛡" },
  { id: "deployment", label: "Deployment", icon: "⚙️" },
  { id: "insights", label: "Log Insights", icon: "📈" },
  { id: "agentops", label: "Agent Ops", icon: "🧠" }
];

const AGENT_OPS_PLACEHOLDER = {
  workflow_agent: {
    title: "Workflow Agent",
    status: "Placeholder",
    summary:
      "Will summarize the run path, identify where orchestration broke, and map failed tasks to deployment stages.",
    bullets: [
      "Expected input: run id, task states, task ordering",
      "Output will focus on workflow progression and breakpoints"
    ]
  },
  log_analysis_agent: {
    title: "Log Analysis Agent",
    status: "Placeholder",
    summary:
      "Will inspect parsed task evidence, highlight root-cause lines, and separate wrapper noise from meaningful failures.",
    bullets: [
      "Expected input: parsed task blocks and evidence lines",
      "Output will surface the strongest error signals per failed task"
    ]
  },
  root_cause_agent: {
    title: "Root Cause Agent",
    status: "Placeholder",
    summary:
      "Will reason over the analyzed failure, classify the issue, assign severity, and define the engineer action.",
    bullets: [
      "Expected input: structured error report plus retrieved runbook context",
      "Output will include classification, severity, and remediation guidance"
    ]
  },
  alerting_agent: {
    title: "Alerting Agent",
    status: "Placeholder",
    summary:
      "Will package the final remediation into an alert, mark approval requirements, and show where notifications were routed.",
    bullets: [
      "Expected input: root cause report and action plan",
      "Output will show alert status, approval requirement, and notification channel details"
    ]
  },
  dag_analysis_agent: {
    title: "DAG Analysis Agent",
    status: "Placeholder",
    summary:
      "Will scan the DAG source code, query RAG for correct command syntax, and identify broken SSH commands.",
    bullets: [
      "Expected input: DAG Python source file",
      "Output will include identified issues and corrected source code"
    ]
  },
  dag_patch_agent: {
    title: "DAG Patch Agent",
    status: "Placeholder",
    summary:
      "Will write the corrected DAG as remediation_workflow.py and trigger it via the Airflow REST API.",
    bullets: [
      "Expected input: corrected DAG source from DAG Analysis Agent",
      "Output will show DAG run outcome and any remaining failed tasks"
    ]
  },
  fix_generator_agent: {
    title: "Fix Generator Agent",
    status: "Placeholder",
    summary:
      "Will analyse the root cause report, search the fix registry for known patterns, and generate concrete SSH fix commands.",
    bullets: [
      "Expected input: root cause report with classification and severity",
      "Output will include fix commands, risk level, and approval requirement"
    ]
  },
  fix_executor_agent: {
    title: "Fix Executor Agent",
    status: "Placeholder",
    summary:
      "Will execute the generated fix commands on target worker nodes via SSH and report per-command results.",
    bullets: [
      "Expected input: fix strategy with SSH commands and target nodes",
      "Output will show command outputs, exit codes, and overall execution status"
    ]
  },
  validation_agent: {
    title: "Validation Agent",
    status: "Placeholder",
    summary:
      "Will verify system health after the fix and check the HPC error queue for lingering failure logs.",
    bullets: [
      "Expected input: applied fix context and queue connection",
      "Output will show verification verdict and any newly escalated errors"
    ]
  },
  final_summary: {
    title: "Combined Summary",
    status: "Pending API",
    summary:
      "Once the agent API is wired, this panel will show the merged decision from all agents in one operator-ready incident brief.",
    bullets: [
      "Single endpoint response can populate all cards",
      "UI is ready to swap placeholder data for live agent outputs"
    ]
  }
};

const AGENT_CARD_ORDER = [
  "workflow_agent",
  "monitor_agent",
  "log_analysis_agent",
  "root_cause_agent",
  "alerting_agent",
  "dag_analysis_agent",
  "dag_patch_agent",
  "fix_generator_agent",
  "fix_executor_agent",
  "validation_agent"
];

const LOG_PATTERNS = [
  {
    id: "ssh_auth",
    label: "SSH Authentication",
    severity: "high",
    pattern: /(authentication failed|permission denied \(publickey,password\)|auth failed)/i,
    suggestion: "Verify SSH username/password or key pair, then retest with a manual SSH command."
  },
  {
    id: "network_timeout",
    label: "Network Timeout",
    severity: "high",
    pattern: /(timeout|timed out|network is unreachable|no route to host)/i,
    suggestion: "Check node reachability, firewall rules, and port 22 connectivity from Airflow worker."
  },
  {
    id: "connection_refused",
    label: "Connection Refused",
    severity: "high",
    pattern: /(connection refused|actively refused)/i,
    suggestion: "Ensure SSH service is running on target node and listening on expected port."
  },
  {
    id: "command_missing",
    label: "Command Missing",
    severity: "medium",
    pattern: /(command not found|is not recognized as an internal or external command)/i,
    suggestion: "Install missing dependency or update command path in DAG task."
  },
  {
    id: "docker_issue",
    label: "Docker Runtime Issue",
    severity: "medium",
    pattern: /(docker: command not found|cannot connect to the docker daemon|docker daemon)/i,
    suggestion: "Install/start Docker service and verify daemon access for deployment user."
  },
  {
    id: "airflow_task",
    label: "Airflow Task Failure",
    severity: "medium",
    pattern: /(task failed|marking task as failed|upstream_failed)/i,
    suggestion: "Open Airflow task instance details for full traceback and retry conditions."
  }
];

function analyzeLogs(logText, status) {
  const lines = (logText || "").split("\n").filter((line) => line.trim().length > 0);
  const totalLines = lines.length;
  const joined = lines.join("\n");

  const errorCount = lines.filter((line) =>
    /(error|failed|exception|traceback|refused|fatal)/i.test(line)
  ).length;
  const warningCount = lines.filter((line) =>
    /(warn|warning|retry|deprecat|unreachable|timeout)/i.test(line)
  ).length;
  const successCount = lines.filter((line) =>
    /(success|completed|task exited with return code 0|marking task as success)/i.test(line)
  ).length;

  const hits = LOG_PATTERNS.filter((entry) => entry.pattern.test(joined));
  const severityScore = hits.reduce((acc, hit) => {
    if (hit.severity === "high") return acc + 3;
    if (hit.severity === "medium") return acc + 2;
    return acc + 1;
  }, 0);

  let verdict = "Healthy";
  if (status === "Failed" || errorCount > 0 || severityScore >= 5) verdict = "Critical";
  else if (warningCount > 0 || severityScore >= 2) verdict = "Watch";

  return {
    totalLines,
    errorCount,
    warningCount,
    successCount,
    hits,
    verdict
  };
}

function summarizeDeploymentEvents(logText, runStatus) {
  const text = logText || "";
  const lines = text.split("\n");
  const executedSteps = [];

  const stepMap = [
    { key: "get_worker_nodes", label: "Fetched reachable worker nodes" },
    { key: "create_airflow_connections", label: "Prepared Airflow SSH connections" },
    { key: "run_hostname", label: "Executed remote SSH command(s) on worker nodes" }
  ];

  for (const step of stepMap) {
    const seenTask = new RegExp(`task_id=${step.key}`, "i").test(text);
    const seenSuccess = new RegExp(`task_id=${step.key}.*Marking task as SUCCESS`, "is").test(text);
    if (seenTask) {
      executedSteps.push({
        step: step.label,
        status: seenSuccess ? "completed" : "in_progress"
      });
    }
  }

  const hasFailure = /(marking task as failed|task failed|upstream_failed|exception|traceback)/i.test(text);
  const hasAnyOutput = lines.some((l) => l.trim().length > 0);

  let summary = "No deployment output captured yet.";
  if (runStatus === "Completed") {
    summary = "Deployment run completed successfully. Core workflow tasks were executed and logged.";
  } else if (runStatus === "Failed" || hasFailure) {
    summary = "Deployment run ended with failure signals. Review findings below and task-level logs for root cause.";
  } else if (hasAnyOutput) {
    summary = "Deployment is running. Logs indicate task execution is in progress.";
  }

  return {
    summary,
    executedSteps
  };
}

function hasFailureSignals(logText) {
  return /(marking task as failed|task failed with exception|error - failed to execute job|upstream_failed|airflow\.exceptions\.airflowexception|connection refused|unknown keyword|does not exist|failed to connect)/i.test(
    logText || ""
  );
}

function useToast() {
  const [toast, setToast] = useState(null);

  const show = (message, kind = "success") => {
    setToast({ message, kind });
    setTimeout(() => setToast(null), 3500);
  };

  const node = toast ? (
    <div className={`toast ${toast.kind === "success" ? "toast-success" : "toast-error"}`}>
      {toast.message}
    </div>
  ) : null;

  return { show, node };
}

function useNodes(apiBase, toast) {
  const [nodes, setNodes] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const refresh = async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`${apiBase}/nodes`);
      if (!res.ok) {
        const errorText = await res.text();
        throw new Error(errorText || 'Failed to fetch nodes');
      }
      const data = await res.json();
      if (Array.isArray(data)) setNodes(data);
    } catch (err) {
      console.error(err);
      setError(err.message);
      toast?.show?.("Failed to load nodes", "error");
    } finally {
      setLoading(false);
    }
  };

  const add = async (payload) => {
    setError(null);
    try {
      const res = await fetch(`${apiBase}/nodes`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      });
      if (!res.ok) {
        const errorData = await res.json();
        throw new Error(errorData.detail || "Failed to add node");
      }
      toast?.show?.("Worker node added successfully.");
      await refresh();
      return true;
    } catch (err) {
      console.error(err);
      setError(err.message);
      toast?.show?.(err.message, "error");
      return false;
    }
  };

  const remove = async (nodeId) => {
    setError(null);
    try {
      const res = await fetch(`${apiBase}/nodes/${nodeId}`, {
        method: "DELETE"
      });
      if (!res.ok) {
        const errorData = await res.json();
        throw new Error(errorData.detail || "Failed to delete node");
      }
      toast?.show?.("Worker node deleted successfully.");
      await refresh();
      return true;
    } catch (err) {
      console.error(err);
      setError(err.message);
      toast?.show?.(err.message, "error");
      return false;
    }
  };

  const refreshStatus = async () => {
    setError(null);
    try {
      const res = await fetch(`${apiBase}/nodes/refresh_status`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: "{}"
      });
      if (!res.ok) {
        const errorData = await res.json();
        throw new Error(errorData.detail || "Failed to refresh status");
      }
      toast?.show?.("Node statuses refreshed successfully.");
      await refresh();
    } catch (err) {
      console.error(err);
      setError(err.message);
      toast?.show?.(err.message, "error");
    }
  };

  useEffect(() => {
    refresh();
  }, []);

  const metrics = useMemo(() => {
    const total = nodes.length;
    const connected = nodes.filter((n) => n.status === "reachable").length;
    const unreachable = nodes.filter((n) => n.status === "unreachable").length;
    const unknown = nodes.filter((n) => n.status === "unknown").length;
    return { total, connected, unreachable, unknown };
  }, [nodes]);

  return { nodes, loading, error, refresh, add, remove, refreshStatus, metrics };
}

function OverviewView({ metrics, lastRunId, lastStatus }) {
  const getHealthStatus = () => {
    if (metrics.total === 0) return { label: "No Nodes", color: "#9ca3af" };
    const healthPercentage = (metrics.connected / metrics.total) * 100;
    if (healthPercentage === 100) return { label: "Healthy", color: "#22c55e" };
    if (healthPercentage >= 50) return { label: "Warning", color: "#f59e0b" };
    return { label: "Critical", color: "#ef4444" };
  };

  const healthStatus = getHealthStatus();
  const total = Math.max(metrics.total, 1);
  const connectedPct = Math.round((metrics.connected / total) * 100);
  const unreachablePct = Math.round((metrics.unreachable / total) * 100);
  const unknownPct = Math.max(0, 100 - connectedPct - unreachablePct);

  return (
    <section className="panel">
      <div className="panel-header">
        <h2>Platform Overview</h2>
        <div className="health-indicator">
          <span className="health-dot" style={{ backgroundColor: healthStatus.color }}></span>
          <span className="health-label">{healthStatus.label}</span>
        </div>
      </div>
      <div className="overview-grid">
        <div className="metric">
          <span className="label">Total Nodes</span>
          <span className="value">{metrics.total}</span>
        </div>
        <div className="metric">
          <span className="label">Connected Nodes</span>
          <span className="value connected">{metrics.connected}</span>
        </div>
        <div className="metric">
          <span className="label">Unreachable</span>
          <span className="value unreachable">{metrics.unreachable}</span>
        </div>
        <div className="metric">
          <span className="label">Last Deployment</span>
          <span className={`value ${lastStatus?.toLowerCase()}`}>
            {lastStatus || "Never"}
          </span>
        </div>
      </div>
      <div className="overview-visuals">
        <div className="overview-donut-wrap">
          <div
            className="overview-donut"
            style={{
              background: `conic-gradient(#10b981 0 ${connectedPct}%, #ef4444 ${connectedPct}% ${connectedPct + unreachablePct}%, #64748b ${connectedPct + unreachablePct}% 100%)`
            }}
          >
            <div className="overview-donut-center">{connectedPct}%</div>
          </div>
          <div className="overview-donut-caption">Connection Ratio</div>
        </div>
        <div className="overview-bars">
          <div className="overview-bar-row">
            <span>Connected</span>
            <div className="overview-bar-track"><div className="overview-bar-fill overview-ok" style={{ width: `${connectedPct}%` }} /></div>
            <span>{connectedPct}%</span>
          </div>
          <div className="overview-bar-row">
            <span>Unreachable</span>
            <div className="overview-bar-track"><div className="overview-bar-fill overview-bad" style={{ width: `${unreachablePct}%` }} /></div>
            <span>{unreachablePct}%</span>
          </div>
          <div className="overview-bar-row">
            <span>Unknown</span>
            <div className="overview-bar-track"><div className="overview-bar-fill overview-neutral" style={{ width: `${unknownPct}%` }} /></div>
            <span>{unknownPct}%</span>
          </div>
        </div>
      </div>
    </section>
  );
}

function NodesView({ nodes, onAdd, onRemove, loading, error }) {
  const [form, setForm] = useState({ ip: "", username: "", password: "" });
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [diagnostics, setDiagnostics] = useState(null);
  const [showDiagnostics, setShowDiagnostics] = useState(false);
  const [selectedNodeIndex, setSelectedNodeIndex] = useState(null);
  const [quickCheck, setQuickCheck] = useState(null);

  const handleChange = (e) => {
    setForm((f) => ({ ...f, [e.target.name]: e.target.value }));
  };

  const validateForm = () => {
    const ipRegex = /^(?:(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.){3}(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)$/;
    if (!form.ip || !ipRegex.test(form.ip)) {
      return "Please enter a valid IP address";
    }
    if (!form.username || form.username.length < 2) {
      return "Username must be at least 2 characters";
    }
    if (!form.password || form.password.length < 4) {
      return "Password must be at least 4 characters";
    }
    return null;
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    const validationError = validateForm();
    if (validationError) {
      alert(validationError);
      return;
    }
    
    setIsSubmitting(true);
    const success = await onAdd(form);
    if (success) {
      setQuickCheck({ loading: true, ip: form.ip, result: null, error: null });
      try {
        const findNodeWithRetry = async (retries = 3) => {
          for (let attempt = 0; attempt < retries; attempt += 1) {
            const listRes = await fetch(`${API_BASE}/nodes`);
            const nodeList = await listRes.json();
            const idx = nodeList.findIndex((n) => n.ip === form.ip && n.username === form.username);
            if (idx >= 0) return { idx, node: nodeList[idx] };
            await new Promise((resolve) => setTimeout(resolve, 400));
          }
          return { idx: -1, node: null };
        };

        const match = await findNodeWithRetry();
        if (match.idx >= 0) {
          try {
            const diagRes = await fetch(`${API_BASE}/nodes/${match.idx}/diagnostics`);
            if (!diagRes.ok) throw new Error("Diagnostics endpoint failed");
            const diagData = await diagRes.json();
            setQuickCheck({ loading: false, ip: form.ip, result: diagData, error: null });
          } catch {
            // Fallback if diagnostics endpoint fails: still show basic status from node list.
            setQuickCheck({
              loading: false,
              ip: form.ip,
              result: { fallback: true, node: match.node },
              error: null
            });
          }
        } else {
          setQuickCheck({
            loading: false,
            ip: form.ip,
            result: null,
            error: "Node added, but quick diagnostics could not resolve node index."
          });
        }
      } catch (diagErr) {
        setQuickCheck({ loading: false, ip: form.ip, result: null, error: diagErr.message });
      }
      setForm({ ip: "", username: "", password: "" });
    }
    setIsSubmitting(false);
  };

  const runDiagnostics = async (nodeIndex) => {
    setSelectedNodeIndex(nodeIndex);
    setShowDiagnostics(true);
    setDiagnostics(null);
    
    try {
      const response = await fetch(`${API_BASE}/nodes/${nodeIndex}/diagnostics`);
      if (!response.ok) {
        throw new Error('Failed to fetch diagnostics');
      }
      const data = await response.json();
      setDiagnostics(data);
    } catch (err) {
      console.error('Diagnostics error:', err);
      setDiagnostics({ error: err.message });
    }
  };

  const formatStatus = (status) => {
    if (!status || status === "unknown") return { label: "Unknown", className: "node-status-unknown" };
    if (status === "reachable") return { label: "Connected", className: "node-status-ok" };
    if (status === "unreachable") return { label: "Unreachable", className: "node-status-bad" };
    return { label: status, className: "node-status-unknown" };
  };

  const formatLastChecked = (timestamp) => {
    if (!timestamp) return "Never";
    const date = new Date(timestamp);
    return date.toLocaleString();
  };

  return (
    <section className="panel">
      <div className="panel-header">
        <h2>Worker Nodes</h2>
        <span className="node-count">{nodes.length} nodes</span>
      </div>
      
      {error && (
        <div className="error-message">
          <span className="error-icon">⚠️</span>
          {error}
        </div>
      )}
      
      <form className="node-form" onSubmit={handleSubmit}>
        <div className="field">
          <label htmlFor="node-ip">IP Address</label>
          <input
            id="node-ip"
            name="ip"
            placeholder="192.168.1.100"
            value={form.ip}
            onChange={handleChange}
            required
            pattern="^(?:(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.){3}(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)$"
          />
        </div>
        <div className="field">
          <label htmlFor="node-username">Username</label>
          <input
            id="node-username"
            name="username"
            placeholder="root"
            value={form.username}
            onChange={handleChange}
            required
            minLength="2"
          />
        </div>
        <div className="field">
          <label htmlFor="node-password">Password</label>
          <input
            id="node-password"
            name="password"
            type="password"
            placeholder="••••••••"
            value={form.password}
            onChange={handleChange}
            required
            minLength="4"
          />
        </div>
        <button 
          className="secondary-btn" 
          type="submit" 
          disabled={loading || isSubmitting}
        >
          {isSubmitting ? "Adding..." : "Add Worker Node"}
        </button>
      </form>

      {quickCheck && (
        <div className="quick-check-card">
          <div className="quick-check-title">Quick Health Check ({quickCheck.ip})</div>
          {quickCheck.loading && <div className="quick-check-loading">Running diagnostics...</div>}
          {!quickCheck.loading && quickCheck.error && <div className="test-error-msg">{quickCheck.error}</div>}
          {!quickCheck.loading && quickCheck.result?.fallback && quickCheck.result?.node && (
            <div className="quick-check-grid">
              <div className="quick-pill">
                Reachability:{" "}
                <span className={quickCheck.result.node.status === "reachable" ? "test-success" : "test-warning"}>
                  {quickCheck.result.node.status || "unknown"}
                </span>
              </div>
              <div className="quick-pill">
                Last Checked:{" "}
                <span>{quickCheck.result.node.last_checked ? formatLastChecked(quickCheck.result.node.last_checked) : "Never"}</span>
              </div>
            </div>
          )}
          {!quickCheck.loading && quickCheck.result?.tests && (
            <div className="quick-check-grid">
              <div className="quick-pill">
                Ping: <span className={quickCheck.result.tests.ping?.success ? "test-success" : "test-error"}>
                  {quickCheck.result.tests.ping?.success ? "OK" : "Failed"}
                </span>
              </div>
              <div className="quick-pill">
                SSH 22: <span className={quickCheck.result.tests.port_scan?.["22"] === "open" ? "test-success" : "test-error"}>
                  {quickCheck.result.tests.port_scan?.["22"] === "open" ? "Open" : quickCheck.result.tests.port_scan?.["22"] || "Unknown"}
                </span>
              </div>
              <div className="quick-pill">
                DNS: <span className={quickCheck.result.tests.dns?.success ? "test-success" : "test-warning"}>
                  {quickCheck.result.tests.dns?.success ? "Resolved" : "Not resolved"}
                </span>
              </div>
            </div>
          )}
        </div>
      )}
      
      <div className="table-wrapper">
        <table className="nodes-table">
          <thead>
            <tr>
              <th>IP Address</th>
              <th>Username</th>
              <th>Status</th>
              <th>Last Checked</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            {nodes.map((node, idx) => {
              const statusInfo = formatStatus(node.status);
              return (
                <tr key={`${node.ip}-${idx}`} className={node.status === "unreachable" ? "node-unreachable" : ""}>
                  <td className="ip-cell">{node.ip}</td>
                  <td>{node.username}</td>
                  <td>
                    <span className={`node-status ${statusInfo.className}`}>
                      {statusInfo.label}
                    </span>
                  </td>
                  <td className="last-checked">
                    {formatLastChecked(node.last_checked)}
                  </td>
                  <td>
                    <button
                      className="ghost-btn"
                      onClick={() => runDiagnostics(idx)}
                      disabled={loading}
                      title="Run diagnostics"
                      style={{ marginRight: '8px', padding: '4px 8px', fontSize: '0.8rem' }}
                    >
                      🔍
                    </button>
                    <button
                      className="delete-btn"
                      onClick={() => {
                        if (window.confirm(`Are you sure you want to delete node ${node.ip}?`)) {
                          onRemove(idx);
                        }
                      }}
                      disabled={loading}
                      title="Delete node"
                    >
                      🗑️
                    </button>
                  </td>
                </tr>
              );
            })}
            {nodes.length === 0 && (
              <tr>
                <td colSpan={5} className="empty-state">
                  <div className="empty-content">
                    <span className="empty-icon">🖥️</span>
                    <p>No worker nodes configured</p>
                    <p>Add your first node above to get started</p>
                  </div>
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
      
      {showDiagnostics && (
        <div className="diagnostics-modal" onClick={(e) => {
          if (e.target === e.currentTarget) {
            setShowDiagnostics(false);
          }
        }}>
          <div className="diagnostics-content">
            <div className="diagnostics-header">
              <h3>Node Diagnostics</h3>
              <button 
                className="ghost-btn" 
                onClick={() => setShowDiagnostics(false)}
                style={{ padding: '4px 8px' }}
              >
                ✕
              </button>
            </div>
            
            {diagnostics ? (
              <div className="diagnostics-results">
                {diagnostics.error ? (
                  <div className="error-message">
                    <span className="error-icon">⚠️</span>
                    {diagnostics.error}
                  </div>
                ) : (
                  <>
                    <div className="diagnostic-section">
                      <h4>Node Information</h4>
                      <div className="diagnostic-grid">
                        <div><strong>IP:</strong> {diagnostics.node.ip}</div>
                        <div><strong>Username:</strong> {diagnostics.node.username}</div>
                        <div><strong>Status:</strong> {diagnostics.node.status}</div>
                        <div><strong>Last Checked:</strong> {formatLastChecked(diagnostics.node.last_checked)}</div>
                      </div>
                    </div>
                    
                    <div className="diagnostic-section">
                      <h4>Connectivity Tests</h4>
                      
                      {diagnostics.tests.ping && (
                        <div className="test-result">
                          <strong>Ping Test:</strong> 
                          <span className={diagnostics.tests.ping.success ? "test-success" : "test-error"}>
                            {diagnostics.tests.ping.success ? "✓ Passed" : "✗ Failed"}
                          </span>
                          {diagnostics.tests.ping.output && (
                            <pre className="test-output">{diagnostics.tests.ping.output}</pre>
                          )}
                          {diagnostics.tests.ping.error && (
                            <div className="test-error-msg">{diagnostics.tests.ping.error}</div>
                          )}
                        </div>
                      )}
                      
                      {diagnostics.tests.port_scan && (
                        <div className="test-result">
                          <strong>Port Scan:</strong>
                          <div className="port-results">
                            {Object.entries(diagnostics.tests.port_scan).map(([port, result]) => (
                              <div key={port} className="port-result">
                                <span>Port {port}:</span>
                                <span className={`
                                  ${result === "open" ? "test-success" : "test-error"}
                                  ${result.includes("timeout") ? "test-warning" : ""}
                                `}>
                                  {result === "open" ? "✓ Open" : result === "timeout" ? "⏱ Timeout" : `✗ ${result}`}
                                </span>
                              </div>
                            ))}
                          </div>
                        </div>
                      )}
                      
                      {diagnostics.tests.dns && (
                        <div className="test-result">
                          <strong>DNS Resolution:</strong>
                          <span className={diagnostics.tests.dns.success ? "test-success" : "test-error"}>
                            {diagnostics.tests.dns.success ? "✓ Success" : "✗ Failed"}
                          </span>
                          {diagnostics.tests.dns.hostname && (
                            <div>Hostname: {diagnostics.tests.dns.hostname}</div>
                          )}
                          {diagnostics.tests.dns.error && (
                            <div className="test-error-msg">{diagnostics.tests.dns.error}</div>
                          )}
                        </div>
                      )}
                    </div>
                  </>
                )}
              </div>
            ) : (
              <div className="loading-diagnostics">
                <div className="spinner"></div>
                <p>Running diagnostics...</p>
              </div>
            )}
          </div>
        </div>
      )}
    </section>
  );
}

function HealthView({ metrics, onRefresh, loading, nodes, apiBase }) {
  const total = Math.max(metrics.total, 1);
  const connectedRate = Math.round((metrics.connected / total) * 100);
  const unreachableRate = Math.round((metrics.unreachable / total) * 100);
  const unknownRate = Math.max(0, 100 - connectedRate - unreachableRate);
  const [detailedChecks, setDetailedChecks] = useState({});
  const [checksLoading, setChecksLoading] = useState(false);
  const [checksError, setChecksError] = useState(null);
  const recentCheck = nodes
    .map((n) => n.last_checked)
    .filter(Boolean)
    .sort((a, b) => new Date(b) - new Date(a))[0];

  const runDetailedChecks = async () => {
    if (!nodes.length) return;
    setChecksLoading(true);
    setChecksError(null);
    try {
      const results = await Promise.all(
        nodes.map(async (_, idx) => {
          try {
            const res = await fetch(`${apiBase}/nodes/${idx}/diagnostics`);
            if (!res.ok) throw new Error("diagnostics failed");
            const data = await res.json();
            return [idx, data.tests || {}];
          } catch {
            return [idx, {}];
          }
        })
      );
      const mapped = {};
      results.forEach(([idx, tests]) => {
        mapped[idx] = tests;
      });
      setDetailedChecks(mapped);
      const failedCount = Object.values(mapped).filter((t) => !t || Object.keys(t).length === 0).length;
      if (failedCount > 0) {
        setChecksError(`Detailed checks unavailable for ${failedCount} node(s).`);
      }
    } catch {
      setChecksError("Unable to run detailed checks.");
    } finally {
      setChecksLoading(false);
    }
  };

  const runRefreshAndChecks = async () => {
    await onRefresh?.();
    await runDetailedChecks();
  };

  useEffect(() => {
    if (!nodes.length) {
      setDetailedChecks({});
      setChecksError(null);
      return;
    }
    runDetailedChecks();
  }, [nodes.length]);

  return (
    <section className="panel">
      <div className="panel-header">
        <h2>SSH Validation</h2>
        <div className="monitor-controls">
          <button className="ghost-btn" onClick={runRefreshAndChecks} disabled={checksLoading || loading}>
          {checksLoading || loading ? "Checking..." : "Run SSH Health Check"}
        </button>
        </div>
      </div>
      <div className="health-check-tags">
        <span className="health-tag">Ping checks</span>
        <span className="health-tag">SSH port checks</span>
        <span className="health-tag">DNS checks</span>
        <span className="health-tag">Reachability status</span>
      </div>
      <div className="node-health-metrics">
        <div className="metric">
          <span className="label">Total Nodes</span>
          <span className="value">{metrics.total}</span>
        </div>
        <div className="metric">
          <span className="label">Connected</span>
          <span className="value">{metrics.connected}</span>
        </div>
        <div className="metric">
          <span className="label">Unreachable</span>
          <span className="value">{metrics.unreachable}</span>
        </div>
      </div>

      <div className="health-section">
        <div className="health-score-card">
          <div className="health-score-label">Node Health Score</div>
          <div className="health-score-value">{connectedRate}%</div>
          <div className="health-score-sub">
            Last check: {recentCheck ? new Date(recentCheck).toLocaleString() : "Never"}
          </div>
        </div>
        <div className="health-bars">
          <div className="health-bar-row">
            <span>Connected</span>
            <div className="health-bar-track"><div className="health-bar-fill health-ok" style={{ width: `${connectedRate}%` }} /></div>
            <span>{connectedRate}%</span>
          </div>
          <div className="health-bar-row">
            <span>Unreachable</span>
            <div className="health-bar-track"><div className="health-bar-fill health-bad" style={{ width: `${unreachableRate}%` }} /></div>
            <span>{unreachableRate}%</span>
          </div>
          <div className="health-bar-row">
            <span>Unknown</span>
            <div className="health-bar-track"><div className="health-bar-fill health-neutral" style={{ width: `${unknownRate}%` }} /></div>
            <span>{unknownRate}%</span>
          </div>
        </div>
      </div>

      <div className="health-node-list">
        {checksError && <div className="health-node-empty">{checksError}</div>}
        <div className="health-node-header">
          <span>Node</span>
          <span>Status</span>
          <span>Ping</span>
          <span>SSH 22</span>
          <span>DNS</span>
          <span>Last Checked</span>
        </div>
        {nodes.length === 0 && (
          <div className="health-node-empty">No nodes added yet. Add a node and run SSH health check.</div>
        )}
        {nodes.map((node, idx) => (
          <div key={`${node.ip}-${idx}`} className="health-node-row">
            <span className="health-node-ip">{node.ip}</span>
            <span className={`node-status ${node.status === "reachable" ? "node-status-ok" : node.status === "unreachable" ? "node-status-bad" : "node-status-unknown"}`}>
              {node.status || "unknown"}
            </span>
            <span className={`check-badge ${detailedChecks[idx]?.ping?.success ? "check-ok" : detailedChecks[idx]?.ping ? "check-bad" : "check-unknown"}`}>
              {detailedChecks[idx]?.ping?.success ? "Pass" : detailedChecks[idx]?.ping ? "Fail" : "-"}
            </span>
            <span className={`check-badge ${detailedChecks[idx]?.port_scan?.["22"] === "open" ? "check-ok" : detailedChecks[idx]?.port_scan?.["22"] ? "check-bad" : "check-unknown"}`}>
              {detailedChecks[idx]?.port_scan?.["22"] === "open" ? "Open" : detailedChecks[idx]?.port_scan?.["22"] || "-"}
            </span>
            <span className={`check-badge ${detailedChecks[idx]?.dns?.success ? "check-ok" : detailedChecks[idx]?.dns ? "check-bad" : "check-unknown"}`}>
              {detailedChecks[idx]?.dns?.success ? "Resolved" : detailedChecks[idx]?.dns ? "No" : "-"}
            </span>
            <span className="health-node-time">
              {node.last_checked ? new Date(node.last_checked).toLocaleString() : "Never"}
            </span>
          </div>
        ))}
      </div>
    </section>
  );
}

function LogInsightsView({ insightData, apiBase, toast }) {
  const analysis = useMemo(
    () => analyzeLogs(insightData.logs || "", insightData.status || "Idle"),
    [insightData.logs, insightData.status]
  );
  const eventSummary = useMemo(
    () => summarizeDeploymentEvents(insightData.logs || "", insightData.status || "Idle"),
    [insightData.logs, insightData.status]
  );

  const totalSignals = Math.max(analysis.errorCount + analysis.warningCount + analysis.successCount, 1);
  const errorPct = Math.round((analysis.errorCount / totalSignals) * 100);
  const warnPct = Math.round((analysis.warningCount / totalSignals) * 100);
  const okPct = Math.round((analysis.successCount / totalSignals) * 100);
  const verdictClass = analysis.verdict.toLowerCase();
  const [llmLoading, setLlmLoading] = useState(false);
  const [llmError, setLlmError] = useState(null);
  const [llmSummary, setLlmSummary] = useState(null);

  const generateLlmSummary = async () => {
    if (!insightData.logs || !insightData.logs.trim()) {
      toast?.show?.("No logs available to summarize", "error");
      return;
    }
    setLlmLoading(true);
    setLlmError(null);
    try {
      const response = await fetch(`${apiBase}/logs/summarize-llm`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          run_id: insightData.runId,
          status: insightData.status,
          logs: insightData.logs
        })
      });
      const payload = await response.json();
      if (!response.ok) {
        throw new Error(payload.detail || "Failed to generate LLM summary");
      }
      setLlmSummary(payload);
      toast?.show?.("LLM summary generated");
    } catch (err) {
      setLlmError(err.message);
      toast?.show?.(err.message, "error");
    } finally {
      setLlmLoading(false);
    }
  };

  return (
    <section className="panel">
      <div className="panel-header">
        <h2>Log Insights</h2>
        <div className="insights-actions">
          <button className="ghost-btn" onClick={generateLlmSummary} disabled={llmLoading}>
            {llmLoading ? "Generating..." : "Generate LLM Summary"}
          </button>
          <span className={`insight-verdict insight-${verdictClass}`}>{analysis.verdict}</span>
        </div>
      </div>

      <div className="deployment-meta">
        <div className="meta-card">
          <span className="label">Run ID</span>
          <span className="value value-run-id">{insightData.runId || "-"}</span>
        </div>
        <div className="meta-card">
          <span className="label">Task Streams</span>
          <span className="value">{insightData.taskStreams || 0}</span>
        </div>
        <div className="meta-card">
          <span className="label">Last Updated</span>
          <span className="value">
            {insightData.lastUpdated ? new Date(insightData.lastUpdated).toLocaleTimeString() : "-"}
          </span>
        </div>
      </div>

      <div className="insight-chart">
        <div className="chart-row">
          <span className="chart-label">Error Density</span>
          <div className="chart-track"><div className="chart-fill chart-error" style={{ width: `${errorPct}%` }} /></div>
          <span className="chart-value">{errorPct}%</span>
        </div>
        <div className="chart-row">
          <span className="chart-label">Warning Density</span>
          <div className="chart-track"><div className="chart-fill chart-warn" style={{ width: `${warnPct}%` }} /></div>
          <span className="chart-value">{warnPct}%</span>
        </div>
        <div className="chart-row">
          <span className="chart-label">Success Signals</span>
          <div className="chart-track"><div className="chart-fill chart-ok" style={{ width: `${okPct}%` }} /></div>
          <span className="chart-value">{okPct}%</span>
        </div>
      </div>

      <div className="insight-findings">
        <div className="finding-card finding-low">
          <div className="finding-title">Deployment Event Summary</div>
          <div className="finding-text">{eventSummary.summary}</div>
          {eventSummary.executedSteps.length > 0 && (
            <div className="event-steps">
              {eventSummary.executedSteps.map((item, idx) => (
                <div key={`${item.step}-${idx}`} className="event-step">
                  <span className={`event-dot event-${item.status}`} />
                  <span>{item.step}</span>
                </div>
              ))}
            </div>
          )}
        </div>

        {analysis.hits.length > 0 ? (
          analysis.hits.map((hit) => (
            <div key={hit.id} className={`finding-card finding-${hit.severity}`}>
              <div className="finding-title">{hit.label}</div>
              <div className="finding-text">{hit.suggestion}</div>
            </div>
          ))
        ) : (
          <div className="finding-card finding-low">
            <div className="finding-title">No risky patterns detected</div>
            <div className="finding-text">Run a deployment and this panel will auto-summarize actionable hints.</div>
          </div>
        )}
      </div>

      {(llmSummary || llmError) && (
        <div className="llm-summary">
          <h3>LLM Summary</h3>
          {llmError && <div className="error-message">{llmError}</div>}
          {llmSummary && (
            <>
              <p className="finding-text">{llmSummary.summary}</p>
              <div className="llm-confidence">Confidence: {llmSummary.confidence || "medium"}</div>
              {Array.isArray(llmSummary.executed_steps) && llmSummary.executed_steps.length > 0 && (
                <div className="llm-list">
                  <h4>Executed Steps</h4>
                  <ul>
                    {llmSummary.executed_steps.map((item, idx) => (
                      <li key={`step-${idx}`}>{item}</li>
                    ))}
                  </ul>
                </div>
              )}
              {Array.isArray(llmSummary.security_suggestions) && llmSummary.security_suggestions.length > 0 && (
                <div className="llm-list">
                  <h4>Security Suggestions</h4>
                  <ul>
                    {llmSummary.security_suggestions.map((item, idx) => (
                      <li key={`security-${idx}`}>{item}</li>
                    ))}
                  </ul>
                </div>
              )}
              {Array.isArray(llmSummary.root_causes) && llmSummary.root_causes.length > 0 && (
                <div className="llm-list">
                  <h4>Likely Root Causes</h4>
                  <ul>
                    {llmSummary.root_causes.map((item, idx) => (
                      <li key={`cause-${idx}`}>{item}</li>
                    ))}
                  </ul>
                </div>
              )}
              {Array.isArray(llmSummary.recommended_actions) && llmSummary.recommended_actions.length > 0 && (
                <div className="llm-list">
                  <h4>Recommended Actions</h4>
                  <ul>
                    {llmSummary.recommended_actions.map((item, idx) => (
                      <li key={`action-${idx}`}>{item}</li>
                    ))}
                  </ul>
                </div>
              )}
            </>
          )}
        </div>
      )}
    </section>
  );
}

function DeploymentView({ apiBase, toast, onStatusChange, onInsightUpdate }) {
  const [currentRunId, setCurrentRunId] = useState(null);
  const [status, setStatus] = useState("Idle");
  const [logs, setLogs] = useState("");
  const [taskStreams, setTaskStreams] = useState(0);
  const [lastUpdated, setLastUpdated] = useState(null);
  const [pollTimer, setPollTimer] = useState(null);
  const [isDeploying, setIsDeploying] = useState(false);
  const [deploymentError, setDeploymentError] = useState(null);
  const [autoScroll, setAutoScroll] = useState(true);
  const logRef = useRef(null);

  const setStatusBoth = (s) => {
    setStatus(s);
    onStatusChange?.(s);
  };

  const startPolling = (runId) => {
    if (pollTimer) clearInterval(pollTimer);
    const id = setInterval(async () => {
      try {
        const res = await fetch(`${apiBase}/deployments/${encodeURIComponent(runId)}/live-logs`);
        if (!res.ok) {
          const errorData = await res.json();
          throw new Error(errorData.detail || "Failed to fetch deployment logs");
        }
        const data = await res.json();
        setLogs(data.log || "");
        setTaskStreams(data.task_streams || 0);
        onInsightUpdate?.({
          runId,
          status: data.state ? (["success", "failed", "upstream_failed"].includes(data.state) ? (data.state === "success" ? "Completed" : "Failed") : "Running") : status,
          logs: data.log || "",
          taskStreams: data.task_streams || 0,
          lastUpdated: new Date().toISOString()
        });
        if (data.state) {
          if (["success", "failed", "upstream_failed"].includes(data.state)) {
            setStatusBoth(data.state === "success" ? "Completed" : "Failed");
            setIsDeploying(false);
            clearInterval(id);
          } else {
            setStatusBoth("Running");
          }
        }
        setLastUpdated(new Date());
        setDeploymentError(null);
      } catch (err) {
        console.error(err);
        setDeploymentError(err.message);
        if (err.message.includes("404")) {
          setStatusBoth("Failed");
          setIsDeploying(false);
          clearInterval(id);
        }
      }
    }, 3000);
    setPollTimer(id);
  };

  const startDeployment = async () => {
    setDeploymentError(null);
    setIsDeploying(true);
    try {
      setStatusBoth("Running");
      setLogs("");
      setTaskStreams(0);
      onInsightUpdate?.({
        runId: null,
        status: "Running",
        logs: "",
        taskStreams: 0,
        lastUpdated: new Date().toISOString()
      });
      const res = await fetch(`${apiBase}/deployments/start`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: "{}"
      });
      if (!res.ok) {
        const errorData = await res.json();
        throw new Error(errorData.detail || "Failed to start deployment");
      }
      const data = await res.json();
      setCurrentRunId(data.run_id);
      setLastUpdated(new Date());
      toast?.show?.(data.message || "Deployment started successfully.");
      startPolling(data.run_id);
    } catch (err) {
      console.error(err);
      setStatusBoth("Failed");
      setIsDeploying(false);
      setDeploymentError(err.message);
      toast?.show?.(err.message, "error");
    }
  };

  const clearLogs = () => {
    setLogs("");
    setDeploymentError(null);
    setTaskStreams(0);
    onInsightUpdate?.({
      runId: currentRunId,
      status,
      logs: "",
      taskStreams: 0,
      lastUpdated: new Date().toISOString()
    });
  };

  const copyLogs = async () => {
    if (!logs) return;
    try {
      await navigator.clipboard.writeText(logs);
      toast?.show?.("Logs copied to clipboard.");
    } catch {
      toast?.show?.("Unable to copy logs", "error");
    }
  };

  useEffect(() => {
    return () => {
      if (pollTimer) clearInterval(pollTimer);
    };
  }, [pollTimer]);

  useEffect(() => {
    if (!autoScroll || !logRef.current) return;
    logRef.current.scrollTop = logRef.current.scrollHeight;
  }, [logs, autoScroll]);

  const statusClass = status?.toLowerCase().replace(/\s+/g, "-");
  return (
    <>
      <section className="panel deployment-status">
        <div className="panel-header">
          <h2>Airflow Deployment</h2>
          <button 
            className="primary-btn" 
            onClick={startDeployment}
            disabled={isDeploying}
          >
            {isDeploying ? "Deploying..." : "Start Infrastructure Deployment"}
          </button>
        </div>
        <div className="deployment-info">
          <p style={{ marginBottom: '12px', color: 'var(--text-muted)', fontSize: '0.9rem' }}>
            🚀 This will trigger an Airflow DAG that deploys applications across all reachable worker nodes.
            The DAG will execute SSH commands on each node for system updates, Docker installation, and application deployment.
          </p>
        </div>
        <div className="deployment-meta">
          <div className="meta-card">
            <span className="label">Current Run ID</span>
            <span className="value value-run-id">{currentRunId || "-"}</span>
          </div>
          <div className="meta-card">
            <span className="label">DAG</span>
            <span className="value">deployment_workflow</span>
          </div>
          <div className="meta-card">
            <span className="label">Status</span>
            <span className={`status-chip ${statusClass}`}>{status}</span>
          </div>
          <div className="meta-card">
            <span className="label">Last Updated</span>
            <span className="value">{lastUpdated ? lastUpdated.toLocaleTimeString() : "-"}</span>
          </div>
          <div className="meta-card">
            <span className="label">Task Streams</span>
            <span className="value">{taskStreams}</span>
          </div>
        </div>
        {deploymentError && (
          <div className="error-message">
            <span className="error-icon">⚠️</span>
            {deploymentError}
          </div>
        )}
      </section>

      <section className="panel workflow-monitor">
        <div className="panel-header">
          <h2>Workflow Monitor</h2>
          <div className="monitor-controls">
            <button className="ghost-btn" onClick={copyLogs} disabled={!logs}>
              Copy Logs
            </button>
            <button className="ghost-btn" onClick={() => setAutoScroll((v) => !v)}>
              {autoScroll ? "Auto-scroll: On" : "Auto-scroll: Off"}
            </button>
            <button className="ghost-btn" onClick={clearLogs} disabled={!logs && !deploymentError}>
              Clear Logs
            </button>
            <span className={`label monitor-status monitor-status-${statusClass}`}>Status: {status}</span>
          </div>
        </div>
        <pre ref={logRef} className="log-output">
          {logs || "No logs available. Start a deployment to see real-time logs from Airflow."}
        </pre>
      </section>
    </>
  );
}

function AgentOpsView({ agentOpsState, onRetry, runId, nodes }) {
  const isLoading = agentOpsState.status === "loading";
  const isReady = agentOpsState.status === "ready" && agentOpsState.data;
  const isError = agentOpsState.status === "error";
  const analyses = isReady
    ? Array.isArray(agentOpsState.data?.analyses) && agentOpsState.data.analyses.length > 0
      ? agentOpsState.data.analyses
      : [agentOpsState.data]
    : [];
  const placeholderCards = Object.entries(AGENT_OPS_PLACEHOLDER)
    .filter(([key]) => key !== "final_summary")
    .map(([key, value]) => ({ key, ...value }));

  // Phase 2: Autofix state per incident
  const [autofixStates, setAutofixStates] = useState({});

  // Phase 3: Queue status polling
  const [queueData, setQueueData] = useState({ available: false, errors: [] });

  useEffect(() => {
    let intervalId;
    const fetchQueueStatus = async () => {
      try {
        const agentApiBase = API_BASE.replace(/:8000\b/, ":8001");
        const res = await fetch(`${agentApiBase}/api/agents/queue-status`);
        if (res.ok) {
          const data = await res.json();
          setQueueData({ available: data.queue_available, errors: data.queued_errors || [] });
        }
      } catch (e) {
        // silently ignore fetch errors for polling
      }
    };
    fetchQueueStatus();
    intervalId = setInterval(fetchQueueStatus, 5000);
    return () => clearInterval(intervalId);
  }, []);

  const triggerAutofix = async () => {
    const firstAnalysis = analyses[0];
    if (!firstAnalysis) return;

    const failedTask = firstAnalysis?.combined_summary?.failed_task
      || firstAnalysis?.monitor_agent?.output?.failed_task
      || firstAnalysis?.analysis_task_id
      || "task-0";
    const logText = firstAnalysis?.log_analysis_agent?.output?.error_message
      || firstAnalysis?.combined_summary?.error_message
      || `Task ${failedTask} failed`;
    const dagRunId = firstAnalysis?.workflow_agent?.output?.dag_run_id
      || agentOpsState.data?.dag_run_id
      || runId
      || "mock_run";

    setAutofixStates(prev => ({
      ...prev,
      global: { status: "loading", data: null, error: null }
    }));

    const agentApiBase = API_BASE.replace(/:8000\b/, ":8001");

    try {
      const response = await fetch(`${agentApiBase}/api/agents/autofix-pipeline`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          dag_id: "deployment_workflow",
          dag_run_id: dagRunId,
          failed_task: failedTask,
          task_state: "failed",
          log_text: logText,
          timestamp: new Date().toISOString(),
          worker_nodes: nodes || [],
          auto_approve: true,
          mock: false
        })
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || "Autofix failed");

      setAutofixStates(prev => ({
        ...prev,
        global: { status: "ready", data: data, error: null }
      }));
    } catch (err) {
      setAutofixStates(prev => ({
        ...prev,
        global: { status: "error", data: null, error: err.message }
      }));
    }
  };

  const globalAutofixState = autofixStates["global"];
  const globalAutofixData = globalAutofixState?.data;

  return (
    <section className="panel">
      <div className="panel-header">
        <h2>Agent Ops</h2>
        <div className="agentops-actions">
          <span className="agentops-badge">
            {isReady ? "Live Agent Output" : isLoading ? "Analyzing Failed Run" : "Waiting For Failure"}
          </span>
          <button className="ghost-btn" onClick={onRetry} disabled={!runId || isLoading}>
            {isLoading ? "Analyzing..." : "Retry Analysis"}
          </button>
        </div>
      </div>

      <div className="agentops-hero">
        <div>
          <div className="agentops-kicker">
            {isReady ? "Live Workflow" : isLoading ? "Analysis Running" : "Auto Triggered On Failure"}
          </div>
          <h3>
            {isReady
              ? "Agent reasoning for every failed task in the latest deployment run"
              : "Separate outputs for each agent will land here"}
          </h3>
          <p>
            {isReady
              ? `Current run: ${runId || "-"}. These sections reflect the failed task analyses returned by the agent pipeline.`
              : isLoading
                ? "The failed run has been handed off to the agent pipeline. The cards will populate as soon as the analysis response returns."
                : "When a deployment run fails, this panel will automatically send the failed task log to the agent service and render each agent response separately."}
          </p>
        </div>
        <div className="agentops-flow">
          <span>Run Context</span>
          <span>Parsed Logs</span>
          <span>Agent Outputs</span>
          <span>Autofix</span>
          <span>Final Brief</span>
        </div>
      </div>

      {isError && <div className="error-message">{agentOpsState.error}</div>}

      {isReady ? (
        <>
          <div className="agentops-run-summary">
            <div className="agent-summary">
              <div className="agent-summary-header">
                <h3>Run Summary</h3>
                <div style={{ display: 'flex', gap: '0.75rem', alignItems: 'center' }}>
                  <span className="agent-card-status">
                    {agentOpsState.data?.failed_task_count || analyses.length} failures
                  </span>
                  <button
                    className="autofix-btn"
                    onClick={() => triggerAutofix()}
                    disabled={globalAutofixState?.status === "loading"}
                    style={{ fontSize: '0.85rem', padding: '0.5rem 1.2rem' }}
                  >
                    {globalAutofixState?.status === "loading" ? "⏳ Analyzing & Fixing..." :
                     globalAutofixState?.status === "ready" ? "✅ Autofix Complete" :
                     "🔧 Apply Autofix (All Errors)"}
                  </button>
                </div>
              </div>
              <div className="agent-summary-grid">
                <div className="agent-output-row">
                  <span>dag run id</span>
                  <strong>{agentOpsState.data?.dag_run_id || runId || "-"}</strong>
                </div>
                <div className="agent-output-row">
                  <span>failed task count</span>
                  <strong>{agentOpsState.data?.failed_task_count || analyses.length}</strong>
                </div>
                <div className="agent-output-row">
                  <span>failed tasks</span>
                  <strong>{(agentOpsState.data?.failed_tasks || []).join(", ") || "-"}</strong>
                </div>
                <div className="agent-output-row">
                  <span>highest severity</span>
                  <strong>{agentOpsState.data?.highest_severity || "-"}</strong>
                </div>
              </div>
            </div>
          </div>

          {/* Global Autofix Error */}
          {globalAutofixState?.status === "error" && (
            <div className="error-message autofix-error" style={{ margin: '1rem 0' }}>
              <span className="error-icon">⚠️</span>
              Autofix failed: {globalAutofixState.error}
            </div>
          )}

          {/* Global Autofix Results — DAG Analysis + DAG Patch + Attempt badges */}
          {globalAutofixData && (
            <div className="agentops-autofix-results" style={{ marginBottom: '1.5rem' }}>
              {/* Attempt Status Badges */}
              <div style={{ display: 'flex', gap: '1rem', marginBottom: '1rem', flexWrap: 'wrap' }}>
                {globalAutofixData.attempt_1 && (
                  <span className={`agent-card-status ${globalAutofixData.attempt_1.status === 'success' ? 'status-fixed' : globalAutofixData.attempt_1.status === 'skipped' ? '' : 'status-failed'}`}
                    style={{ padding: '0.4rem 1rem', borderRadius: '6px', fontSize: '0.85rem' }}>
                    Attempt 1 (DAG Fix): {globalAutofixData.attempt_1.status === 'success' ? '✅ Success' :
                      globalAutofixData.attempt_1.status === 'skipped' ? 'ℹ️ Skipped' : '❌ ' + (globalAutofixData.attempt_1.status || 'Failed')}
                  </span>
                )}
                {globalAutofixData.attempt_2 && (
                  <span className={`agent-card-status ${globalAutofixData.attempt_2.status === 'success' ? 'status-fixed' : 'status-failed'}`}
                    style={{ padding: '0.4rem 1rem', borderRadius: '6px', fontSize: '0.85rem' }}>
                    Attempt 2 (SSH Fix): {globalAutofixData.attempt_2.status === 'success' ? '✅ Success' : '❌ Failed'}
                  </span>
                )}
              </div>

              {/* Autofix Agent Cards */}
              <div className="agentops-grid">
                {["dag_analysis_agent", "dag_patch_agent", "fix_generator_agent", "fix_executor_agent", "validation_agent"].map((key) => {
                  const cardData = globalAutofixData[key];
                  if (!cardData) return null;
                  const title = AGENT_OPS_PLACEHOLDER[key]?.title || key;
                  return (
                    <article key={`autofix-${key}`} className="agent-card agent-card-autofix">
                      <div className="agent-card-header">
                        <h3>{title}</h3>
                        <span className="agent-card-status">Live</span>
                      </div>
                      <p className="agent-card-summary">{cardData.thinking?.[0] || "Agent completed."}</p>
                      <ul className="agent-card-list">
                        {(cardData.thinking || []).map((item, i) => (
                          <li key={`autofix-${key}-${i}`}>{item}</li>
                        ))}
                      </ul>
                      {cardData.output && (
                        <div className="agent-output">
                          {Object.entries(cardData.output).map(([k, v]) => (
                            <div key={`autofix-${key}-${k}`} className="agent-output-row">
                              <span>{k.replace(/_/g, " ")}</span>
                              <strong>
                                {Array.isArray(v) ? (v.length > 0 ? JSON.stringify(v) : "-") :
                                 typeof v === 'object' && v !== null ? JSON.stringify(v) :
                                 v === null || v === undefined || v === "" ? "-" :
                                 typeof v === 'boolean' ? (v ? "true" : "false") : String(v)}
                              </strong>
                            </div>
                          ))}
                        </div>
                      )}
                    </article>
                  );
                })}
              </div>

              {/* Autofix Summary Card */}
              {globalAutofixData.autofix_summary && (
                <div className="agent-summary autofix-summary-card" style={{ marginTop: '1rem' }}>
                  <div className="agent-summary-header">
                    <h3>🔧 Autofix Summary</h3>
                    <span className={`agent-card-status ${globalAutofixData.autofix_summary.final_status === 'fixed' ? 'status-fixed' : 'status-failed'}`}>
                      {globalAutofixData.autofix_summary.final_status === 'fixed' ? '✅ All Errors Resolved' :
                       globalAutofixData.autofix_summary.final_status === 'escalated' ? '🚨 Escalated to Human' : '❌ Fix Failed'}
                    </span>
                  </div>
                  <div className="agent-summary-grid">
                    {Object.entries(globalAutofixData.autofix_summary).map(([key, value]) => (
                      <div key={`autofix-summary-${key}`} className="agent-output-row">
                        <span>{key.replace(/_/g, " ")}</span>
                        <strong>
                          {value === true ? "Yes" : value === false ? "No" :
                           value === null || value === undefined || value === "" ? "-" : String(value)}
                        </strong>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}

          <div className="agentops-incidents">
            {analyses.map((analysis, index) => {
              const analysisTaskId =
                analysis?.combined_summary?.failed_task ||
                analysis?.analysis_task_id ||
                `failure-${index + 1}`;

              // Phase 1 cards only — autofix cards are now global above
              const cards = AGENT_CARD_ORDER.filter(k =>
                !["dag_analysis_agent", "dag_patch_agent", "fix_generator_agent", "fix_executor_agent", "validation_agent"].includes(k)
              ).map((key) => {
                return {
                  key,
                  title: AGENT_OPS_PLACEHOLDER[key]?.title || key,
                  status: "Live",
                  summary: analysis[key]?.thinking?.[0] || "No agent summary available.",
                  bullets: analysis[key]?.thinking || ["Agent completed without extra commentary."],
                  output: analysis[key]?.output || null,
                };
              }).filter(Boolean);

              const combinedSummary = analysis?.combined_summary || null;

              return (
                <section key={`${analysisTaskId}-${index}`} className="agentops-incident">
                  <div className="agentops-incident-header">
                    <div>
                      <div className="agentops-kicker">Failed Task {index + 1}</div>
                      <h3>{analysisTaskId}</h3>
                    </div>
                    <div className="agentops-incident-actions">
                      <span className="agent-card-status">{combinedSummary?.severity || "ready"}</span>
                    </div>
                  </div>

                  <div className="agentops-grid">
                    {cards.map((card) => (
                      <article key={`${analysisTaskId}-${card.key || card.title}`} className="agent-card">
                        <div className="agent-card-header">
                          <h3>{card.title}</h3>
                          <span className="agent-card-status">{card.status}</span>
                        </div>
                        <p className="agent-card-summary">{card.summary}</p>
                        <ul className="agent-card-list">
                          {card.bullets.map((item, bulletIndex) => (
                            <li key={`${analysisTaskId}-${card.title}-${bulletIndex}`}>{item}</li>
                          ))}
                        </ul>
                        {card.output && (
                          <div className="agent-output">
                            {Object.entries(card.output).map(([key, value]) => (
                              <div key={`${analysisTaskId}-${card.title}-${key}`} className="agent-output-row">
                                <span>{key.replace(/_/g, " ")}</span>
                                <strong>
                                  {Array.isArray(value)
                                    ? value.join(", ")
                                    : value === null || value === undefined || value === ""
                                      ? "-"
                                      : String(value)}
                                </strong>
                              </div>
                            ))}
                          </div>
                        )}
                      </article>
                    ))}
                  </div>

                  {combinedSummary && (
                    <div className="agent-summary">
                      <div className="agent-summary-header">
                        <h3>Combined Summary</h3>
                        <span className="agent-card-status">{combinedSummary.severity || "ready"}</span>
                      </div>
                      <div className="agent-summary-grid">
                        {Object.entries(combinedSummary).map(([key, value]) => (
                          <div key={`${analysisTaskId}-${key}`} className="agent-output-row">
                            <span>{key.replace(/_/g, " ")}</span>
                            <strong>
                              {Array.isArray(value)
                                ? value.join(", ")
                                : value === null || value === undefined || value === ""
                                  ? "-"
                                  : String(value)}
                            </strong>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                </section>
              );
            })}
          </div>
          
          {/* Phase 3: Escalated Incidents from Queue */}
          {queueData.errors.length > 0 && (
            <div className="agentops-incidents">
              <div className="agent-summary-header" style={{ marginTop: '2rem' }}>
                <h3>Escalated Queue Incidents</h3>
                <span className="agent-card-status status-failed">{queueData.errors.length} in queue</span>
              </div>
              {queueData.errors.map((qErr, idx) => {
                const analysisTaskId = qErr.task_id || `queue-${idx}`;
                const autofixState = autofixStates[analysisTaskId];
                
                // Create a mock analysis object to pass to triggerAutofix
                const mockAnalysis = {
                  combined_summary: {
                    failed_task: qErr.task_id,
                    error_message: qErr.log_text,
                    error_type: "QueueEscalation",
                    root_cause: "Lingering error in HPC queue"
                  }
                };

                return (
                  <section key={`q-${qErr.job_id}`} className="agentops-incident" style={{ borderColor: '#f59e0b' }}>
                    <div className="agentops-incident-header">
                      <div>
                        <div className="agentops-kicker" style={{ color: '#f59e0b' }}>Lingering HPC Error</div>
                        <h3>{qErr.task_id}</h3>
                        <p style={{ fontSize: '0.85rem', color: '#9ca3af', marginTop: '0.5rem' }}>
                          Job ID: {qErr.job_id} • Enqueued: {new Date(qErr.enqueued_at).toLocaleString()}
                        </p>
                      </div>
                      <div className="agentops-incident-actions">
                        <button
                          className="autofix-btn"
                          onClick={() => triggerAutofix(mockAnalysis, idx)}
                          disabled={autofixState?.status === "loading"}
                          style={{ background: '#f59e0b', color: '#0f172a' }}
                        >
                          {autofixState?.status === "loading" ? "⏳ Fixing..." :
                           autofixState?.status === "ready" ? "✅ Fixed" :
                           "🔧 Re-Fix Escalation"}
                        </button>
                      </div>
                    </div>
                    
                    <div className="agentops-grid">
                      <article className="agent-card">
                        <div className="agent-card-header">
                          <h3>Error Log Context</h3>
                          <span className="agent-card-status">Escalated</span>
                        </div>
                        <p className="agent-card-summary">This error was found lingering in the hpc_error_logs queue during Validation check or arrived asynchronously.</p>
                        <div className="agent-output">
                          <pre style={{ whiteSpace: 'pre-wrap', wordBreak: 'break-all', fontSize: '0.8rem' }}>
                            {qErr.log_text}
                          </pre>
                        </div>
                      </article>
                      
                      {/* Show Fix Generator/Executor if it was re-fixed */}
                      {autofixState?.data && ["fix_generator_agent", "fix_executor_agent", "validation_agent"].map(key => {
                        const cardData = autofixState.data[key];
                        if (!cardData) return null;
                        return (
                          <article key={key} className="agent-card agent-card-autofix">
                            <div className="agent-card-header">
                              <h3>{AGENT_OPS_PLACEHOLDER[key]?.title || key}</h3>
                              <span className="agent-card-status">Live</span>
                            </div>
                            <p className="agent-card-summary">{cardData.thinking?.[0]}</p>
                            <ul className="agent-card-list">
                              {cardData.thinking?.map((item, i) => <li key={i}>{item}</li>)}
                            </ul>
                          </article>
                        );
                      })}
                    </div>
                  </section>
                );
              })}
            </div>
          )}
        </>
      ) : (
        <div className="agentops-grid">
          {placeholderCards.map((card) => (
            <article key={card.key || card.title} className="agent-card">
              <div className="agent-card-header">
                <h3>{card.title}</h3>
                <span className="agent-card-status">{card.status}</span>
              </div>
              <p className="agent-card-summary">{card.summary}</p>
              <ul className="agent-card-list">
                {card.bullets.map((item, index) => (
                  <li key={`${card.title}-${index}`}>{item}</li>
                ))}
              </ul>
            </article>
          ))}
        </div>
      )}
    </section>
  );
}

export default function App() {
  const [activeView, setActiveView] = useState("overview");
  const [lastDeploymentStatus, setLastDeploymentStatus] = useState("Idle");
  const [insightData, setInsightData] = useState({
    runId: null,
    status: "Idle",
    logs: "",
    taskStreams: 0,
    lastUpdated: null
  });
  const [agentOpsState, setAgentOpsState] = useState({
    status: "idle",
    analyzedRunId: null,
    data: null,
    error: null
  });
  const { show, node: toastNode } = useToast();
  const nodesHook = useNodes(API_BASE, { show });
  const totalNodesForRate = Math.max(nodesHook.metrics.total, 1);
  const connectedRate = Math.round((nodesHook.metrics.connected / totalNodesForRate) * 100);
  const sidebarStatusClass = lastDeploymentStatus.toLowerCase().replace(/\s+/g, "-");

  const switchView = (id) => setActiveView(id);

  const triggerAgentOpsAnalysis = async (override = null) => {
    const payload = override || insightData;
    const inferredFailure = hasFailureSignals(payload?.logs);
    if (!payload?.runId || !payload.logs || (!inferredFailure && payload.status !== "Failed")) return;

    setAgentOpsState((prev) => ({
      ...prev,
      status: "loading",
      analyzedRunId: payload.runId,
      error: null
    }));

    try {
      const response = await fetch(`${API_BASE}/agent-ops/analyze`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          run_id: payload.runId,
          status: inferredFailure ? "Failed" : payload.status,
          logs: payload.logs
        })
      });
      const data = await response.json();
      if (!response.ok) {
        throw new Error(data.detail || "Failed to analyze failed run");
      }
      setAgentOpsState({
        status: "ready",
        analyzedRunId: payload.runId,
        data,
        error: null
      });
      show("Agent Ops analysis ready");
    } catch (err) {
      setAgentOpsState({
        status: "error",
        analyzedRunId: payload.runId,
        data: null,
        error: err.message
      });
      show(err.message, "error");
    }
  };

  useEffect(() => {
    const inferredFailure = hasFailureSignals(insightData.logs);

    if (insightData.status === "Running") {
      setAgentOpsState((prev) =>
        prev.status === "loading"
          ? prev
          : {
              status: "idle",
              analyzedRunId: null,
              data: null,
              error: null
            }
      );
      return;
    }

    if (
      (insightData.status === "Failed" || inferredFailure) &&
      insightData.runId &&
      insightData.logs &&
      agentOpsState.analyzedRunId !== insightData.runId &&
      agentOpsState.status !== "loading"
    ) {
      triggerAgentOpsAnalysis();
    }
  }, [insightData, agentOpsState.analyzedRunId, agentOpsState.status]);

  const views = {
    overview: (
      <OverviewView
        metrics={nodesHook.metrics}
        lastRunId={insightData.runId}
        lastStatus={lastDeploymentStatus}
      />
    ),
    nodes: (
      <NodesView
        nodes={nodesHook.nodes}
        onAdd={nodesHook.add}
        onRemove={nodesHook.remove}
        loading={nodesHook.loading}
        error={nodesHook.error}
      />
    ),
    health: (
      <HealthView
        metrics={nodesHook.metrics}
        onRefresh={nodesHook.refreshStatus}
        loading={nodesHook.loading}
        nodes={nodesHook.nodes}
        apiBase={API_BASE}
      />
    ),
    deployment: (
      <DeploymentView
        apiBase={API_BASE}
        toast={{ show }}
        onStatusChange={setLastDeploymentStatus}
        onInsightUpdate={setInsightData}
      />
    ),
    insights: <LogInsightsView insightData={insightData} apiBase={API_BASE} toast={{ show }} />,
    agentops: (
      <AgentOpsView
        agentOpsState={agentOpsState}
        onRetry={() => triggerAgentOpsAnalysis()}
        runId={insightData.runId}
        nodes={nodesHook.nodes}
      />
    )
  };

  return (
    <div className="app-shell">
      <header className="app-header">
        <div className="top-nav-left">
          <img className="brand-logo" src={workflowLogo} alt="Workflow logo" />
          <div className="top-brand-text">
            <strong>AI Enabled Build Workflow</strong>
            <span>for Infrastructure Deployment</span>
          </div>
        </div>
        <div className="top-nav-search">
          <input type="text" placeholder="Search nodes, runs, logs..." aria-label="Search" />
        </div>
        <div className="header-meta">
          <span className="env-badge">DEV</span>
          <button className="nav-icon-btn" title="Notifications" aria-label="Notifications">🔔</button>
          <button className="nav-icon-btn" title="Settings" aria-label="Settings">⚙</button>
          <div className="admin-profile">
            <div className="admin-avatar">AD</div>
            <div className="admin-info">
              <strong>Admin</strong>
              <span>Platform Owner</span>
            </div>
          </div>
        </div>
      </header>
      <div className="layout">
        <aside className="sidebar">
          <div className="sidebar-header">
            <span className="sidebar-brand">
              <img className="sidebar-logo" src={secureInfraLogo} alt="SecureInfra logo" />
              <span className="sidebar-title">SecureInfra</span>
            </span>
          </div>
          <nav className="sidebar-nav">
            {TABS.map((tab) => (
              <button
                key={tab.id}
                className={
                  "nav-item" + (activeView === tab.id ? " nav-item-active" : "")
                }
                onClick={() => switchView(tab.id)}
              >
                <span className="nav-icon">{tab.icon}</span>
                <span className="nav-label">{tab.label}</span>
              </button>
            ))}
          </nav>
          <div className="sidebar-insights">
            <div className="sidebar-insights-title">Live Pulse</div>
            <div className="sidebar-pct">{connectedRate}% Connected</div>
            <div className="sidebar-meter">
              <div className="sidebar-meter-fill" style={{ width: `${connectedRate}%` }} />
            </div>
            <div className="sidebar-mini-grid">
              <div className="mini-tile">
                <span>Total</span>
                <strong>{nodesHook.metrics.total}</strong>
              </div>
              <div className="mini-tile">
                <span>Unreachable</span>
                <strong>{nodesHook.metrics.unreachable}</strong>
              </div>
            </div>
            <div className={`sidebar-deploy sidebar-deploy-${sidebarStatusClass}`}>
              Deployment: {lastDeploymentStatus}
            </div>
          </div>
        </aside>
        <main className="app-main">
          {Object.entries(views).map(([viewId, content]) => (
            <div
              key={viewId}
              style={{ display: activeView === viewId ? "block" : "none" }}
              aria-hidden={activeView !== viewId}
            >
              {content}
            </div>
          ))}
        </main>
      </div>
      {toastNode}
    </div>
  );
}




