# Plugin Development Guide

## Structure

kogwistar-openclaw-plugin/
  package.json
  openclaw.plugin.json
  src/hooks/

---

## Core Hook

before_tool_call:
- send payload to kogwistar
- receive decision

---

## Decision Types
- allow
- block
- requireApproval

---

## Example Flow

OpenClaw → Hook → Kogwistar → Decision → OpenClaw

---

## Best Practice
- keep plugin thin
- push logic to kogwistar
- avoid embedding governance logic inside OpenClaw
