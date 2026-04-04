import { mkdir, appendFile } from "node:fs/promises";
import path from "node:path";
import { definePluginEntry } from "openclaw/plugin-sdk/plugin-entry";

const TRACE_FILE_ENV = "DEMO_APPROVAL_TRACE_FILE";
const DEFAULT_COMPONENT = "openclaw";
const EVENT_KIND = "openclaw_demo_trace";
const PREVIEW_LIMIT = 320;
const TOOL_LIKE_TEXT_RE = /^[a-z][a-z0-9_-]*\s*:/i;

let traceDirReady: Promise<void> | null = null;
const runState = new Map<string, RunTraceState>();

type RunTraceState = {
  sawToolBefore: boolean;
  sawToolAfter: boolean;
  toolNames: string[];
  lastAssistantTexts: string[];
};

function getTracePath(): string | null {
  const value = process.env[TRACE_FILE_ENV]?.trim();
  return value ? value : null;
}

function previewText(value: unknown, limit = PREVIEW_LIMIT): string | undefined {
  if (typeof value !== "string") {
    if (value == null) {
      return undefined;
    }
    try {
      return truncate(JSON.stringify(sanitize(value)));
    } catch {
      return truncate(String(value));
    }
  }
  return truncate(value, limit);
}

function truncate(value: string, limit = PREVIEW_LIMIT): string {
  if (value.length <= limit) {
    return value;
  }
  return `${value.slice(0, Math.max(0, limit - 1))}…`;
}

function sanitize(value: unknown, depth = 0, seen = new WeakSet<object>()): unknown {
  if (value === null || value === undefined) {
    return value;
  }
  if (typeof value === "string") {
    return truncate(value);
  }
  if (typeof value === "number" || typeof value === "boolean") {
    return value;
  }
  if (typeof value === "bigint") {
    return value.toString();
  }
  if (typeof value === "symbol") {
    return value.toString();
  }
  if (typeof value === "function") {
    return "[Function]";
  }
  if (Array.isArray(value)) {
    if (depth >= 2) {
      return `[Array(${value.length})]`;
    }
    const slice = value.slice(0, 5).map((item) => sanitize(item, depth + 1, seen));
    if (value.length > 5) {
      slice.push(`...(+${value.length - 5} more)`);
    }
    return slice;
  }
  if (typeof value === "object") {
    if (seen.has(value)) {
      return "[Circular]";
    }
    seen.add(value);
    if (depth >= 2) {
      return "[Object]";
    }
    const entries = Object.entries(value as Record<string, unknown>).slice(0, 10);
    const out: Record<string, unknown> = {};
    for (const [key, item] of entries) {
      out[key] = sanitize(item, depth + 1, seen);
    }
    const remaining = Object.keys(value as Record<string, unknown>).length - entries.length;
    if (remaining > 0) {
      out.__moreKeys = remaining;
    }
    return out;
  }
  return String(value);
}

function keysOf(value: unknown): string[] | undefined {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return undefined;
  }
  return Object.keys(value as Record<string, unknown>);
}

function stateKey(ctx: {
  runId?: string;
  sessionId?: string;
}): string | null {
  return ctx.runId ?? ctx.sessionId ?? null;
}

function getRunState(ctx: {
  runId?: string;
  sessionId?: string;
}): RunTraceState | null {
  const key = stateKey(ctx);
  if (!key) {
    return null;
  }
  const existing = runState.get(key);
  if (existing) {
    return existing;
  }
  const created: RunTraceState = {
    sawToolBefore: false,
    sawToolAfter: false,
    toolNames: [],
    lastAssistantTexts: [],
  };
  runState.set(key, created);
  return created;
}

function clearRunState(ctx: {
  runId?: string;
  sessionId?: string;
}): void {
  const key = stateKey(ctx);
  if (!key) {
    return;
  }
  runState.delete(key);
}

async function ensureTraceDirectory(tracePath: string): Promise<void> {
  if (!traceDirReady) {
    traceDirReady = mkdir(path.dirname(tracePath), { recursive: true }).then(() => undefined);
  }
  await traceDirReady;
}

async function appendTrace(
  event: string,
  ctx: {
    runId?: string;
    sessionId?: string;
    sessionKey?: string;
    agentId?: string;
    channelId?: string;
  },
  extra: Record<string, unknown> = {},
): Promise<void> {
  const tracePath = getTracePath();
  if (!tracePath) {
    return;
  }
  try {
    await ensureTraceDirectory(tracePath);
    const record = {
      ts: new Date().toISOString(),
      kind: EVENT_KIND,
      component: DEFAULT_COMPONENT,
      event,
      ...ctx,
      ...extra,
    };
    await appendFile(tracePath, `${JSON.stringify(record)}\n`);
  } catch {
    // Demo trace should never break the agent run.
  }
}

export default definePluginEntry({
  id: "demo-trace",
  name: "Demo Trace",
  description: "Writes concise prompt, LLM, tool, and session traces for demo runs.",
  register(api) {
    api.on("before_model_resolve", async (event, ctx) => {
      await appendTrace(
        "model.resolve.before",
        ctx,
        {
          prompt: previewText(event.prompt),
        },
      );
    });

    api.on("before_prompt_build", async (event, ctx) => {
      await appendTrace("prompt.build.before", ctx, {
        prompt: previewText(event.prompt),
        messageCount: Array.isArray(event.messages) ? event.messages.length : undefined,
        messagesPreview: Array.isArray(event.messages)
          ? event.messages.slice(0, 2).map((message) => sanitize(message))
          : undefined,
      });
    });

    api.on("llm_input", async (event, ctx) => {
      getRunState(ctx);
      await appendTrace("llm.input", ctx, {
        provider: event.provider,
        model: event.model,
        prompt: previewText(event.prompt),
        systemPrompt: previewText(event.systemPrompt),
        historyCount: Array.isArray(event.historyMessages) ? event.historyMessages.length : undefined,
        imagesCount: event.imagesCount,
      });
    });

    api.on("llm_output", async (event, ctx) => {
      const state = getRunState(ctx);
      if (state) {
        state.lastAssistantTexts = Array.isArray(event.assistantTexts)
          ? event.assistantTexts.filter((text): text is string => typeof text === "string")
          : [];
      }
      await appendTrace("llm.output", ctx, {
        provider: event.provider,
        model: event.model,
        assistantTexts: Array.isArray(event.assistantTexts)
          ? event.assistantTexts.slice(0, 3).map((text) => previewText(text))
          : undefined,
        lastAssistant: event.lastAssistant ? previewText(event.lastAssistant) : undefined,
        usage: event.usage ? sanitize(event.usage) : undefined,
      });
    });

    api.on("message_received", async (event, ctx) => {
      await appendTrace("message.received", ctx, {
        from: event.from,
        content: previewText(event.content),
      });
    });

    api.on("message_sent", async (event, ctx) => {
      await appendTrace("message.sent", ctx, {
        to: event.to,
        success: event.success,
        error: previewText(event.error),
        content: previewText(event.content),
      });
    });

    api.on("before_tool_call", async (event, ctx) => {
      const state = getRunState(ctx);
      if (state) {
        state.sawToolBefore = true;
        if (!state.toolNames.includes(event.toolName)) {
          state.toolNames.push(event.toolName);
        }
      }
      await appendTrace("tool.before", ctx, {
        toolName: event.toolName,
        toolCallId: event.toolCallId,
        paramsKeys: keysOf(event.params),
        params: sanitize(event.params),
      });
    });

    api.on("after_tool_call", async (event, ctx) => {
      const state = getRunState(ctx);
      if (state) {
        state.sawToolAfter = true;
      }
      await appendTrace("tool.after", ctx, {
        toolName: event.toolName,
        toolCallId: event.toolCallId,
        durationMs: event.durationMs,
        result: event.result === undefined ? undefined : sanitize(event.result),
        error: previewText(event.error),
      });
    });

    api.on("agent_end", async (event, ctx) => {
      const state = getRunState(ctx);
      await appendTrace("agent.end", ctx, {
        success: event.success,
        durationMs: event.durationMs,
        error: previewText(event.error),
        messageCount: Array.isArray(event.messages) ? event.messages.length : undefined,
      });
      if (state && !state.sawToolBefore) {
        const toolLikeAssistantText = state.lastAssistantTexts.find((text) => TOOL_LIKE_TEXT_RE.test(text));
        await appendTrace(toolLikeAssistantText ? "tool.call.rendered_as_text" : "tool.call.not_used", ctx, {
          assistantTexts: state.lastAssistantTexts.map((text) => previewText(text)),
          hint: toolLikeAssistantText
            ? "Model produced tool-like plain text instead of a real tool call."
            : "No actual tool hook fired during the run.",
        });
      } else if (state && state.sawToolBefore && !state.sawToolAfter) {
        await appendTrace("tool.call.incomplete", ctx, {
          toolNames: state.toolNames,
          hint: "A tool hook started but no after_tool_call event was observed.",
        });
      }
      clearRunState(ctx);
    });

    api.on("session_start", async (event, ctx) => {
      await appendTrace("session.start", ctx, {
        resumedFrom: event.resumedFrom,
      });
    });

    api.on("session_end", async (event, ctx) => {
      await appendTrace("session.end", ctx, {
        messageCount: event.messageCount,
        durationMs: event.durationMs,
      });
    });
  },
});
