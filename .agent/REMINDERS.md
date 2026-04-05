# Agent Reminders — cloistar

## CRITICAL: `governanceCallId` Identity Invariant

**This was violated TWICE during the refactor. Do not weaken it again.**

### The rule

> `governanceCallId` = `ctx.toolCallId` from OpenClaw.
> It must ALWAYS be present. If absent → **throw an error**.
> It must NEVER be: fabricated, defaulted, set to `undefined`, set to `null`, inferred, or merged with any other ID.

### How it was violated

1. **First violation**: `governanceCallId: ctx.toolCallId ?? undefined` — silently swallowed the absent case as `undefined` instead of throwing. The comment even said "this is semantically correct" — it is not.
2. **Second violation**: `governanceCallId: expedition.string().modes(["internal", "wire", "debug"]).optional()` — marking it `.optional()` in the type system contradicts the enforcement rule, and sending it on wire caused a 422 from the bridge anyway.

### Correct implementation

```ts
// In normalizeBeforeToolHook / normalizeAfterToolHook:
if (!ctx.toolCallId) {
  throw new Error(
    `[kogwistar-governance] governanceCallId cannot be established: ctx.toolCallId is absent.`
  );
}
return { governanceCallId: ctx.toolCallId, ... };
```

```ts
// In governance-schema.ts:
governanceCallId: expedition.string().modes(["internal", "debug"]),
// NOT .optional() — required at type level too.
// NOT on wire — the bridge rejects it (additionalProperties: false).
// IS on wire in ApprovalResolutionSchema — bridge needs it for correlation.
```

### The ID taxonomy (never merge these)

| ID | Owner | Lives on wire? | Purpose |
|---|---|---|---|
| `governanceCallId` | Plugin (= `ctx.toolCallId`) | ❌ before/after, ✅ resolution | Per-attempt plugin identity |
| `gatewayApprovalId` | Bridge (`requireApproval.approvalId`) | ✅ | Bridge-side approval handle |
| `localObservationId` | Plugin (process-local counter) | ❌ | Debug log correlation only |

---

## `plugin-kg` Has Tests

`plugin-kg/test/llm-safe.test.js` exists. If `tsc: not found` appears, run `npm install` in `plugin-kg/` first — typescript is in devDependencies but may not be installed.

---

## Wire Mode Rule

> The bridge uses `additionalProperties: false`. Any field not in the bridge schema will cause a **422 extra_forbidden**.
> Always verify the wire projection matches the bridge endpoint schema before adding fields to `.modes(["wire"])`.
