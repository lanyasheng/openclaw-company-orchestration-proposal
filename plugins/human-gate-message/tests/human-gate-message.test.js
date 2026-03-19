/**
 * Minimal tests for human-gate-message plugin.
 *
 * Run:
 *   node tests/human-gate-message.test.js
 */

import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

process.env.OPENCLAW_HUMAN_GATE_DIR = fs.mkdtempSync(
  path.join(os.tmpdir(), "human-gate-message-")
);

const {
  cliApprove,
  cliReject,
  cliWithdraw,
  cliList,
  cliGet,
  genId,
  getStoragePaths
} = await import("../index.js");

const { pendingFile, decisionLog } = getStoragePaths();

function seedDecision(overrides = {}) {
  const decisionId = overrides.decisionId || genId();
  const decision = {
    decisionId,
    agentId: "test",
    sessionKey: "agent:test:discord:channel:999",
    channel: "999",
    messagePreview: "test message",
    fullMessage: "this is a test message for human-gate plugin",
    createdAt: new Date().toISOString(),
    expiresAt: new Date(Date.now() + 60_000).toISOString(),
    status: "pending",
    verdictAt: null,
    verdictBy: null,
    verdictReason: null,
    ...overrides
  };

  fs.mkdirSync(path.dirname(pendingFile), { recursive: true });

  const pending = fs.existsSync(pendingFile)
    ? JSON.parse(fs.readFileSync(pendingFile, "utf-8"))
    : {};

  pending[decisionId] = decision;
  fs.writeFileSync(pendingFile, JSON.stringify(pending, null, 2));
  return decision;
}

function cleanup() {
  fs.rmSync(process.env.OPENCLAW_HUMAN_GATE_DIR, { recursive: true, force: true });
}

try {
  console.log("\n=== Test 1: seed + get ===");
  const seeded = seedDecision();
  const fetched = cliGet(seeded.decisionId);
  assert.ok(fetched, "decision should exist");
  assert.equal(fetched.decisionId, seeded.decisionId);
  assert.equal(fetched.status, "pending");
  console.log("✅ PASS: seed + get");

  console.log("\n=== Test 2: list ===");
  const listed = cliList();
  assert.ok(Array.isArray(listed), "list should return an array");
  assert.ok(listed.some((item) => item.decisionId === seeded.decisionId));
  console.log("✅ PASS: list");

  console.log("\n=== Test 3: approve ===");
  const approved = cliApprove(seeded.decisionId, "tester");
  assert.ok(approved, "approve should return a decision");
  assert.equal(approved.status, "approved");
  assert.equal(approved.verdictBy, "tester");
  assert.equal(cliGet(seeded.decisionId).status, "approved");
  console.log("✅ PASS: approve");

  console.log("\n=== Test 4: reject ===");
  const rejectSeed = seedDecision();
  const rejected = cliReject(rejectSeed.decisionId, "tester", "test rejection reason");
  assert.equal(rejected.status, "rejected");
  assert.equal(rejected.verdictReason, "test rejection reason");
  console.log("✅ PASS: reject");

  console.log("\n=== Test 5: withdraw ===");
  const withdrawSeed = seedDecision();
  const withdrawn = cliWithdraw(withdrawSeed.decisionId, "tester", "user changed mind");
  assert.equal(withdrawn.status, "withdrawn");
  assert.equal(withdrawn.verdictReason, "user changed mind");
  console.log("✅ PASS: withdraw");

  console.log("\n=== Test 6: audit log ===");
  assert.ok(fs.existsSync(decisionLog), "decision log should exist");
  const lines = fs.readFileSync(decisionLog, "utf-8").trim().split("\n");
  assert.ok(lines.length >= 3, "decision log should record updates");
  console.log("✅ PASS: audit log");

  console.log("\n=== All Tests Passed ===\n");
} finally {
  cleanup();
}
