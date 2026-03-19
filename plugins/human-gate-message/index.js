/**
 * human-gate-message v0.1.0 — Minimal human approval gate for message tool calls.
 *
 * Source of truth lives in the orchestration repo.
 * Runtime should only keep the thinnest glue:
 *   1. load this plugin
 *   2. expose a verdict surface (CLI / UI / webhook)
 *   3. write approved/rejected/withdrawn decisions back to the shared store
 */

import fs from "fs";
import os from "os";
import path from "path";

const DEFAULT_TIMEOUT_MS = 5 * 60 * 1000; // 5 minutes
const DECISION_RETENTION_MS = 60 * 60 * 1000; // 1 hour
const VERDICT_BY_STATUS = Object.freeze({
  approved: "approve",
  rejected: "reject",
  timeout: "timeout",
  withdrawn: "withdraw"
});

let pluginLogger = null;
let pluginConfig = null;
let pendingDecisions = new Map();

function resolveHumanGateDir(config = pluginConfig) {
  return (
    config?.storageDir ||
    process.env.OPENCLAW_HUMAN_GATE_DIR ||
    path.join(os.homedir(), ".openclaw", "shared-context", "human-gate")
  );
}

export function getStoragePaths(config = pluginConfig) {
  const dir = resolveHumanGateDir(config);
  return {
    dir,
    pendingFile: path.join(dir, "pending.json"),
    decisionLog: path.join(dir, "decisions.jsonl"),
    payloadDir: path.join(dir, "decision-payloads")
  };
}

function getDecisionPayloadPath(decisionId, config = pluginConfig) {
  const { payloadDir } = getStoragePaths(config);
  return path.join(payloadDir, `${decisionId}.json`);
}

// --- Persistence ---

function ensureDir(config = pluginConfig) {
  const { dir, payloadDir } = getStoragePaths(config);
  if (!fs.existsSync(dir)) fs.mkdirSync(dir, { recursive: true });
  if (!fs.existsSync(payloadDir)) fs.mkdirSync(payloadDir, { recursive: true });
}

function loadPending(config = pluginConfig) {
  const { pendingFile } = getStoragePaths(config);

  try {
    if (fs.existsSync(pendingFile)) {
      const data = JSON.parse(fs.readFileSync(pendingFile, "utf-8"));
      pendingDecisions = new Map(Object.entries(data));
      return;
    }
  } catch {
    // fall through and start fresh
  }

  pendingDecisions = new Map();
}

function savePending(config = pluginConfig) {
  const { pendingFile } = getStoragePaths(config);

  try {
    ensureDir(config);
    const tmp = `${pendingFile}.tmp`;
    fs.writeFileSync(tmp, JSON.stringify(Object.fromEntries(pendingDecisions), null, 2));
    fs.renameSync(tmp, pendingFile);
  } catch (err) {
    pluginLogger?.warn(`human-gate: failed to save pending: ${err?.message}`);
  }
}

function appendDecisionLog(entry, config = pluginConfig) {
  const { decisionLog } = getStoragePaths(config);

  try {
    ensureDir(config);
    fs.appendFileSync(decisionLog, `${JSON.stringify(entry)}\n`);
  } catch {
    // non-fatal
  }
}

function writeDecisionPayload(decision, config = pluginConfig) {
  try {
    const payload = buildDecisionPayload(decision);
    ensureDir(config);
    const payloadPath = getDecisionPayloadPath(decision.decisionId, config);
    const tmp = `${payloadPath}.tmp`;
    fs.writeFileSync(tmp, JSON.stringify(payload, null, 2));
    fs.renameSync(tmp, payloadPath);
    return payloadPath;
  } catch (err) {
    pluginLogger?.debug?.(`human-gate: skip payload export for ${decision?.decisionId}: ${err?.message}`);
    return null;
  }
}

function genId() {
  const ts = new Date().toISOString().replace(/[-:T:]/g, "").slice(0, 14);
  const r = Math.random().toString(36).slice(2, 6);
  return `hg_${ts}_${r}`;
}

function normalizeHumanGateContext(humanGate) {
  if (!humanGate || typeof humanGate !== "object") return null;

  const taskId = humanGate.taskId || humanGate.task_id;
  const resumeToken = humanGate.resumeToken || humanGate.resume_token;
  const sourceRef = humanGate.sourceRef || humanGate.source_ref;

  if (!taskId || !resumeToken || !sourceRef) return null;

  return {
    taskId: String(taskId),
    resumeToken: String(resumeToken),
    sourceRef: String(sourceRef),
    sourceTransport: String(humanGate.sourceTransport || humanGate.source_transport || "message"),
    prompt: humanGate.prompt ? String(humanGate.prompt) : null
  };
}

function extractHumanGateContext(args) {
  return normalizeHumanGateContext(args?.humanGate || args?.metadata?.humanGate || null);
}

export function buildDecisionPayload(decision) {
  if (!decision || typeof decision !== "object") {
    throw new Error("decision record is required");
  }

  const verdict = VERDICT_BY_STATUS[decision.status];
  if (!verdict) {
    throw new Error(`decision ${decision.decisionId || "unknown"} is not terminal`);
  }

  const humanGate = normalizeHumanGateContext(decision.humanGate);
  if (!humanGate) {
    throw new Error(`decision ${decision.decisionId || "unknown"} missing humanGate context`);
  }

  const payload = {
    decision_id: String(decision.decisionId),
    task_id: humanGate.taskId,
    resume_token: humanGate.resumeToken,
    verdict,
    source: {
      transport: humanGate.sourceTransport,
      ref: humanGate.sourceRef
    },
    actor: {
      id: String(decision.verdictBy || "system")
    },
    decided_at: String(decision.verdictAt || decision.createdAt)
  };

  if (decision.verdictReason) {
    payload.reason = String(decision.verdictReason);
  }

  return payload;
}

// --- Decision Management ---

function createDecision(agentId, sessionKey, messageContent, timeoutMs, humanGate = null) {
  const decisionId = genId();
  const now = new Date().toISOString();

  const decision = {
    decisionId,
    agentId,
    sessionKey,
    channel: parseChannelFromSessionKey(sessionKey),
    messagePreview: truncate(messageContent, 200),
    fullMessage: messageContent,
    createdAt: now,
    expiresAt: new Date(Date.now() + timeoutMs).toISOString(),
    status: "pending",
    verdictAt: null,
    verdictBy: null,
    verdictReason: null
  };

  if (humanGate) {
    decision.humanGate = humanGate;
  }

  pendingDecisions.set(decisionId, decision);
  savePending();
  appendDecisionLog({ event: "created", ...decision });

  pluginLogger?.info(`human-gate: created decision ${decisionId} for agent ${agentId}`);
  return decision;
}

function getDecision(decisionId) {
  return pendingDecisions.get(decisionId);
}

function updateDecision(decisionId, status, verdictBy, reason = null) {
  const decision = pendingDecisions.get(decisionId);
  if (!decision) return null;

  decision.status = status;
  decision.verdictAt = new Date().toISOString();
  decision.verdictBy = verdictBy;
  decision.verdictReason = reason;

  savePending();
  appendDecisionLog({ event: "updated", ...decision });
  writeDecisionPayload(decision);

  pluginLogger?.info(`human-gate: decision ${decisionId} ${status} by ${verdictBy}`);
  return decision;
}

function pruneExpired() {
  const now = Date.now();
  let changed = false;

  for (const [id, decision] of pendingDecisions) {
    if (decision.status === "pending") {
      const expiresAt = new Date(decision.expiresAt).getTime();
      if (now > expiresAt) {
        updateDecision(id, "timeout", "system", "auto-timeout");
        changed = true;
      }
      continue;
    }

    const decidedAt = new Date(decision.verdictAt || decision.createdAt).getTime();
    if (now - decidedAt > DECISION_RETENTION_MS) {
      pendingDecisions.delete(id);
      changed = true;
    }
  }

  if (changed) savePending();
}

// --- Helpers ---

function truncate(str, maxLen) {
  if (typeof str !== "string") return "";
  if (str.length <= maxLen) return str;
  return `${str.slice(0, maxLen - 1)}…`;
}

function parseChannelFromSessionKey(sessionKey) {
  if (!sessionKey) return null;
  const match = sessionKey.match(/discord:channel:(\d+)/);
  return match ? match[1] : null;
}

function extractMessageContent(args) {
  return args?.message || args?.text || args?.content || "";
}

function shouldIntercept(agentId, action, args) {
  if (action !== "send") return false;

  const content = extractMessageContent(args);
  if (!content || content.trim().length === 0) return false;

  const allowAgents = pluginConfig?.allowAgents || [];
  if (allowAgents.length > 0 && !allowAgents.includes(agentId)) {
    return false;
  }

  return true;
}

function readVerdict(decisionId) {
  const decision = getDecision(decisionId);
  if (!decision) {
    return { status: "error", error: "decision_not_found" };
  }

  if (decision.status === "pending") return null;

  return {
    status: decision.status,
    verdictBy: decision.verdictBy,
    reason: decision.verdictReason
  };
}

function waitForVerdictSync(decisionId, timeoutMs) {
  const deadline = Date.now() + timeoutMs;

  while (Date.now() < deadline) {
    loadPending();
    const verdict = readVerdict(decisionId);
    if (verdict) return verdict;

    if (typeof Atomics !== "undefined" && typeof SharedArrayBuffer !== "undefined") {
      const sab = new SharedArrayBuffer(4);
      const ia = new Int32Array(sab);
      Atomics.wait(ia, 0, 0, 100);
    } else {
      const start = Date.now();
      while (Date.now() - start < 100) {
        // busy-wait fallback
      }
    }
  }

  updateDecision(decisionId, "timeout", "system", "sync-timeout");
  return { status: "timeout", verdictBy: "system", reason: "sync-timeout" };
}

function waitForVerdictViaApi(api, decisionId, timeoutMs) {
  const waitFor = api?.utils?.waitFor;
  if (typeof waitFor !== "function") return null;

  return waitFor(() => {
    loadPending();
    return readVerdict(decisionId);
  }, timeoutMs);
}

// --- Plugin API ---

export function activate(api, ctx) {
  pluginLogger = api.logger;
  pluginConfig = ctx?.config || {};

  const timeoutMs = pluginConfig?.timeoutSeconds
    ? pluginConfig.timeoutSeconds * 1000
    : DEFAULT_TIMEOUT_MS;

  const { dir } = getStoragePaths(pluginConfig);
  pluginLogger?.info(`human-gate-message: activated with timeout=${timeoutMs}ms dir=${dir}`);

  loadPending(pluginConfig);
  pruneExpired();

  const pruneInterval = setInterval(() => {
    loadPending(pluginConfig);
    pruneExpired();
  }, 5 * 60 * 1000);

  api.on("deactivate", () => {
    clearInterval(pruneInterval);
    savePending(pluginConfig);
  });

  api.on("before_tool_call", (event, toolCtx) => {
    const { toolName, args, sessionKey } = toolCtx;
    const agentId = toolCtx?.agentId || "unknown";

    if (toolName !== "message") return;

    if (!shouldIntercept(agentId, args?.action, args)) {
      pluginLogger?.debug(`human-gate: skipping intercept for ${agentId} action=${args?.action}`);
      return;
    }

    const content = extractMessageContent(args);
    const humanGate = extractHumanGateContext(args);
    const decision = createDecision(agentId, sessionKey, content, timeoutMs, humanGate);

    pluginLogger?.info(`human-gate: blocking message send for decision ${decision.decisionId}`);

    const verdict = waitForVerdictViaApi(api, decision.decisionId, timeoutMs)
      || waitForVerdictSync(decision.decisionId, timeoutMs);

    switch (verdict.status) {
      case "approved":
        pluginLogger?.info(`human-gate: message approved for ${decision.decisionId}`);
        break;

      case "rejected":
        pluginLogger?.warn(`human-gate: message rejected for ${decision.decisionId}`);
        event.preventDefault?.();
        event.result = {
          success: false,
          blocked: true,
          reason: verdict.reason || "human_reject",
          decisionId: decision.decisionId
        };
        break;

      case "timeout":
        pluginLogger?.warn(`human-gate: message timeout for ${decision.decisionId}`);
        event.preventDefault?.();
        event.result = {
          success: false,
          blocked: true,
          reason: "timeout",
          decisionId: decision.decisionId
        };
        break;

      case "withdrawn":
        pluginLogger?.info(`human-gate: message withdrawn for ${decision.decisionId}`);
        event.preventDefault?.();
        event.result = {
          success: false,
          blocked: true,
          reason: "withdrawn",
          decisionId: decision.decisionId
        };
        break;

      default:
        pluginLogger?.warn(`human-gate: unknown verdict ${verdict.status} for ${decision.decisionId}`);
        event.preventDefault?.();
        event.result = {
          success: false,
          blocked: true,
          reason: verdict.status || "unknown",
          decisionId: decision.decisionId
        };
    }
  });

  return {
    name: "human-gate-message",
    version: "0.1.0"
  };
}

// --- CLI helpers ---

export function cliApprove(decisionId, userId = "cli") {
  loadPending();
  return updateDecision(decisionId, "approved", userId, "cli-approve");
}

export function cliReject(decisionId, userId = "cli", reason = "cli-reject") {
  loadPending();
  return updateDecision(decisionId, "rejected", userId, reason);
}

export function cliWithdraw(decisionId, userId = "cli", reason = "cli-withdraw") {
  loadPending();
  return updateDecision(decisionId, "withdrawn", userId, reason);
}

export function cliList() {
  loadPending();
  return Array.from(pendingDecisions.values());
}

export function cliGet(decisionId) {
  loadPending();
  return getDecision(decisionId);
}

export function cliGetDecisionPayload(decisionId) {
  loadPending();
  const decision = getDecision(decisionId);
  if (!decision) return null;
  return buildDecisionPayload(decision);
}

export { genId, getDecisionPayloadPath };
