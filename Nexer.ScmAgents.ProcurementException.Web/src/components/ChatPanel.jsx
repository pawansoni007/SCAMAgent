import { useEffect, useRef, useState } from "react";
import { api } from "../api.js";

const STARTERS = [
  "Which purchase orders are currently overdue?",
  "Which overdue POs should I act on first?",
  "Prioritize overdue purchase orders by inventory coverage risk.",
  "For ITEM003, which overdue POs are most critical?",
];

const LOCAL_DEV = import.meta.env.DEV;
const SHOW_LOCAL_CALL_FLOW = false;

const CALL_FLOW_TEMPLATE = [
  {
    id: "browser",
    title: "Buyer Chat UI",
    detail: "Capture user message and tenant context",
  },
  {
    id: "api",
    title: "POST /api/chat",
    detail: "Send request through Vite proxy to local Functions host",
  },
  {
    id: "function",
    title: "Azure Function chat endpoint",
    detail: "Resolve tenant session and buyer chat agent",
  },
  {
    id: "agent",
    title: "Buyer Chat Agent",
    detail: "Run prompt package and choose procurement tools",
  },
  {
    id: "tools",
    title: "Procurement tools",
    detail: "Read inventory, POs, demand, supplier, policy, or D365 data",
  },
  {
    id: "response",
    title: "Agent response",
    detail: "Return answer and session id to the UI",
  },
];

function createInitialCallFlow() {
  return CALL_FLOW_TEMPLATE.map((step) => ({ ...step, status: "idle" }));
}

function setFlowStatus(flow, statusById) {
  return flow.map((step) => ({
    ...step,
    status: statusById[step.id] ?? step.status,
  }));
}

/* ---------- minimal markdown rendering (bold, code, lists, tables) ---------- */

function renderInline(text, keyPrefix) {
  const parts = [];
  // split on **bold** and `code`
  const regex = /(\*\*[^*]+\*\*|`[^`]+`)/g;
  let last = 0;
  let m;
  let i = 0;
  while ((m = regex.exec(text)) !== null) {
    if (m.index > last) parts.push(text.slice(last, m.index));
    const token = m[0];
    if (token.startsWith("**")) {
      parts.push(<strong key={`${keyPrefix}-b${i++}`}>{token.slice(2, -2)}</strong>);
    } else {
      parts.push(<code key={`${keyPrefix}-c${i++}`}>{token.slice(1, -1)}</code>);
    }
    last = m.index + token.length;
  }
  if (last < text.length) parts.push(text.slice(last));
  return parts;
}

function renderMarkdown(text) {
  const lines = text.split(/\r?\n/);
  const blocks = [];
  let i = 0;
  let key = 0;

  while (i < lines.length) {
    const line = lines[i];

    if (!line.trim()) {
      i++;
      continue;
    }

    // table block
    if (line.trim().startsWith("|") && line.trim().endsWith("|")) {
      const tableLines = [];
      while (i < lines.length && lines[i].trim().startsWith("|")) {
        tableLines.push(lines[i].trim());
        i++;
      }
      const rows = tableLines
        .filter((l) => !/^\|[\s\-:|]+\|$/.test(l)) // drop separator row
        .map((l) => l.slice(1, -1).split("|").map((c) => c.trim()));
      if (rows.length > 0) {
        blocks.push(
          <table className="chat-table" key={`t${key++}`}>
            <thead>
              <tr>
                {rows[0].map((c, ci) => (
                  <th key={ci}>{renderInline(c, `th${ci}`)}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.slice(1).map((r, ri) => (
                <tr key={ri}>
                  {r.map((c, ci) => (
                    <td key={ci}>{renderInline(c, `td${ri}-${ci}`)}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        );
      }
      continue;
    }

    // list block (bullets or numbered)
    if (/^\s*([-*]|\d+\.)\s+/.test(line)) {
      const items = [];
      const ordered = /^\s*\d+\.\s+/.test(line);
      while (i < lines.length && /^\s*([-*]|\d+\.)\s+/.test(lines[i])) {
        items.push(lines[i].replace(/^\s*([-*]|\d+\.)\s+/, ""));
        i++;
      }
      const ListTag = ordered ? "ol" : "ul";
      blocks.push(
        <ListTag className="chat-list" key={`l${key++}`}>
          {items.map((item, ii) => (
            <li key={ii}>{renderInline(item, `li${ii}`)}</li>
          ))}
        </ListTag>
      );
      continue;
    }

    // heading
    const heading = line.match(/^(#{1,4})\s+(.*)$/);
    if (heading) {
      blocks.push(
        <p className="chat-heading" key={`h${key++}`}>
          {renderInline(heading[2], `h${key}`)}
        </p>
      );
      i++;
      continue;
    }

    // paragraph (merge consecutive plain lines)
    const para = [];
    while (
      i < lines.length &&
      lines[i].trim() &&
      !lines[i].trim().startsWith("|") &&
      !/^\s*([-*]|\d+\.)\s+/.test(lines[i]) &&
      !/^#{1,4}\s+/.test(lines[i])
    ) {
      para.push(lines[i]);
      i++;
    }
    blocks.push(
      <p key={`p${key++}`}>{renderInline(para.join(" "), `p${key}`)}</p>
    );
  }

  return blocks;
}

/* ---------- chat panel ---------- */

export default function ChatPanel({ tenantId, conversationId, onConversationCreated, }) {
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  // const [activeConversationId, setActiveConversationId] = useState(null);
  const [busy, setBusy] = useState(false);
  const [callFlow, setCallFlow] = useState(createInitialCallFlow);
  const [lastCall, setLastCall] = useState(null);
  const scrollRef = useRef(null);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [messages, busy]);

  // useEffect(() => {
  //   setActiveConversationId(
  //     conversationId
  //   );
  // }, [conversationId]);


  useEffect(() => {
    if (!conversationId) {
      setMessages([]);
      return;
    }

    api
      .getConversation(
        conversationId
      )
      .then((conversation) => {
        const msgs =
          conversation.messages.map(
            (message) => ({
              role:
                message.role ===
                "assistant"
                  ? "agent"
                  : message.role,
              text:
                message.content,
            })
          );

        setMessages(msgs);
      });
  }, [conversationId]);

  async function send(text) {
    const message = (text ?? input).trim();
    if (!message || busy) return;
    setInput("");
    setMessages((m) => [...m, { role: "user", text: message }]);
    setBusy(true);
    const startedAt = Date.now();
    if (LOCAL_DEV) {
      setLastCall({
        message,
        tenantId,
        sessionId: conversationId ?? "new",
        status: "running",
        startedAt,
      });
      setCallFlow(
        setFlowStatus(createInitialCallFlow(), {
          browser: "done",
          api: "active",
          function: "pending",
          agent: "pending",
          tools: "pending",
          response: "pending",
        })
      );
    }
    try {
      if (LOCAL_DEV) {
        setCallFlow((flow) =>
          setFlowStatus(flow, {
            api: "done",
            function: "active",
            agent: "active",
            tools: "active",
            response: "pending",
          })
        );
      }
      const res = await api.chat({
        message,
        conversation_id: conversationId,
        tenant_id: tenantId,
        debug: LOCAL_DEV,
      });
      if (
        !conversationId &&
        onConversationCreated
      ) {
        onConversationCreated(
          res.conversation_id
        );
      }
      setMessages((m) => [...m, { role: "agent", text: res.reply }]);
      if (LOCAL_DEV) {
        const toolsCalled = res.debug?.tools_called ?? [];
        const methodCalls = res.debug?.method_calls ?? [];
        setLastCall((current) => ({
          ...current,
          sessionId: res.conversation_id,
          status: "completed",
          durationMs: Date.now() - startedAt,
          toolsCalled,
          methodCalls,
          promptPackage: res.debug?.prompt_package,
        }));
        setCallFlow((flow) =>
          setFlowStatus(flow, {
            function: "done",
            agent: "done",
            tools: toolsCalled.length > 0 ? "done" : "idle",
            response: "done",
          })
        );
      }
    } catch (e) {
      setMessages((m) => [...m, { role: "error", text: e.message }]);
      if (LOCAL_DEV) {
        setLastCall((current) => ({
          ...current,
          status: "failed",
          error: e.message,
          durationMs: Date.now() - startedAt,
        }));
        setCallFlow((flow) =>
          setFlowStatus(flow, {
            api: "error",
            function: "error",
            agent: "pending",
            tools: "pending",
            response: "error",
          })
        );
      }
    } finally {
      setBusy(false);
    }
  }

  function newConversation() {
    // setSessionId(null);
    // setActiveConversationId(null);
    setMessages([]);
    setInput("");
    if (LOCAL_DEV) {
      setCallFlow(createInitialCallFlow());
      setLastCall(null);
    }
  }

  return (
    <div className={`chat-shell ${LOCAL_DEV ? "chat-shell-localdev" : ""}`}>
      <div className="chat-panel">
        <div className="chat-header">
          <div>
            <h2>Procurement Agent</h2>
            <span className="chat-subtitle">
              Buyer assistant — inventory, suppliers, purchase orders, draft POs
            </span>
          </div>
          <button className="btn chat-new-btn" onClick={newConversation} disabled={busy}>
            New conversation
          </button>
        </div>

        <div className="chat-scroll" ref={scrollRef}>
          {messages.length === 0 && (
            <div className="chat-welcome">
              <h3>Hi, I'm your Procurement Agent</h3>
              <p>
                Ask me about overdue or blocked purchase orders, supplier performance, prices,
                lead times and inventory coverage. I can also prepare a draft PO — with your
                confirmation.
              </p>
              <div className="chat-starters">
                {STARTERS.map((s) => (
                  <button key={s} className="starter-chip" onClick={() => send(s)}>
                    {s}
                  </button>
                ))}
              </div>
              <p className="chat-disclaimer">
                AI-generated insights are marked as <strong>Assessment</strong>. ERP data is
                read-only; any purchase order is created as a draft requiring approval.
              </p>
            </div>
          )}

          {messages.map((m, idx) =>
            m.role === "error" ? (
              <div className="chat-error" key={idx}>
                ⚠ {m.text}
              </div>
            ) : (
              <div key={idx} className={`chat-row ${m.role}`}>
                {m.role === "agent" && <div className="chat-avatar agent">AI</div>}
                <div className={`chat-bubble ${m.role}`}>
                  {m.role === "agent" ? renderMarkdown(m.text) : m.text}
                </div>
              </div>
            )
          )}

          {busy && (
            <div className="chat-row agent">
              <div className="chat-avatar agent">AI</div>
              <div className="chat-bubble agent typing">
                <span className="typing-dot" />
                <span className="typing-dot" />
                <span className="typing-dot" />
              </div>
            </div>
          )}
        </div>

        <div className="chat-input-bar">
          <textarea
            rows={1}
            value={input}
            placeholder="Ask about items, suppliers, purchase orders…"
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                send();
              }
            }}
            disabled={busy}
          />
          <button className="chat-send-btn" onClick={() => send()} disabled={busy || !input.trim()}>
            Send
          </button>
        </div>
      </div>

      {LOCAL_DEV && SHOW_LOCAL_CALL_FLOW && (
        <aside className="local-call-flow" aria-label="Local development call flow">
          <div className="local-call-flow-head">
            <div>
              <h3>Call Flow</h3>
              <span>Local dev only</span>
            </div>
            <span className={`call-flow-state ${lastCall?.status ?? "idle"}`}>
              {lastCall?.status ?? "idle"}
            </span>
          </div>

          {lastCall && (
            <div className="call-flow-meta">
              <div>
                <span>Tenant</span>
                <strong>{lastCall.tenantId}</strong>
              </div>
              <div>
                <span>Session</span>
                <strong>{lastCall.sessionId}</strong>
              </div>
              {lastCall.durationMs != null && (
                <div>
                  <span>Duration</span>
                  <strong>{lastCall.durationMs} ms</strong>
                </div>
              )}
            </div>
          )}

          <ol className="call-flow-list">
            {callFlow.map((step) => (
              <li key={step.id} className={`call-flow-step ${step.status}`}>
                <span className="call-flow-dot" />
                <div>
                  <strong>{step.title}</strong>
                  <p>{step.detail}</p>
                </div>
              </li>
            ))}
          </ol>

          <div className="call-flow-section">
            <h4>Prompts</h4>
            {lastCall?.promptPackage ? (
              <>
                <div className="call-flow-kv">
                  <span>Agent</span>
                  <strong>{lastCall.promptPackage.agent_id}</strong>
                </div>
                <div className="call-flow-kv">
                  <span>Version</span>
                  <strong>{lastCall.promptPackage.package_version}</strong>
                </div>
                <div className="call-flow-kv">
                  <span>Model</span>
                  <strong>{lastCall.promptPackage.model}</strong>
                </div>
                <div className="call-flow-chip-list">
                  {(lastCall.promptPackage.prompt_types ?? []).map((promptType) => (
                    <span key={promptType} className="call-flow-chip">
                      {promptType}
                    </span>
                  ))}
                </div>
              </>
            ) : (
              <p className="call-flow-empty">No prompt metadata yet.</p>
            )}
          </div>

          <div className="call-flow-section">
            <h4>Tools Called</h4>
            {lastCall?.toolsCalled?.length > 0 ? (
              <ol className="call-flow-tools">
                {lastCall.toolsCalled.map((toolCall, index) => (
                  <li key={`${toolCall.name}-${index}`}>
                    <strong>{toolCall.name}</strong>
                    {toolCall.arguments && Object.keys(toolCall.arguments).length > 0 && (
                      <code>{JSON.stringify(toolCall.arguments)}</code>
                    )}
                  </li>
                ))}
              </ol>
            ) : (
              <p className="call-flow-empty">
                {lastCall ? "No tools were called." : "No request has run yet."}
              </p>
            )}
          </div>

          <div className="call-flow-section">
            <h4>Methods &amp; Entities</h4>
            {lastCall?.methodCalls?.length > 0 ? (
              <ol className="call-flow-tools">
                {lastCall.methodCalls.map((call, index) => (
                  <li key={`${call.kind}-${call.name}-${index}`}>
                    <span className="call-flow-kind">{call.kind}</span>
                    <strong>{call.name}</strong>
                    {call.entity && <em>Entity: {call.entity}</em>}
                    {call.arguments && Object.keys(call.arguments).length > 0 && (
                      <code>{JSON.stringify(call.arguments)}</code>
                    )}
                    {call.metadata && Object.keys(call.metadata).length > 0 && (
                      <code>{JSON.stringify(call.metadata)}</code>
                    )}
                  </li>
                ))}
              </ol>
            ) : (
              <p className="call-flow-empty">
                {lastCall ? "No service methods were traced." : "No request has run yet."}
              </p>
            )}
          </div>

          {lastCall?.error && <div className="call-flow-error">{lastCall.error}</div>}
        </aside>
      )}
    </div>
  );
}
