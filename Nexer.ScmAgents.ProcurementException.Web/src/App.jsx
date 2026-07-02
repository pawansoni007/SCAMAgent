import { useEffect, useState } from "react";
import { api } from "./api.js";
import ChatPanel from "./components/ChatPanel.jsx";
import EventForm from "./components/EventForm.jsx";
import RecommendationCard from "./components/RecommendationCard.jsx";
import ValidationPanel from "./components/ValidationPanel.jsx";
import HistoryPage from "./pages/HistoryPage";
import InboxPage from "./pages/InboxPage";
import ExceptionDetailPage from "./pages/ExceptionDetailPage";
import ConversationSidebar from "./components/ConversationSidebar.jsx";

export default function App() {
  const [tab, setTab] = useState("chat");
  const [refData, setRefData] = useState(null);
  const [apiUp, setApiUp] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [result, setResult] = useState(null);
  const [decisions, setDecisions] = useState({});
  const [selectedInboxException, setSelectedInboxException] = useState(null);

  const [selectedConversationId,setSelectedConversationId] = useState(null);
  const [conversationRefreshToken,setConversationRefreshToken] = useState(0);



  useEffect(() => {
    api
      .health()
      .then(() => {
        setApiUp(true);
        return api.referenceData();
      })
      .then(setRefData)
      .catch(() => setApiUp(false));
  }, []);

  // Reset detail view when leaving inbox tab
  useEffect(() => {
    if (tab !== "inbox") {
      setSelectedInboxException(null);
    }
  }, [tab]);

  async function runAnalysis(event) {
    setLoading(true);
    setError(null);
    setResult(null);
    setDecisions({});
    try {
      const data = await api.analyze({ event });
      setResult(data);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }

  async function decide(rank, decision) {
  const requestId = result?.response?.request_id;
  if (!requestId) {
    console.warn("decide() called with no requestId — ignoring");
    return;
  }
  try {
    const res = await api.decide({ request_id: requestId, rank, decision });
    setDecisions((d) => ({ ...d, [rank]: { decision, next_step: res.next_step } }));
  } catch (e) {
    console.error("Approval decision failed:", e.message);
    // Don't retry — just show error to user
    setDecisions((d) => ({ ...d, [rank]: { decision, next_step: `Error: ${e.message}` } }));
  }
}

  const tenantId = refData?.tenants?.[0] || "nexer-demo";

  return (
    <div className="app">
      {/* ── Navbar ── */}
      <header className="d365-navbar">
        <div className="navbar-left">
          <button className="waffle" aria-label="App launcher">
            <span /><span /><span />
            <span /><span /><span />
            <span /><span /><span />
          </button>
          <span className="navbar-app">Dynamics 365</span>
          <span className="navbar-divider">|</span>
          <span className="navbar-module">SCM AI Agents</span>
        </div>
        <div className="navbar-right">
          <div className={`api-status ${apiUp ? "up" : apiUp === false ? "down" : ""}`}>
            <span className="dot" />
            {apiUp ? "Connected" : apiUp === false ? "API offline" : "checking…"}
          </div>
        </div>
      </header>

      {/* ── Command bar ── */}
      <div className="command-bar">
        <button className="cmd-item" onClick={() => window.location.reload()}>
          <span className="cmd-icon">⟳</span> Refresh
        </button>
        <span className="cmd-separator" />
        <span className="cmd-info">Procurement Agent</span>
      </div>

      {/* ── Page title + pivot nav ── */}
      <div className="page-title-area">
        <nav className="breadcrumb">Workspaces &nbsp;›&nbsp; Procurement</nav>
        <h1>
          {tab === "chat"
            ? "Procurement Agent"
            : tab === "inbox"
              ? selectedInboxException
                ? `Exception: ${selectedInboxException.item_id}`
                : "Exception Inbox"
              : tab === "history"
                ? "History & Audit"
                : "Procurement exception analysis"}
        </h1>
        <div className="pivot-bar">
          <button
            className={`pivot ${tab === "chat" ? "active" : ""}`}
            onClick={() => setTab("chat")}
          >
            Buyer chat
          </button>
          <button
            className={`pivot ${tab === "events" ? "active" : ""}`}
            onClick={() => setTab("events")}
          >
            Event simulation
          </button>
          <button
            className={`pivot ${tab === "inbox" ? "active" : ""}`}
            onClick={() => setTab("inbox")}
          >
            Exception inbox
          </button>
          <button
            className={`pivot ${tab === "history" ? "active" : ""}`}
            onClick={() => setTab("history")}
          >
            History &amp; audit
          </button>
        </div>
      </div>

      {/* ── Main content ── */}
      {tab === "chat" ? (
        <main className="chat-layout">
          <ConversationSidebar
            selectedConversationId={
              selectedConversationId
            }
            refreshToken={
              conversationRefreshToken
            }
            onSelectConversation={
              setSelectedConversationId
            }
            onNewConversation={() =>
              setSelectedConversationId(null)
            }
          />

          <ChatPanel
            tenantId={tenantId}
            conversationId={
              selectedConversationId
            }
            onConversationCreated={(
              conversationId
            ) => {
              setSelectedConversationId(
                conversationId
              );

              setConversationRefreshToken(
                (x) => x + 1
              );
            }}
          />
        </main>
      ) : tab === "inbox" ? (
        <main className="full-layout">
          {selectedInboxException ? (
            <ExceptionDetailPage
              exception={selectedInboxException}
              onBack={() => setSelectedInboxException(null)}
            />
          ) : (
            <InboxPage onSelectException={setSelectedInboxException} />
          )}
        </main>
      ) : tab === "history" ? (
        <main className="full-layout">
          <HistoryPage />
        </main>
      ) : (
        <main className="layout">
          <aside className="sidebar">
            <h2>PROC-01 Event Simulation</h2>
            <p className="hint">
              Simulates an overdue purchase order event arriving from D365 F&amp;O
              for inventory coverage risk prioritization.
            </p>
            {refData ? (
              <EventForm refData={refData} onSubmit={runAnalysis} loading={loading} />
            ) : (
              <div className="skeleton">Loading reference data…</div>
            )}
          </aside>

          <section className="content">
            {loading && (
              <div className="loading-panel">
                <div className="spinner" />
                <h3>Agents reasoning…</h3>
                <p>
                  Orchestrator → Procurement Exception Agent → tools (inventory, suppliers,
                  forecast, policies) → rules engine → validation
                </p>
              </div>
            )}

            {error && <div className="error-panel">⚠ {error}</div>}

            {!loading && !error && !result && (
              <div className="empty-panel">
                <h3>No analysis yet</h3>
                <p>Submit a PROC-01 overdue PO event to get Top 3 buyer recommendations.</p>
              </div>
            )}

            {result && (
              <>
                <div className="summary-card">
                  <div className="summary-head">
                    <h2>Analysis Summary</h2>
                    <span className={`risk-badge risk-${result.response.overall_risk}`}>
                      {result.response.overall_risk.toUpperCase()} RISK
                    </span>
                  </div>
                  <p>{result.response.summary}</p>
                  <div className="meta-row">
                    <span>Request: {result.response.request_id}</span>
                    <span>Agent: {result.response.agent_id} v{result.response.agent_version}</span>
                    <span>Item: {result.response.item_id}</span>
                    <span>Event: {result.response.event_type}</span>
                  </div>
                </div>

                <ValidationPanel validation={result.validation} />

                <h2 className="rec-title">
                  Top {result.response.recommendations.length} Recommendations
                  <span className="approval-note">human approval required before any ERP action</span>
                </h2>
                <div className="rec-grid">
                  {result.response.recommendations.map((rec) => (
                    <RecommendationCard
                      key={rec.rank}
                      rec={rec}
                      decision={decisions[rec.rank]}
                      onDecide={decide}
                    />
                  ))}
                </div>
              </>
            )}
          </section>
        </main>
      )}
    </div>
  );
}