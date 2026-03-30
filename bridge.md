# Kogwistar Bridge Service

## Responsibilities
- receive events
- evaluate policy
- append oplog
- manage approvals

---

## API

POST /policy/before-tool-call  
POST /events/append  
POST /approval/respond  

---

## Event Types
- message_received
- tool_call_proposed
- tool_call_blocked
- tool_call_approved
- tool_call_executed

---

## Principle
Append-only log. No mutation.
