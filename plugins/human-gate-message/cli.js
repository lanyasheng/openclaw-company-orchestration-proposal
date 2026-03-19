#!/usr/bin/env node
/**
 * human-gate-message CLI — Manage pending decisions
 * 
 * Usage:
 *   node cli.js list                     # List all pending decisions
 *   node cli.js get <decisionId>         # Get decision details
 *   node cli.js approve <decisionId>     # Approve a decision
 *   node cli.js reject <decisionId> [reason]  # Reject a decision
 *   node cli.js withdraw <decisionId> [reason] # Withdraw a decision
 */

import { cliApprove, cliReject, cliWithdraw, cliList, cliGet } from "./index.js";

const cmd = process.argv[2];
const arg1 = process.argv[3];
const arg2 = process.argv[4];

switch (cmd) {
  case "list": {
    const decisions = cliList();
    console.log(JSON.stringify(decisions, null, 2));
    break;
  }
  
  case "get": {
    if (!arg1) {
      console.error("Usage: node cli.js get <decisionId>");
      process.exit(1);
    }
    const decision = cliGet(arg1);
    if (!decision) {
      console.error(`Decision ${arg1} not found`);
      process.exit(1);
    }
    console.log(JSON.stringify(decision, null, 2));
    break;
  }
  
  case "approve": {
    if (!arg1) {
      console.error("Usage: node cli.js approve <decisionId>");
      process.exit(1);
    }
    const result = cliApprove(arg1);
    console.log(JSON.stringify(result, null, 2));
    break;
  }
  
  case "reject": {
    if (!arg1) {
      console.error("Usage: node cli.js reject <decisionId> [reason]");
      process.exit(1);
    }
    const result = cliReject(arg1, "cli", arg2 || "manual-reject");
    console.log(JSON.stringify(result, null, 2));
    break;
  }
  
  case "withdraw": {
    if (!arg1) {
      console.error("Usage: node cli.js withdraw <decisionId> [reason]");
      process.exit(1);
    }
    const result = cliWithdraw(arg1, "cli", arg2 || "manual-withdraw");
    console.log(JSON.stringify(result, null, 2));
    break;
  }
  
  default:
    console.log("Usage: node cli.js <list|get|approve|reject|withdraw> [args]");
    process.exit(1);
}
