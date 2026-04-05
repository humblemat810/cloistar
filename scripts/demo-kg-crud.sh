#!/bin/bash
# demo-kg-crud.sh - Demo Kogwistar KG CRUD via OpenClaw CLI

# Exit on error
set -e

# Configuration
export BRIDGE_URL="http://127.0.0.1:8799"
export KOGWISTAR_BRIDGE_URL="http://127.0.0.1:8799"
OPENCLAW_CLI="node /home/azureuser/cloistar/openclaw/openclaw.mjs"

echo "=== Kogwistar KG CRUD Demo ==="

# 1. Create Nodes
echo -e "\n1. Creating Nodes..."
NODE1_JSON=$($OPENCLAW_CLI kg node create --label "OpenClaw" --type "software" --summary "An open-source agent platform")
NODE1_ID=$(echo "$NODE1_JSON" | grep -oP '"id":\s*"\K[^"]+' | tail -n 1)
echo "Created Node 1 (OpenClaw): $NODE1_ID"

NODE2_JSON=$($OPENCLAW_CLI kg node create --label "Kogwistar" --type "software" --summary "A knowledge graph engine")
NODE2_ID=$(echo "$NODE2_JSON" | grep -oP '"id":\s*"\K[^"]+' | tail -n 1)
echo "Created Node 2 (Kogwistar): $NODE2_ID"

# 2. Create Edge
echo -e "\n2. Creating Edge..."
EDGE_JSON=$($OPENCLAW_CLI kg edge create --relation "powers" --source-ids "$NODE2_ID" --target-ids "$NODE1_ID" --label "integration")
EDGE_ID=$(echo "$EDGE_JSON" | grep -oP '"id":\s*"\K[^"]+' | tail -n 1)
echo "Created Edge (Kogwistar powers OpenClaw): $EDGE_ID"

# 3. Query KG
echo -e "\n3. Querying KG for 'open-source'..."
$OPENCLAW_CLI kg query "open-source" --limit 5

# 4. Get Node Details
echo -e "\n4. Getting Node Details for $NODE1_ID..."
$OPENCLAW_CLI kg node get --ids "$NODE1_ID"

# 5. Update Node (Redirect)
echo -e "\n5. Updating Node (Redirecting to a new version)..."
NODE1_NEW_JSON=$($OPENCLAW_CLI kg node create --label "OpenClaw v2" --type "software" --summary "Enhanced agent platform")
NODE1_NEW_ID=$(echo "$NODE1_NEW_JSON" | grep -oP '"id":\s*"\K[^"]+' | tail -n 1)
echo "Created New Node: $NODE1_NEW_ID"

$OPENCLAW_CLI kg node update "$NODE1_ID" "$NODE1_NEW_ID"
echo "Redirected $NODE1_ID -> $NODE1_NEW_ID"

# 6. Delete Node (Tombstone)
echo -e "\n6. Deleting New Node (Tombstone)..."
$OPENCLAW_CLI kg node delete "$NODE1_NEW_ID"
echo "Tombstoned $NODE1_NEW_ID"

# 7. Final Verification
echo -e "\n7. Final Query (Verify tombstones are hidden by default)..."
$OPENCLAW_CLI kg node get --ids "$NODE1_NEW_ID" --resolve-mode active_only

echo -e "\n=== Demo Completed Successfully ==="
