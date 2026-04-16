# OpenClaw -> Canonical Governance Adapter Design

## Decision Summary

OpenClaw should be treated as a boundary integration contract only.

It is not sufficient as the internal source of truth for a Kogwistar-style
substrate that cares about:

- append-only event history
- deterministic replay
- provenance-first auditability
- explicit governance state transitions
- approval suspend/resume lifecycle
- long-term canonical semantics independent of any one upstream producer

Recommended stance:

- Use OpenClaw schema as ingress/egress only.
- Introduce a canonical governance schema owned by us.
- Keep all compatibility logic inside one adapter layer.
- Append only canonical validated events to the authoritative event log.
- Preserve raw OpenClaw payloads as provenance evidence, not as canonical truth.

## Current Upstream Contract Snapshot

OpenClaw's current plugin hook contract is useful, but intentionally scoped to
plugin runtime control rather than authoritative event sourcing.

Observed upstream boundary shape:

- `before_tool_call` input includes `toolName`, `params`, optional `runId`,
  optional `toolCallId`
- tool context includes `agentId`, `sessionKey`, `sessionId`, `runId`,
  `toolName`, optional `toolCallId`
- `before_tool_call` output supports:
  - `params?`
  - `block?`
  - `blockReason?`
  - `requireApproval?`
- `requireApproval` supports:
  - `title`
  - `description`
  - `severity?`
  - `timeoutMs?`
  - `timeoutBehavior?`
  - `pluginId?`
  - `onResolution?`
- approval resolution values are:
  - `allow-once`
  - `allow-always`
  - `deny`
  - `timeout`
  - `cancelled`

Primary source references:

- [openclaw/src/plugins/types.ts](/home/azureuser/cloistar/openclaw/src/plugins/types.ts#L2140)
- [plugin-governance/src/governance-contract.ts](/home/azureuser/cloistar/plugin-governance/src/governance-contract.ts#L1)
- [bridge/app/models.py](/home/azureuser/cloistar/bridge/app/models.py#L7)

This upstream contract is good for pausing or blocking a tool call inside
OpenClaw. It is not a sufficient ontology for authoritative governance history.

## Architectural Position

### Boundary layering

Required layering:

1. External adapter schema
2. Internal canonical schema
3. Outbound projection schema

Desired flow:

```text
OpenClaw payload
-> strict adapter validation
-> canonicalization / normalization
-> canonical governance event(s)
-> authoritative append validation
-> append-only event log
-> projections / runtime actions
-> optional outbound OpenClaw projection
```

Not desired:

```text
OpenClaw payload
-> directly becomes internal truth
```

### Ownership rule

OpenClaw owns its hook DTOs.

We own:

- event identity
- event versioning
- policy provenance
- replay-safe reason structure
- approval lifecycle semantics
- canonical correlation and causation
- governance state transitions
- provenance references

## Recommended Canonical Model

### Canonical event envelope

Every authoritative governance event should use one common envelope.

```json
{
  "eventId": "uuid",
  "eventType": "governance.tool_call_observed.v1",
  "schemaVersion": 1,
  "occurredAt": "2026-04-01T06:20:10.199Z",
  "recordedAt": "2026-04-01T06:20:10.210Z",
  "correlationId": "run-or-governance-flow-id",
  "causationId": "prior-event-id-or-null",
  "streamId": "governance/tool-call/<governanceCallId>",
  "producer": {
    "system": "kogwistar-openclaw-adapter",
    "component": "bridge",
    "adapterVersion": "v1"
  },
  "subject": {
    "governanceCallId": "uuid",
    "approvalRequestId": null
  },
  "provenance": {
    "sourceSystem": "openclaw",
    "sourceEventType": "before_tool_call",
    "receiptId": "uuid",
    "payloadSha256": "hex",
    "sourceSchemaVersion": "openclaw-plugin-hook-unknown"
  },
  "data": {}
}
```

### Minimal canonical event types

The minimum useful internal model is event-oriented, not DTO-oriented.

#### `governance.tool_call_observed.v1`

Meaning:
Incoming proposal observed at the boundary and accepted for canonicalization.

Data:

```json
{
  "tool": {
    "name": "exec",
    "params": { "command": "rm -rf /" }
  },
  "executionContext": {
    "agentId": "optional",
    "sessionKey": "optional",
    "sessionId": "optional",
    "runId": "optional",
    "toolCallId": "optional"
  },
  "sourceRef": {
    "pluginId": "kogwistar-governance"
  }
}
```

#### `governance.decision_recorded.v1`

Meaning:
Canonical governance decision produced by policy evaluation.

Data:

```json
{
  "decisionId": "uuid",
  "disposition": "allow | block | require_approval",
  "reasons": [
    {
      "code": "policy.marker.rm_rf",
      "message": "Blocked by policy marker: rm -rf",
      "category": "policy"
    }
  ],
  "policyTrace": {
    "policyId": "optional",
    "ruleId": "optional",
    "ruleVersion": "optional"
  },
  "annotations": {
    "policy": "allow-default"
  }
}
```

#### `governance.approval_requested.v1`

Meaning:
An approval request became part of authoritative state.

Data:

```json
{
  "approvalRequestId": "uuid",
  "decisionId": "uuid",
  "title": "Approval required for exec",
  "description": "This tool is marked dangerous and requires explicit approval.",
  "severity": "warning",
  "timeoutMs": 120000,
  "timeoutBehavior": "deny",
  "approvalScope": "once | always",
  "status": "pending"
}
```

#### `governance.execution_suspended.v1`

Meaning:
Runtime execution is suspended pending external resolution.

Data:

```json
{
  "suspensionId": "uuid",
  "approvalRequestId": "uuid",
  "suspensionReason": "approval_required",
  "resumeCondition": "approval_resolved_positive"
}
```

#### `governance.approval_resolved.v1`

Meaning:
The approval request received a final outcome.

Data:

```json
{
  "approvalRequestId": "uuid",
  "resolution": "allow_once | allow_always | deny | timeout | cancelled",
  "resolvedAt": "2026-04-01T06:21:00.000Z",
  "resolvedBy": {
    "actorType": "user | system | channel | unknown",
    "actorId": "optional",
    "displayName": "optional"
  }
}
```

#### `governance.execution_resumed.v1`

Meaning:
Execution may proceed after a positive approval outcome.

Data:

```json
{
  "suspensionId": "uuid",
  "approvalRequestId": "uuid",
  "resumeReason": "approval_granted",
  "resumeMode": "single_use | persistent"
}
```

#### `governance.execution_denied.v1`

Meaning:
The suspended execution terminated without permission to continue.

Data:

```json
{
  "suspensionId": "uuid",
  "approvalRequestId": "uuid",
  "denyReason": "approval_denied | approval_timeout | approval_cancelled"
}
```

#### `governance.tool_call_completed.v1`

Meaning:
Observed terminal completion of the tool call.

Data:

```json
{
  "outcome": "success | error | unknown",
  "result": {},
  "error": null,
  "durationMs": 123
}
```

### Canonical state machine

Canonical state should be derivable by replay:

- observed
- decided_allow
- decided_block
- approval_pending
- suspended
- approved_once
- approved_always
- denied
- timed_out
- cancelled
- resumed
- completed

The authoritative model is the event stream, not a mutable approval row.

## Mapping Rules

### Boundary input -> canonical fields

| OpenClaw / adapter field | Canonical treatment | Notes |
|---|---|---|
| `pluginId` | `data.sourceRef.pluginId` | Pass through as provenance-level integration identity |
| `toolName` | `data.tool.name` | Normalize casing only if policy requires it |
| `params` | `data.tool.params` | Preserve structurally; may add canonical param normalization later |
| `ctx.agentId` | `data.executionContext.agentId` | Pass through |
| `ctx.sessionKey` | `data.executionContext.sessionKey` | Pass through |
| `ctx.sessionId` | `data.executionContext.sessionId` | Pass through as external session identifier, not canonical event id |
| `ctx.runId` or `event.runId` | `data.executionContext.runId` and `correlationId` candidate | Prefer stable run-scoped correlation if present |
| `toolCallId` | `data.executionContext.toolCallId` | Pass through |
| raw payload | provenance receipt only | Never authoritative domain truth |

### Decision output mapping

| OpenClaw-shaped decision | Canonical disposition | Additional canonical events |
|---|---|---|
| `allow` | `allow` | `governance.decision_recorded.v1` |
| `block + blockReason` | `block` | `governance.decision_recorded.v1` |
| `requireApproval` | `require_approval` | `governance.decision_recorded.v1`, `governance.approval_requested.v1`, `governance.execution_suspended.v1` |

### Approval resolution mapping

| OpenClaw resolution | Canonical resolution | Runtime consequence |
|---|---|---|
| `allow-once` | `allow_once` | append `approval_resolved`, then `execution_resumed` with `single_use` |
| `allow-always` | `allow_always` | append `approval_resolved`, then `execution_resumed` with `persistent` |
| `deny` | `deny` | append `approval_resolved`, then `execution_denied` |
| `timeout` | `timeout` | append `approval_resolved`, then `execution_denied` |
| `cancelled` | `cancelled` | append `approval_resolved`, then `execution_denied` |

### Transformations we must add

The adapter must add fields OpenClaw does not own:

- `eventId`
- `eventType`
- `schemaVersion`
- `occurredAt`
- `recordedAt`
- `streamId`
- `correlationId`
- `causationId`
- `governanceCallId`
- `decisionId`
- `approvalRequestId`
- `suspensionId`
- `policyTrace`
- structured `reasons[]`
- provenance receipt reference

### Fields that should not leak as internal truth

These may be preserved, but not promoted unchanged into canonical semantics:

- OpenClaw hook event object shape
- `requireApproval` object shape
- callback-oriented `onResolution`
- free-form `blockReason` as the sole explanation
- raw payload aliasing and optionality rules

## Append-Path Invariants

Only canonical validated internal events may enter the authoritative event log.

Required invariants:

1. Every appended event has a canonical envelope with explicit version.
2. Every appended event has stable identity and replay-safe timestamps.
3. Every appended event has provenance pointing to the raw ingress receipt.
4. Every event after the first has a valid causal predecessor or explicit null causation.
5. `approval_resolved` must reference an existing pending `approval_requested`.
6. `execution_resumed` may only occur after a positive approval resolution.
7. `execution_denied` may only occur after a negative or terminal approval resolution.
8. No raw OpenClaw payload blob is appended as the authoritative `data` body.
9. Canonicalization must be deterministic for a given adapter version and ingress payload.
10. Outbound projection is derived from canonical state, never the reverse.

## Provenance Strategy

### Principle

Raw integration payloads are evidence, not ontology.

### Recommended storage split

Store provenance separately from the authoritative canonical event log.

#### `integration_receipts`

Append each ingress payload to a boundary-evidence store:

```json
{
  "receiptId": "uuid",
  "receivedAt": "2026-04-01T06:20:10.199Z",
  "sourceSystem": "openclaw",
  "sourceEventType": "before_tool_call",
  "adapterVersion": "v1",
  "payloadSha256": "hex",
  "payload": { "raw": "full original JSON" },
  "parseStatus": "accepted | rejected",
  "notes": []
}
```

#### Canonical event log

Canonical events should contain only:

- receipt reference
- payload hash
- source metadata
- selected normalized fields needed for replay

This keeps replay deterministic while preserving full evidence for debugging and
forensic reconstruction.

### Why separate stores

If raw payloads are embedded directly into canonical events:

- canonical ontology becomes upstream-shaped
- replay semantics depend on loose external DTOs
- compatibility logic leaks everywhere
- event log becomes harder to evolve

## OpenClaw Coverage Assessment

### Covered by OpenClaw

- basic tool call observation
- allow / block / requireApproval control decisions
- tool identifiers and params
- some execution context:
  - `agentId`
  - `sessionKey`
  - `sessionId`
  - `runId`
  - `toolCallId`
- approval timeout knobs:
  - `timeoutMs`
  - `timeoutBehavior`
- final approval resolution callback values

### Partially covered

- decision reasoning
  - has `blockReason`
  - lacks structured reason taxonomy
- approval lifecycle
  - has final resolution values
  - lacks authoritative lifecycle event model
- provenance
  - has some contextual ids
  - lacks explicit receipt/evidence model
- policy traceability
  - can carry ad hoc annotations externally
  - lacks first-class `policyId`, `ruleId`, `ruleVersion`
- cross-runtime determinism
  - hook DTOs are simple
  - optional fields and callback semantics still require normalization

### Missing

- canonical event identity
- explicit canonical event type versioning
- authoritative append semantics
- structured replay-safe reasons
- causal graph fields:
  - `correlationId`
  - `causationId`
  - `streamId`
- explicit governance aggregate identity
- explicit suspension and resume events
- explicit denial terminal event
- actor attribution for approval resolution
- canonical provenance reference model
- separation of raw evidence from canonical truth
- policy lineage:
  - `policyId`
  - `ruleId`
  - `ruleVersion`
- audit-focused timestamps beyond transient runtime flow

## Risk Assessment

If OpenClaw schema becomes the internal canonical model, we inherit several
long-term risks:

### Tight coupling risk

Our substrate evolution becomes constrained by OpenClaw naming, omissions, and
upgrade path.

### Replay risk

A callback-shaped runtime contract is not the same thing as a replay-safe event
model. Important lifecycle transitions become implicit rather than explicit.

### Audit risk

A single `blockReason` string and raw hook payloads are not enough to explain
why a decision happened months later across versions and projections.

### Governance lifecycle risk

`requireApproval` is runtime control flow, not a full governance state machine.
Without canonical approval and suspension events, resume/deny semantics become
hard to reason about and harder to replay.

### Cross-runtime drift risk

Python and TypeScript will drift if each side interprets optional fields,
approval values, and free-form strings slightly differently.

Current repo example:

- OpenClaw resolution enum is `allow-once | allow-always | deny | timeout | cancelled`
- local plugin test currently uses `approved`

That mismatch alone shows why upstream runtime shapes should not be assumed to
be sufficient canonical truth.

## Recommendation

Recommendation:

`Use as boundary only + canonical internal model`

Interpretation:

- OpenClaw is sufficient for ingress and outbound compatibility.
- OpenClaw is not sufficient as-is for the core event-sourced governance model.
- We do not need to reject OpenClaw as an integration.
- We should reject it as the internal ontology.

## Minimal Extensions Needed For Replay-Safe Governance

If we wanted a schema that is good enough for our domain, the minimum additions
would be:

1. canonical event envelope with explicit version
2. stable event and stream identity
3. structured reasons instead of reason-only strings
4. explicit policy provenance fields
5. explicit approval lifecycle events
6. explicit execution suspension and resume events
7. actor attribution for resolution
8. provenance references to raw ingress receipts

These should be expressed in our canonical model, not bolted onto OpenClaw DTOs
across the codebase.

## Example Event Flow

### Example A: block

#### OpenClaw ingress DTO

```json
{
  "pluginId": "kogwistar-governance",
  "sessionId": "sess-1",
  "toolName": "exec",
  "params": { "command": "rm -rf /" },
  "rawEvent": {
    "toolName": "exec",
    "params": { "command": "rm -rf /" },
    "runId": "run-1"
  }
}
```

#### Canonical events

```json
{
  "eventType": "governance.tool_call_observed.v1",
  "data": {
    "tool": { "name": "exec", "params": { "command": "rm -rf /" } },
    "executionContext": { "sessionId": "sess-1", "runId": "run-1" },
    "sourceRef": { "pluginId": "kogwistar-governance" }
  }
}
```

```json
{
  "eventType": "governance.decision_recorded.v1",
  "data": {
    "decisionId": "dec-1",
    "disposition": "block",
    "reasons": [
      {
        "code": "policy.marker.rm_rf",
        "message": "Blocked by policy marker: rm -rf",
        "category": "policy"
      }
    ],
    "policyTrace": {
      "policyId": "default-governance",
      "ruleId": "block-pattern-rm-rf"
    }
  }
}
```

#### Outbound OpenClaw projection

```json
{
  "decision": "block",
  "reason": "Blocked by policy marker: rm -rf"
}
```

### Example B: require approval -> suspend -> allow once -> resume

#### OpenClaw ingress DTO

```json
{
  "pluginId": "kogwistar-governance",
  "sessionId": "sess-2",
  "toolName": "exec",
  "params": { "command": "echo hello" }
}
```

#### Canonical events

```json
{
  "eventType": "governance.tool_call_observed.v1"
}
```

```json
{
  "eventType": "governance.decision_recorded.v1",
  "data": {
    "decisionId": "dec-2",
    "disposition": "require_approval",
    "reasons": [
      {
        "code": "policy.tool.requires_approval",
        "message": "Tool marked dangerous",
        "category": "policy"
      }
    ]
  }
}
```

```json
{
  "eventType": "governance.approval_requested.v1",
  "data": {
    "approvalRequestId": "apr-1",
    "decisionId": "dec-2",
    "title": "Approval required for exec",
    "description": "This tool is marked dangerous and requires explicit approval.",
    "severity": "warning",
    "timeoutMs": 120000,
    "timeoutBehavior": "deny",
    "status": "pending"
  }
}
```

```json
{
  "eventType": "governance.execution_suspended.v1",
  "data": {
    "suspensionId": "sus-1",
    "approvalRequestId": "apr-1",
    "suspensionReason": "approval_required",
    "resumeCondition": "approval_resolved_positive"
  }
}
```

```json
{
  "eventType": "governance.approval_resolved.v1",
  "data": {
    "approvalRequestId": "apr-1",
    "resolution": "allow_once"
  }
}
```

```json
{
  "eventType": "governance.execution_resumed.v1",
  "data": {
    "suspensionId": "sus-1",
    "approvalRequestId": "apr-1",
    "resumeReason": "approval_granted",
    "resumeMode": "single_use"
  }
}
```

#### Outbound OpenClaw projection

```json
{
  "decision": "requireApproval",
  "title": "Approval required for exec",
  "description": "This tool is marked dangerous and requires explicit approval.",
  "severity": "warning",
  "timeoutMs": 120000,
  "timeoutBehavior": "deny",
  "approvalId": "apr-1"
}
```

Later resolution projection:

```json
{
  "approvalId": "apr-1",
  "resolution": "allow-once"
}
```

## Adapter Module Boundaries

Compatibility logic should live in one ingestion/projection module.

Suggested module split:

- `bridge/app/integrations/openclaw_dto.py`
  - strict boundary DTO validation only
- `bridge/app/integrations/openclaw_mapper.py`
  - OpenClaw DTO -> canonical event mapping
- `bridge/app/domain/governance_events.py`
  - canonical internal event definitions
- `bridge/app/domain/governance_append.py`
  - authoritative append validation and state transition checks
- `bridge/app/projections/openclaw_projection.py`
  - canonical decision/state -> OpenClaw outbound shape
- `bridge/app/provenance/receipts.py`
  - raw ingress evidence storage

## Test Fixture Layout

Recommended test layout:

```text
bridge/tests/fixtures/openclaw/
  before_tool_call.block.json
  before_tool_call.require_approval.json
  after_tool_call.success.json
  approval_resolution.allow_once.json
  approval_resolution.deny.json

bridge/tests/fixtures/canonical/
  tool_call_observed.block.json
  decision_recorded.block.json
  approval_requested.exec.json
  execution_suspended.exec.json
  approval_resolved.allow_once.json
  execution_resumed.allow_once.json

bridge/tests/fixtures/projections/
  outbound.block.json
  outbound.require_approval.json
  outbound.resolution.allow_once.json
```

### Test categories

#### 1. Boundary validation tests

Assert that malformed OpenClaw DTOs are rejected before canonicalization.

#### 2. Canonicalization tests

Fixture-driven assertions:

- raw OpenClaw input
- expected canonical event sequence
- expected provenance receipt metadata

#### 3. Append validation tests

Assert invariants:

- cannot resolve unknown approval
- cannot resume without positive approval
- cannot append non-versioned canonical event
- cannot append approval resolution for non-pending request

#### 4. Projection tests

Assert canonical event/state projects back into the exact OpenClaw-compatible
outbound shape.

#### 5. Replay tests

Replay canonical event streams and assert the derived governance state matches
expected approval and execution status.

## Concrete Conclusion

OpenClaw is comprehensive enough for its own plugin runtime purpose.

It is not comprehensive enough to serve as the canonical internal model for an
event-sourced governance substrate.

Final recommendation:

- keep OpenClaw as boundary DTO only
- adopt canonical governance events as authoritative truth
- append only canonical events
- store raw OpenClaw payloads separately as provenance evidence
- derive outbound OpenClaw responses as projections from canonical state
