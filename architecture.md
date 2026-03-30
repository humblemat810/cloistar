# OpenClaw × Kogwistar Integration Architecture

## Executive Summary
OpenClaw executes actions. Kogwistar governs and records them as durable system state.

---

## OpenClaw Architecture
- Gateway (control plane)
- Runtime (agent loop)
- Plugin system
- Hooks (before/after tool calls)
- Channels & Sessions

Execution model:
observe → think → act → observe

---

## Kogwistar Architecture
- Event log (authoritative)
- Hypergraph model
- Workflow runtime (governance)
- CDC + SSE
- Projections

Principle:
State is derived from history.

---

## Key Differences
| Aspect | OpenClaw | Kogwistar |
|--------|---------|-----------|
| Role | Execution | Governance |
| State | Runtime | Event-sourced |
| Trace | Logs | Truth |
| Replay | Limited | First-class |

---

## Integration Architecture

Client → Gateway → Runtime → Hook → Kogwistar Bridge → Event Log → Projection → SSE

---

## Seam Mapping

### Gateway
Entry point for messages

### Hooks
before_tool_call → policy evaluation

### Runtime
Emit execution events

### Event
Convert actions into durable records

### Approval
Pause → approve → resume

---

## Governance Workflow
proposed action → record → evaluate → decision → record outcome

---

## Responsibilities

### OpenClaw
- execution
- routing
- sessions
- hooks

### Kogwistar
- governance
- audit
- replay
- graph

---

## Security Model
- OpenClaw = untrusted executor
- Kogwistar = authority
- guardrail outside runtime

---

## Final Model
OpenClaw = execution engine  
Kogwistar = governance + memory + replay
