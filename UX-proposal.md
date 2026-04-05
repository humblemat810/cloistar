# UX Proposal

This document proposes the next operator-facing layer for the repo.

The current system already has the hard part:

- canonical governance events
- backbone steps
- semantic side events
- durable latest-state projections
- real approval suspend/resume

The main gap is not core semantics anymore. The gap is making those semantics
easy to inspect, query, trust, and operate.

## Product Direction

The future UX should make one thing obvious:

- this is not just an agent hook integration
- it is a canonical governance semantics layer for agent systems

That means the UX should expose:

- execution flow
- governance meaning
- operator-facing latest state

as separate but linked views.

## Main UX Principle

Do not flatten everything into one generic event log.

The UI should preserve the architectural separation already present in the
system:

- backbone = control flow
- semantic events = governance meaning
- projection = latest operator/debug state

If the UI collapses those into one stream, it will reintroduce the same
confusion the repo was explicitly designed to avoid.

## Proposed Surfaces

## 1. Governance Trace View

Purpose:

- show one governed tool call as an intelligible story

Core layout:

- left rail: latest state summary
- center: backbone timeline
- right rail: semantic events attached to the selected backbone step

Must show:

- tool name
- session id
- governance call id
- current status
- final disposition
- approval status when present
- completion status

Why this matters:

- this becomes the canonical “what happened?” view for one governed action

## 2. Session-Level Interaction View

Purpose:

- show how multiple governed tool calls relate inside one OpenClaw session

Model:

- one session graph
- multiple governed tool-call backbones
- links by session id, run id, tool call id, and turn relationships

Why this matters:

- the repo already models one backbone per governed tool call correctly
- the next usability step is helping operators inspect many such governed
  branches together without collapsing them into one chain

## 3. Approval Desk

Purpose:

- give operators a purpose-built approval workspace instead of forcing them to
  infer approval state from raw graph or logs

Should show:

- pending approvals
- approval source
- requested action
- timeout
- current bridge/gateway linkage ids
- human or LLM resolution path
- resolution rationale/summary when available

Nice future additions:

- batch review
- saved approval policies
- escalation routing
- replay into the corresponding governance trace

## 4. Graph Inspector

Purpose:

- expose raw graph truth for advanced debugging without forcing normal operators
  to read it first

Modes:

- semantic mode
- backbone mode
- raw node/edge mode

Important rule:

- default to semantic mode
- keep raw graph mode available, but not as the primary product surface

## 5. Projection Inspector

Purpose:

- explain the current latest-state view and where it came from

Should show:

- projection namespace
- projection key
- latest payload
- last authoritative seq
- last materialized seq
- source semantic nodes/events that contributed to the current state

Why this matters:

- projection correctness and graph correctness are different
- the UX should teach that instead of hiding it

## 6. Replay / Audit View

Purpose:

- show how a governance decision can be rebuilt from durable records

Should show:

- canonical event sequence
- receipt sequence
- backbone steps
- projection updates

This should feel like:

- “show me how the current truth was derived”

not:

- “dump every log line ever”

## Serious Brainstormed Future Ideas

## A. Split-screen “Semantics vs Projection”

Show:

- left: semantic graph trace
- right: latest-state projection

Benefit:

- teaches operators and developers the difference between durable truth and
  latest materialized state

This is one of the strongest conceptual ideas in the repo and should become a
visual feature.

## B. Trace Cards Instead Of Raw Nodes

Represent one governed tool call as a card with:

- proposed action
- risk classification
- decision
- approval path
- outcome

Expandable into:

- backbone
- semantic events
- raw graph nodes/edges

Benefit:

- makes the system legible to people who are not graph-engine experts

## C. “Why Was This Allowed / Denied?” Lens

Every result should have an operator-visible explanation surface:

- policy reason
- approval resolution
- runtime path taken
- attached semantic events

This can be derived from the existing event model rather than bolted on as a
free-text log field.

## D. Suspended-Run Recovery Workspace

Purpose:

- make suspend/resume operationally safe

Show:

- all currently suspended runs
- what they are waiting on
- whether bridge/gateway linkage is healthy
- whether approval subscription is alive
- whether resume is possible now

Benefit:

- this turns durable suspend/resume into a real operator capability instead of
  just an implementation detail

## E. Named View Presets

Examples:

- “Operator view”
- “Graph/debug view”
- “Approval desk”
- “Replay/audit view”

Benefit:

- the same durable semantics can serve very different users without one cluttered
  universal screen

## Practical Near-Term UX Milestones

1. Add a first-class governance trace page for one `governanceCallId`.
2. Add a pending approvals desk backed by the existing latest-state projection.
3. Add a projection inspector that shows projection payload plus seq metadata.
4. Add a session-level graph page that groups multiple governed tool-call
   backbones.
5. Add a replay/audit panel that reconstructs one run from canonical events and
   receipts.

## Non-Goals

- Do not replace the semantic model with a generic event feed UI.
- Do not make projection rows look like the only truth.
- Do not collapse multiple governed tool calls into one giant backbone.
- Do not make raw graph inspection the only usable operator experience.

## Short Positioning

The repo already has strong system semantics.

The future UX should make those semantics visible and usable without weakening
them.

That means:

- preserve backbone
- preserve semantic events
- preserve projection separation
- make them explorable by humans
