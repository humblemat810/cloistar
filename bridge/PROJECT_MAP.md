# Bridge Project Map

## Purpose

This folder holds the OpenClaw -> Kogwistar governance bridge.

Its job is to:

- validate OpenClaw-facing boundary payloads
- canonicalize them into Kogwistar-owned governance events
- append canonical events and approval state
- project governance decisions back into the OpenClaw-facing response shape

## Layout

### `app/`

Main application code for the bridge service.

### `app/main.py`

FastAPI entrypoint.

Responsibilities:

- expose HTTP endpoints
- call boundary validation models
- invoke canonicalization, policy, append, and projection layers
- keep endpoint behavior thin

### `app/policy.py`

Internal governance policy evaluation.

Responsibilities:

- inspect tool name and params
- return an internal `PolicyEvaluation`
- avoid returning OpenClaw-shaped DTOs directly

### `app/models.py`

Compatibility import layer.

Responsibilities:

- re-export public payload and response models
- keep older imports stable while the codebase moves to explicit submodules

### `app/store.py`

In-memory development store.

Responsibilities:

- record canonical governance events
- record approval state
- record raw integration receipts for provenance
- provide snapshot/debug views

## Submodules

### `app/domain/`

Kogwistar-owned internal domain types and append rules.

This is the canonical layer.

#### `app/domain/governance_models.py`

Canonical Pydantic models for:

- governance event envelope
- governance event data payloads
- policy evaluation
- approval lifecycle data
- integration receipt metadata

#### `app/domain/governance_append.py`

Authoritative append-path helpers.

Responsibilities:

- append canonical events to the store
- register approval requests
- validate and append approval resolution follow-up events

### `app/integrations/`

Boundary adapters for external systems.

This is where upstream compatibility logic should live.

#### `app/integrations/openclaw_dto.py`

Strict OpenClaw boundary DTOs and OpenClaw-facing decision models.

Responsibilities:

- validate ingress payload shape
- constrain allowed approval resolution values
- define the OpenClaw-facing response contract

#### `app/integrations/openclaw_mapper.py`

OpenClaw DTO -> canonical governance mapping.

Responsibilities:

- create provenance receipts
- canonicalize `before_tool_call`
- canonicalize `after_tool_call`
- canonicalize approval resolution payloads
- create follow-up canonical lifecycle events

### `app/projections/`

Outbound projections from canonical state or policy decisions.

#### `app/projections/openclaw_projection.py`

Canonical/internal decision -> OpenClaw-facing response shape.

Responsibilities:

- map internal allow/block/require-approval decisions
- keep OpenClaw projection rules out of policy and endpoint code

## Tests

### `tests/`

Bridge-focused automated tests.

Responsibilities:

- validate adapter behavior
- validate canonical event creation
- validate outbound projection behavior
- validate endpoint flows

### `tests/conftest.py`

Test bootstrap for import path setup.

### `tests/test_bridge_contract.py`

Current bridge contract coverage.

This file is being moved toward fixture-driven tests for:

- raw OpenClaw input
- canonical governance event output
- outbound OpenClaw projection output

## Guiding Rules

### Boundary rule

OpenClaw schema is an integration contract, not internal truth.

### Canonical rule

Only canonical validated governance events may enter the authoritative event log.

### Provenance rule

Raw OpenClaw payloads may be stored as receipts/evidence, but not as canonical domain truth.

### Projection rule

Outbound OpenClaw responses must be derived from canonical/internal state, not the other way around.

## Expected Evolution

As the bridge grows, new folders should follow the same split:

- `integrations/` for upstream adapters
- `domain/` for canonical models and invariants
- `projections/` for outbound consumer-specific views
- `tests/fixtures/` for raw-input / canonical-output / projection-output fixtures
