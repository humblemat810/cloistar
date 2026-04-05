/**
 * @deprecated
 *
 * This file has been replaced by governance-client.ts (governance operations)
 * and plugin-kg/src/kogwistar-client.ts (KG operations).
 *
 * The mixing of governance and KG operations in one client violated the
 * boundary-of-responsibility principle. See governance-client.ts for the
 * correctly scoped governance client.
 *
 * All internal imports in this package now point to governance-client.ts.
 * This file is kept temporarily during transition to avoid breaking any
 * tooling that scans src/. It will be removed in the next cleanup pass.
 */
export { GovernanceClient } from "./governance-client.js";
