import { useEffect, useMemo, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";

const API = import.meta.env.VITE_API_URL || "http://localhost:8001";

function formatDate(value) {
  if (!value) return "Recently";
  try {
    return new Date(value).toLocaleDateString(undefined, {
      month: "short",
      day: "numeric",
      year: "numeric",
    });
  } catch {
    return "Recently";
  }
}

function getSessionId(session) {
  return session?.session_id || session?.id;
}

function getSessionUrl(session) {
  return session?.url || session?.root_url || session?.source_url || "";
}

function getSessionTitle(session) {
  return session?.title || session?.name || getSessionUrl(session) || "Untitled session";
}

function safeModules(studyPlan) {
  return Array.isArray(studyPlan?.modules) ? studyPlan.modules : [];
}

function normalizeMessage(message) {
  const role = message.role === "assistant" ? "ai" : message.role;
  return {
    role,
    content: message.content || "",
    citations: message.citations || message.citation || [],
    struggles: message.struggle_signals || message.struggles || {},
    typewrite: false,
  };
}

function createSseParser(onData) {
  let buffer = "";

  return function parseChunk(chunkText) {
    buffer += chunkText;
    const events = buffer.split("\n\n");
    buffer = events.pop() || "";

    for (const rawEvent of events) {
      const dataLine = rawEvent.split("\n").find((line) => line.startsWith("data: "));
      if (!dataLine) continue;

      try {
        onData(JSON.parse(dataLine.replace("data: ", "")));
      } catch (error) {
        console.error("Invalid SSE payload:", dataLine, error);
      }
    }
  };
}

async function readSseResponse(response, onData) {
  if (!response.body) throw new Error("Streaming response body not available");

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  const parse = createSseParser(onData);

  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    parse(decoder.decode(value, { stream: true }));
  }
}

function Pill({ children, variant = "neutral" }) {
  return <span className={`pill pill-${variant}`}>{children}</span>;
}

function SectionTitle({ children, action }) {
  return (
    <div className="section-title">
      <span>{children}</span>
      {action}
    </div>
  );
}

function MarkdownContent({ text }) {
  const components = {
    a: ({ href, children }) => (
      <a className="md-link" href={href} target="_blank" rel="noreferrer">
        {children}
      </a>
    ),
    p: ({ children }) => <p className="md-p">{children}</p>,
    ul: ({ children }) => <ul className="md-list">{children}</ul>,
    ol: ({ children }) => <ol className="md-list">{children}</ol>,
    li: ({ children }) => <li className="md-li">{children}</li>,
    strong: ({ children }) => <strong className="md-strong">{children}</strong>,
    h1: ({ children }) => <h1 className="md-h1">{children}</h1>,
    h2: ({ children }) => <h2 className="md-h2">{children}</h2>,
    h3: ({ children }) => <h3 className="md-h3">{children}</h3>,
    code: ({ children }) => <code className="inline-code">{children}</code>,
    pre: ({ children }) => <pre className="code-block">{children}</pre>,
    blockquote: ({ children }) => <blockquote className="blockquote">{children}</blockquote>,
  };

  return <ReactMarkdown components={components}>{text || ""}</ReactMarkdown>;
}

function TypeWriter({ text, active }) {
  const [shown, setShown] = useState(active ? "" : text || "");
  const [done, setDone] = useState(!active);
  const indexRef = useRef(0);

  useEffect(() => {
    let interval;
    const start = setTimeout(() => {
      if (!active) {
        setShown(text || "");
        setDone(true);
        return;
      }

      setShown("");
      setDone(false);
      indexRef.current = 0;

      interval = setInterval(() => {
        if (indexRef.current < (text || "").length) {
          setShown((text || "").slice(0, indexRef.current + 1));
          indexRef.current += 1;
        } else {
          clearInterval(interval);
          setDone(true);
        }
      }, 5);
    }, 0);

    return () => {
      clearTimeout(start);
      clearInterval(interval);
    };
  }, [text, active]);

  if (!done) {
    return (
      <span className="typewriter">
        {shown}
        <span className="caret">▋</span>
      </span>
    );
  }

  return <MarkdownContent text={text} />;
}

function EmptyState() {
  return (
    <div className="empty-state">
      <div className="empty-logo">V</div>
      <h1>Learn technical docs with memory.</h1>
      <p>
        Paste a documentation URL, generate a structured learning plan, ask grounded questions,
        and save review notes across sessions.
      </p>
      <div className="empty-pills">
        <Pill variant="accent">Persistent sessions</Pill>
        <Pill variant="success">Citations</Pill>
        <Pill variant="warning">Struggle memory</Pill>
      </div>
    </div>
  );
}

function LiveProgressCard({ progress }) {
  if (!progress) return null;

  const current = Number(progress.current || 0);
  const total = Number(progress.total || 0);
  const percent = total > 0 ? Math.min(100, Math.round((current / total) * 100)) : 0;

  return (
    <div className="live-progress">
      <div className="live-progress-head">
        <div className="live-progress-copy">
          <div className="live-title">{progress.label || "Processing documentation"}</div>
          <div className="live-subtitle">{progress.module || "Preparing module"}</div>
        </div>
        <div className="live-count">{total > 0 ? `${current}/${total}` : "Working"}</div>
      </div>

      <div className="progress-track">
        <div className="progress-fill" style={{ width: `${percent}%` }} />
      </div>

      <div className="live-footer">
        <span>{percent}% complete</span>
        <span title={progress.page || ""}>Current: {progress.page || "Preparing..."}</span>
      </div>
    </div>
  );
}

function AgentActivity({ events }) {
  return (
    <div className="card">
      <SectionTitle>Agent activity</SectionTitle>
      {events.length === 0 ? (
        <p className="card-empty">Setup, retrieval, reranking, and memory updates will appear here.</p>
      ) : (
        <div className="activity-list">
          {events.slice(-8).map((event, index) => (
            <div className="activity-item" key={`${event.message}-${index}`}>
              <div className={`activity-dot activity-${event.type || "status"}`}>
                {event.type === "error" ? "!" : "✓"}
              </div>
              <div className="activity-body">
                <div className="activity-message">{event.message}</div>
                {event.meta && <div className="activity-meta">{event.meta}</div>}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function SourcesPanel({ sources }) {
  const uniqueSources = [...new Set(sources || [])].slice(0, 8);

  return (
    <div className="card">
      <SectionTitle>Sources</SectionTitle>
      {uniqueSources.length === 0 ? (
        <p className="card-empty">Citations from retrieved documentation will appear here.</p>
      ) : (
        <div className="source-list">
          {uniqueSources.map((source, index) => {
            const label = source.split("#")[1] || source.split("/").filter(Boolean).pop() || "Source";
            return (
              <a className="source-item" href={source} target="_blank" rel="noreferrer" key={source}>
                <span>Source {index + 1}</span>
                <strong>{label}</strong>
              </a>
            );
          })}
        </div>
      )}
    </div>
  );
}

function VaultPanel({ vaultFiles, onOpen }) {
  return (
    <div className="card">
      <SectionTitle>Vault memory</SectionTitle>
      {vaultFiles.length === 0 ? (
        <p className="card-empty">
          Notes, struggle summaries, and review schedules will appear after ending a session.
        </p>
      ) : (
        <div className="vault-list">
          {vaultFiles.slice(0, 6).map((file) => (
            <button className="vault-item" type="button" onClick={() => onOpen(file)} key={file}>
              <strong>{file.replace(".md", "")}</strong>
              <span>Markdown note</span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

export default function App() {
  const [dark, setDark] = useState(false);
  const [mobileSidebarOpen, setMobileSidebarOpen] = useState(false);
  const [detailsOpen, setDetailsOpen] = useState(false);

  const [url, setUrl] = useState("");
  const [sessionId, setSessionId] = useState(null);
  const [studyPlan, setStudyPlan] = useState(null);
  const [currentModule, setCurrentModule] = useState(1);

  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [history, setHistory] = useState([]);
  const [histIdx, setHistIdx] = useState(-1);

  const [loading, setLoading] = useState(false);
  const [settingUp, setSettingUp] = useState(false);
  const [notesWritten, setNotesWritten] = useState(false);

  const [pastSessions, setPastSessions] = useState([]);
  const [vaultFiles, setVaultFiles] = useState([]);
  const [progressEvents, setProgressEvents] = useState([]);
  const [liveProgress, setLiveProgress] = useState(null);

  const bottomRef = useRef(null);
  const inputRef = useRef(null);

  const modules = safeModules(studyPlan);
  const activeModule = modules.find((module) => module.module_number === currentModule);

  const latestSources =
    [...messages].reverse().find((message) => message.role === "ai" && message.citations?.length)
      ?.citations || [];

  const themeName = useMemo(() => (dark ? "dark" : "light"), [dark]);

  useEffect(() => {
    document.documentElement.dataset.theme = themeName;
    document.body.style.background = dark ? "#0B1120" : "#F8FAFC";
  }, [themeName, dark]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, liveProgress, loading]);

  const addProgress = (message, type = "status", meta = null) => {
    setProgressEvents((previous) => [
      ...previous,
      { message, type, meta, createdAt: new Date().toISOString() },
    ]);
  };

  const refreshSessions = async () => {
    try {
      const response = await fetch(`${API}/sessions`);
      const data = await response.json();
      setPastSessions(data.sessions || []);
    } catch (error) {
      console.error("Failed to load sessions", error);
    }
  };

  const fetchVault = async () => {
    try {
      const response = await fetch(`${API}/vault`);
      const data = await response.json();
      setVaultFiles(data.files || []);
    } catch (error) {
      console.error("Failed to load vault notes", error);
    }
  };

  useEffect(() => {
    const start = setTimeout(() => {
      refreshSessions();
      fetchVault();
    }, 0);
    return () => clearTimeout(start);
  }, []);

  const applyPersistedMessages = (persistedMessages) => {
    if (!Array.isArray(persistedMessages) || persistedMessages.length === 0) return;
    setMessages(persistedMessages.map(normalizeMessage));
  };

  const handleSetupPayload = (data) => {
    if (data.type === "progress") {
      setLiveProgress({
        label: "Chunking and indexing documentation",
        current: data.current,
        total: data.total,
        module: data.module,
        page: data.page,
      });
      return;
    }

    if (data.type === "status") {
      addProgress(data.message || "Working...", "status");
      return;
    }

    if (data.type === "done") {
      const plan = data.study_plan || {};
      const moduleCount = safeModules(plan).length;

      setSessionId(data.session_id);
      setStudyPlan(plan);
      setCurrentModule(1);
      setLiveProgress(null);
      setMessages([
        {
          role: "ai",
          content: `The documentation index is ready. I found **${moduleCount} learning modules** and prepared the session.\n\nChoose a module on the left, or ask your first question about the documentation.`,
          citations: [],
          struggles: {},
          typewrite: true,
        },
      ]);

      addProgress("Documentation index ready", "status");
      refreshSessions();
      setMobileSidebarOpen(false);
      return;
    }

    if (data.type === "error") {
      setLiveProgress(null);
      addProgress(data.message || "Setup failed", "error");
      setMessages([{ role: "system", content: data.message || "Setup failed. Try another URL." }]);
    }
  };

  const handleSetup = async () => {
    const trimmedUrl = url.trim();
    if (!trimmedUrl || settingUp) return;

    setSettingUp(true);
    setMessages([]);
    setProgressEvents([]);
    setLiveProgress(null);
    setNotesWritten(false);

    addProgress("Starting documentation indexing", "status", trimmedUrl);

    try {
      const response = await fetch(`${API}/setup`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url: trimmedUrl }),
      });

      if (!response.ok) throw new Error(`Setup failed with status ${response.status}`);

      const contentType = response.headers.get("content-type") || "";

      if (contentType.includes("application/json")) {
        const data = await response.json();
        const plan = data.study_plan || {};
        const moduleCount = safeModules(plan).length;

        setSessionId(data.session_id);
        setStudyPlan(plan);
        setCurrentModule(1);
        setMessages([
          {
            role: "ai",
            content: `The documentation index is ready. I found **${moduleCount} learning modules** and prepared the session.\n\nChoose a module on the left, or ask your first question about the documentation.`,
            citations: [],
            struggles: {},
            typewrite: true,
          },
        ]);
        addProgress("Documentation index ready", "status");
        refreshSessions();
        setMobileSidebarOpen(false);
      } else {
        await readSseResponse(response, handleSetupPayload);
      }
    } catch (error) {
      console.error(error);
      setLiveProgress(null);
      addProgress(error.message || "Setup failed", "error");
      setMessages([
        {
          role: "system",
          content: "I could not index this documentation source. Try a direct documentation URL.",
        },
      ]);
    } finally {
      setSettingUp(false);
    }
  };

  const handleResume = async (session) => {
    const id = getSessionId(session);
    if (!id) return;

    setUrl(getSessionUrl(session));
    setSettingUp(true);
    setMessages([]);
    setProgressEvents([]);
    setLiveProgress(null);
    setNotesWritten(false);

    addProgress(`Resuming ${getSessionTitle(session)}`, "status");

    try {
      const response = await fetch(`${API}/session/${id}/resume`, { method: "POST" });
      if (!response.ok) throw new Error(`Resume failed with status ${response.status}`);

      const contentType = response.headers.get("content-type") || "";

      if (contentType.includes("application/json")) {
        const data = await response.json();
        const plan = data.study_plan || {};
        const moduleCount = safeModules(plan).length;

        setSessionId(data.session_id || id);
        setStudyPlan(plan);
        setCurrentModule(1);

        if (Array.isArray(data.messages) && data.messages.length > 0) {
          applyPersistedMessages(data.messages);
        } else {
          setMessages([
            {
              role: "ai",
              content: `Resumed **${plan.title || getSessionTitle(session)}**. ${moduleCount} modules are ready.\n\nYou can continue learning from this documentation session.`,
              citations: [],
              struggles: {},
              typewrite: true,
            },
          ]);
        }

        addProgress("Session resumed from persisted index", "status");
        setMobileSidebarOpen(false);
      } else {
        await readSseResponse(response, (data) => {
          if (data.type === "progress") {
            setLiveProgress({
              label: "Rebuilding documentation index",
              current: data.current,
              total: data.total,
              module: data.module,
              page: data.page,
            });
            return;
          }

          if (data.type === "status") {
            addProgress(data.message || "Resuming session...", "status");
            return;
          }

          if (data.type === "done") {
            const plan = data.study_plan || {};
            const moduleCount = safeModules(plan).length;

            setLiveProgress(null);
            setSessionId(data.session_id || id);
            setStudyPlan(plan);
            setCurrentModule(1);
            setMessages([
              {
                role: "ai",
                content: `Resumed **${plan.title || getSessionTitle(session)}**. ${moduleCount} modules are ready.\n\nYou can continue learning from this documentation session.`,
                citations: [],
                struggles: {},
                typewrite: true,
              },
            ]);
            addProgress("Session resumed", "status");
            setMobileSidebarOpen(false);
            return;
          }

          if (data.type === "error") {
            setLiveProgress(null);
            addProgress(data.message || "Resume failed", "error");
          }
        });
      }
    } catch (error) {
      console.error(error);
      setLiveProgress(null);
      addProgress(error.message || "Resume failed", "error");
      setMessages([{ role: "system", content: "I could not resume this session. Try indexing again." }]);
    } finally {
      setSettingUp(false);
    }
  };

  const handleSend = async (override) => {
    const text = override || input.trim();
    if (!text || !sessionId || loading) return;

    setInput("");
    setHistory((previous) => [text, ...previous]);
    setHistIdx(-1);
    setMessages((previous) => [...previous, { role: "user", content: text }]);
    setLoading(true);

    addProgress("Loading session context", "status");
    addProgress("Retrieving relevant documentation chunks", "progress");

    try {
      const response = await fetch(`${API}/session/${sessionId}/message`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          message: text,
          current_module_number: currentModule,
        }),
      });

      if (!response.ok) throw new Error(`Request failed with status ${response.status}`);

      addProgress("Reranking retrieved context", "progress");
      const data = await response.json();
      addProgress("Generated citation-grounded answer", "status");

      setMessages((previous) => [
        ...previous,
        {
          role: "ai",
          content: data.answer || "",
          citations: data.citations || data.citation || [],
          struggles: data.struggle_signals || {},
          typewrite: true,
        },
      ]);

      if (data.struggle_signals && Object.keys(data.struggle_signals).length > 0) {
        addProgress("Detected struggle signal and updated review memory", "status");
      }

      if (data.notes_written) {
        setNotesWritten(true);
        addProgress("Wrote vault notes and spaced repetition schedule", "status");
        fetchVault();
      }
    } catch (error) {
      console.error(error);
      addProgress(error.message || "Message failed", "error");
      setMessages((previous) => [
        ...previous,
        { role: "system", content: "The request failed. Please try again." },
      ]);
    } finally {
      setLoading(false);
    }
  };

  const handleKeyDown = (event) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      handleSend();
    }

    if (event.key === "ArrowUp") {
      event.preventDefault();
      const next = Math.min(histIdx + 1, history.length - 1);
      setHistIdx(next);
      setInput(history[next] || "");
    }

    if (event.key === "ArrowDown") {
      event.preventDefault();
      const next = Math.max(histIdx - 1, -1);
      setHistIdx(next);
      setInput(next === -1 ? "" : history[next]);
    }
  };

  const priorityVariant = (priority) => {
    if (priority === "RED") return "danger";
    if (priority === "YELLOW") return "warning";
    return "success";
  };

  const css = `
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;500;600&display=swap');

    :root {
      --bg: #F8FAFC;
      --sidebar: #FFFFFF;
      --surface: #FFFFFF;
      --surface-soft: #F1F5F9;
      --text: #0F172A;
      --muted: #64748B;
      --faint: #94A3B8;
      --border: #E2E8F0;
      --border-soft: #EEF2F7;
      --accent: #4F46E5;
      --accent-soft: #EEF2FF;
      --success: #059669;
      --success-soft: #ECFDF5;
      --warning: #D97706;
      --warning-soft: #FFFBEB;
      --danger: #DC2626;
      --danger-soft: #FEF2F2;
      --shadow: 0 8px 30px rgba(15, 23, 42, 0.06);
    }

    [data-theme="dark"] {
      --bg: #0B1120;
      --sidebar: #0F172A;
      --surface: #111827;
      --surface-soft: #1E293B;
      --text: #E5E7EB;
      --muted: #94A3B8;
      --faint: #64748B;
      --border: #1F2937;
      --border-soft: #172033;
      --accent: #818CF8;
      --accent-soft: rgba(129, 140, 248, 0.16);
      --success: #34D399;
      --success-soft: rgba(52, 211, 153, 0.14);
      --warning: #FBBF24;
      --warning-soft: rgba(251, 191, 36, 0.14);
      --danger: #F87171;
      --danger-soft: rgba(248, 113, 113, 0.14);
      --shadow: none;
    }

    * {
      box-sizing: border-box;
    }

    html,
    body,
    #root {
      width: 100%;
      height: 100%;
      margin: 0;
      overflow: hidden;
    }

    body {
      font-family: Inter, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      background: var(--bg);
      color: var(--text);
    }

    button,
    input {
      font-family: inherit;
    }

    button {
      -webkit-tap-highlight-color: transparent;
    }

    input::placeholder {
      color: var(--faint);
      opacity: 1;
    }

    ::-webkit-scrollbar {
      width: 8px;
      height: 8px;
    }

    ::-webkit-scrollbar-thumb {
      background: var(--border);
      border-radius: 999px;
    }

    .app-shell {
      width: 100%;
      height: 100%;
      display: grid;
      grid-template-columns: minmax(260px, 300px) minmax(0, 1fr) minmax(280px, 320px);
      background: var(--bg);
      color: var(--text);
      overflow: hidden;
    }

    .mobile-bar {
      display: none;
    }

    .sidebar {
      min-width: 0;
      overflow-y: auto;
      background: var(--sidebar);
      border-right: 1px solid var(--border);
      padding: 18px;
      display: flex;
      flex-direction: column;
      gap: 16px;
      z-index: 40;
    }

    .main {
      min-width: 0;
      overflow: hidden;
      display: flex;
      flex-direction: column;
      height: 100%;
    }

    .details {
      min-width: 0;
      overflow-y: auto;
      background: var(--bg);
      border-left: 1px solid var(--border);
      padding: 18px;
      display: flex;
      flex-direction: column;
      gap: 14px;
    }

    .brand {
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 12px;
    }

    .brand-left {
      display: flex;
      align-items: center;
      gap: 11px;
      min-width: 0;
    }

    .logo {
      width: 38px;
      height: 38px;
      border-radius: 12px;
      background: var(--accent);
      color: white;
      display: grid;
      place-items: center;
      font-size: 18px;
      font-weight: 850;
      flex: 0 0 auto;
    }

    .brand-title {
      font-size: 18px;
      font-weight: 820;
      letter-spacing: -0.02em;
    }

    .brand-subtitle {
      color: var(--muted);
      font-size: 12px;
      margin-top: 2px;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }

    .theme-button,
    .icon-button {
      border: 1px solid var(--border);
      background: var(--surface);
      color: var(--muted);
      border-radius: 10px;
      padding: 8px 10px;
      cursor: pointer;
      font-size: 12px;
      font-weight: 650;
      white-space: nowrap;
    }

    .panel,
    .card {
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: 18px;
      box-shadow: var(--shadow);
    }

    .panel {
      padding: 14px;
    }

    .card {
      padding: 16px;
    }

    .section-title {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 10px;
      color: var(--muted);
      font-size: 12px;
      font-weight: 760;
      text-transform: uppercase;
      letter-spacing: 0.08em;
      margin-bottom: 10px;
    }

    .url-input {
      width: 100%;
      background: var(--surface-soft);
      border: 1px solid var(--border);
      border-radius: 12px;
      padding: 12px;
      color: var(--text);
      font-size: 14px;
      outline: none;
      margin-bottom: 10px;
    }

    .url-input:focus {
      border-color: var(--accent);
      box-shadow: 0 0 0 3px var(--accent-soft);
    }

    .primary-button {
      width: 100%;
      border: 0;
      border-radius: 12px;
      padding: 12px 14px;
      background: var(--accent);
      color: white;
      font-size: 14px;
      font-weight: 760;
      cursor: pointer;
    }

    .primary-button:disabled {
      background: var(--surface-soft);
      color: var(--muted);
      cursor: not-allowed;
    }

    .danger-button {
      width: 100%;
      margin-top: 12px;
      border: 1px solid var(--danger-soft);
      border-radius: 12px;
      padding: 11px 14px;
      background: var(--danger-soft);
      color: var(--danger);
      font-size: 14px;
      font-weight: 720;
      cursor: pointer;
    }

    .session-list,
    .module-list,
    .activity-list,
    .source-list,
    .vault-list {
      display: flex;
      flex-direction: column;
      gap: 8px;
    }

    .session-item,
    .module-item {
      width: 100%;
      min-width: 0;
      text-align: left;
      border: 1px solid var(--border);
      border-radius: 14px;
      background: var(--surface);
      color: var(--text);
      padding: 11px 12px;
      cursor: pointer;
    }

    .session-item:hover,
    .module-item:hover,
    .module-item-active {
      border-color: var(--accent);
      background: var(--accent-soft);
    }

    .session-title,
    .module-title {
      font-size: 13px;
      font-weight: 720;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
      min-width: 0;
    }

    .session-meta,
    .module-meta {
      color: var(--muted);
      font-size: 11px;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
      margin-top: 4px;
    }

    .module-top {
      display: flex;
      align-items: center;
      gap: 8px;
      min-width: 0;
    }

    .module-num {
      font-family: "JetBrains Mono", monospace;
      color: var(--accent);
      font-weight: 760;
      font-size: 12px;
      flex: 0 0 auto;
    }

    .pill {
      display: inline-flex;
      align-items: center;
      border-radius: 999px;
      padding: 4px 9px;
      font-size: 11px;
      font-weight: 760;
      white-space: nowrap;
    }

    .pill-neutral { color: var(--muted); background: var(--surface-soft); }
    .pill-accent { color: var(--accent); background: var(--accent-soft); }
    .pill-success { color: var(--success); background: var(--success-soft); }
    .pill-warning { color: var(--warning); background: var(--warning-soft); }
    .pill-danger { color: var(--danger); background: var(--danger-soft); }

    .header {
      min-height: 70px;
      padding: 14px 24px;
      border-bottom: 1px solid var(--border);
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 16px;
      flex-shrink: 0;
      min-width: 0;
    }

    .header-main {
      min-width: 0;
    }

    .header-title {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      align-items: center;
      margin: 0;
      font-size: 17px;
      font-weight: 780;
      letter-spacing: -0.02em;
      min-width: 0;
    }

    .header-subtitle {
      color: var(--muted);
      font-size: 13px;
      margin-top: 4px;
      max-width: 100%;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }

    .header-actions {
      display: flex;
      align-items: center;
      gap: 8px;
      flex: 0 0 auto;
    }

    .session-id {
      color: var(--faint);
      font-family: "JetBrains Mono", monospace;
      font-size: 12px;
    }

    .chat-area {
      flex: 1;
      overflow-y: auto;
      min-width: 0;
      padding: 26px 24px;
    }

    .chat-inner {
      width: min(100%, 900px);
      margin: 0 auto;
      display: flex;
      flex-direction: column;
      gap: 18px;
      min-width: 0;
    }

    .empty-state {
      width: min(100%, 720px);
      margin: 80px auto;
      text-align: center;
      padding: 0 12px;
    }

    .empty-logo {
      width: 56px;
      height: 56px;
      border-radius: 18px;
      background: var(--accent-soft);
      color: var(--accent);
      display: grid;
      place-items: center;
      font-weight: 850;
      font-size: 24px;
      margin: 0 auto 20px;
    }

    .empty-state h1 {
      margin: 0 0 12px;
      font-size: clamp(25px, 4vw, 32px);
      line-height: 1.15;
      font-weight: 820;
      letter-spacing: -0.04em;
    }

    .empty-state p {
      color: var(--muted);
      font-size: 15px;
      line-height: 1.8;
      max-width: 620px;
      margin: 0 auto 24px;
    }

    .empty-pills {
      display: flex;
      justify-content: center;
      gap: 10px;
      flex-wrap: wrap;
    }

    .live-progress {
      width: min(100%, 900px);
      margin: 0 auto 18px;
      padding: 16px;
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: 18px;
      box-shadow: var(--shadow);
      min-width: 0;
    }

    .live-progress-head {
      display: flex;
      justify-content: space-between;
      align-items: flex-start;
      gap: 14px;
      min-width: 0;
      margin-bottom: 12px;
    }

    .live-progress-copy {
      min-width: 0;
    }

    .live-title {
      font-size: 14px;
      font-weight: 760;
    }

    .live-subtitle {
      color: var(--muted);
      font-size: 12px;
      margin-top: 4px;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }

    .live-count {
      color: var(--accent);
      font-family: "JetBrains Mono", monospace;
      font-size: 13px;
      font-weight: 760;
      flex: 0 0 auto;
    }

    .progress-track {
      height: 8px;
      background: var(--surface-soft);
      border-radius: 999px;
      overflow: hidden;
      margin-bottom: 10px;
    }

    .progress-fill {
      height: 100%;
      background: var(--accent);
      border-radius: 999px;
      transition: width 0.18s ease;
    }

    .live-footer {
      display: flex;
      justify-content: space-between;
      gap: 12px;
      color: var(--muted);
      font-size: 12px;
      min-width: 0;
    }

    .live-footer span:last-child {
      min-width: 0;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }

    .message-row {
      display: flex;
      min-width: 0;
    }

    .message-row-user {
      justify-content: flex-end;
    }

    .message-row-ai {
      justify-content: flex-start;
    }

    .message-user {
      max-width: min(74%, 680px);
      min-width: 0;
      background: var(--accent);
      color: white;
      padding: 13px 15px;
      border-radius: 18px 18px 5px 18px;
      font-size: 14px;
      line-height: 1.65;
      white-space: pre-wrap;
      word-break: break-word;
    }

    .message-ai {
      max-width: min(82%, 760px);
      min-width: 0;
      background: var(--surface);
      color: var(--text);
      border: 1px solid var(--border);
      border-radius: 18px 18px 18px 5px;
      box-shadow: var(--shadow);
      padding: 18px;
      font-size: 14px;
      line-height: 1.75;
      overflow-wrap: anywhere;
    }

    .message-ai-head {
      display: flex;
      align-items: center;
      gap: 9px;
      margin-bottom: 12px;
    }

    .message-ai-logo {
      width: 26px;
      height: 26px;
      border-radius: 9px;
      background: var(--accent-soft);
      color: var(--accent);
      display: grid;
      place-items: center;
      font-weight: 850;
      font-size: 13px;
      flex: 0 0 auto;
    }

    .message-ai-name {
      font-size: 13px;
      font-weight: 750;
    }

    .system-message {
      display: flex;
      justify-content: center;
    }

    .system-bubble {
      background: var(--warning-soft);
      color: var(--warning);
      border-radius: 999px;
      padding: 8px 12px;
      font-size: 12px;
      font-weight: 650;
      max-width: 100%;
      overflow-wrap: anywhere;
    }

    .citations {
      margin-top: 16px;
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
    }

    .citation-link {
      max-width: 230px;
      color: var(--accent);
      background: var(--accent-soft);
      border: 1px solid var(--border-soft);
      border-radius: 999px;
      padding: 7px 10px;
      text-decoration: none;
      font-size: 12px;
      font-weight: 700;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }

    .struggle {
      margin-top: 14px;
      color: var(--warning);
      background: var(--warning-soft);
      border-radius: 12px;
      padding: 10px 12px;
      font-size: 13px;
      font-weight: 680;
    }

    .loading-bubble {
      background: var(--surface);
      border: 1px solid var(--border);
      box-shadow: var(--shadow);
      border-radius: 18px 18px 18px 5px;
      color: var(--muted);
      padding: 14px 16px;
      font-size: 14px;
    }

    .input-footer {
      border-top: 1px solid var(--border);
      background: var(--surface);
      padding: 16px 20px;
      flex-shrink: 0;
      min-width: 0;
    }

    .input-wrap {
      width: min(100%, 900px);
      margin: 0 auto;
      display: flex;
      align-items: center;
      gap: 10px;
      background: var(--bg);
      border: 1px solid var(--border);
      border-radius: 18px;
      padding: 9px;
      min-width: 0;
    }

    .chat-input {
      flex: 1;
      min-width: 0;
      background: transparent;
      border: 0;
      outline: 0;
      color: var(--text);
      font-size: 14px;
      padding: 8px;
    }

    .send-button {
      border: 0;
      border-radius: 13px;
      background: var(--accent);
      color: white;
      padding: 10px 15px;
      font-size: 14px;
      font-weight: 760;
      cursor: pointer;
      flex: 0 0 auto;
    }

    .send-button:disabled {
      background: var(--surface-soft);
      color: var(--muted);
      cursor: not-allowed;
    }

    .card-empty {
      color: var(--muted);
      margin: 0;
      font-size: 13px;
      line-height: 1.7;
    }

    .activity-item {
      display: flex;
      gap: 10px;
      padding: 8px 0;
      border-bottom: 1px solid var(--border-soft);
      min-width: 0;
    }

    .activity-item:last-child {
      border-bottom: 0;
    }

    .activity-dot {
      width: 20px;
      height: 20px;
      border-radius: 999px;
      display: grid;
      place-items: center;
      font-size: 12px;
      font-weight: 850;
      flex: 0 0 auto;
      background: var(--success-soft);
      color: var(--success);
    }

    .activity-progress {
      background: var(--accent-soft);
      color: var(--accent);
    }

    .activity-error {
      background: var(--danger-soft);
      color: var(--danger);
    }

    .activity-body {
      min-width: 0;
    }

    .activity-message {
      font-size: 13px;
      line-height: 1.45;
      font-weight: 520;
    }

    .activity-meta {
      margin-top: 3px;
      color: var(--faint);
      font-size: 11px;
      font-family: "JetBrains Mono", monospace;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }

    .source-item,
    .vault-item {
      width: 100%;
      text-align: left;
      display: block;
      color: var(--text);
      background: var(--surface-soft);
      border: 1px solid var(--border-soft);
      border-radius: 12px;
      padding: 10px 11px;
      font-size: 12px;
      line-height: 1.5;
      text-decoration: none;
      cursor: pointer;
      min-width: 0;
    }

    .source-item span,
    .vault-item span {
      display: block;
      color: var(--accent);
      font-weight: 750;
      margin-bottom: 4px;
    }

    .source-item strong,
    .vault-item strong {
      display: block;
      color: var(--text);
      font-weight: 650;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }

    .md-link { color: var(--accent); font-weight: 650; text-decoration: none; word-break: break-word; }
    .md-p { margin: 0 0 12px; line-height: 1.75; }
    .md-list { padding-left: 22px; margin: 0 0 12px; line-height: 1.75; }
    .md-li { margin-bottom: 6px; }
    .md-strong { color: var(--text); font-weight: 760; }
    .md-h1, .md-h2, .md-h3 { color: var(--text); margin: 8px 0 10px; line-height: 1.3; }
    .md-h1 { font-size: 22px; }
    .md-h2 { font-size: 18px; }
    .md-h3 { font-size: 16px; }

    .inline-code {
      background: var(--surface-soft);
      color: var(--text);
      border: 1px solid var(--border);
      border-radius: 6px;
      padding: 2px 6px;
      font-family: "JetBrains Mono", monospace;
      font-size: 13px;
    }

    .code-block {
      max-width: 100%;
      overflow-x: auto;
      background: var(--bg);
      border: 1px solid var(--border);
      border-radius: 12px;
      padding: 16px;
      margin: 12px 0;
      font-family: "JetBrains Mono", monospace;
      font-size: 13px;
      line-height: 1.7;
    }

    .blockquote {
      border-left: 3px solid var(--accent);
      background: var(--accent-soft);
      color: var(--muted);
      border-radius: 10px;
      padding: 10px 14px;
      margin: 12px 0;
    }

    .typewriter { white-space: pre-wrap; }
    .caret { opacity: 0.75; animation: blink 1s infinite; }
    @keyframes blink { 0%,100%{opacity:1} 50%{opacity:0} }

    .drawer-overlay {
      display: none;
    }

    .details-drawer {
      display: none;
    }

    @media (max-width: 1240px) {
      .app-shell {
        grid-template-columns: minmax(250px, 290px) minmax(0, 1fr);
      }

      .details {
        display: none;
      }

      .header-actions .details-toggle {
        display: inline-flex;
      }

      .details-drawer {
        display: flex;
        position: fixed;
        top: 0;
        right: 0;
        width: min(88vw, 360px);
        height: 100%;
        z-index: 60;
        background: var(--bg);
        border-left: 1px solid var(--border);
        padding: 18px;
        overflow-y: auto;
        flex-direction: column;
        gap: 14px;
        transform: translateX(105%);
        transition: transform 0.2s ease;
      }

      .details-drawer-open {
        transform: translateX(0);
      }

      .drawer-overlay {
        display: block;
        position: fixed;
        inset: 0;
        z-index: 50;
        background: rgba(15, 23, 42, 0.35);
      }
    }

    @media (min-width: 1241px) {
      .details-toggle {
        display: none;
      }
    }

    @media (max-width: 780px) {
      .app-shell {
        display: flex;
        flex-direction: column;
        height: 100%;
      }

      .mobile-bar {
        display: flex;
        height: 58px;
        flex: 0 0 58px;
        align-items: center;
        justify-content: space-between;
        gap: 10px;
        background: var(--surface);
        border-bottom: 1px solid var(--border);
        padding: 10px 12px;
        z-index: 35;
      }

      .mobile-title {
        display: flex;
        align-items: center;
        gap: 10px;
        min-width: 0;
      }

      .mobile-title strong {
        display: block;
        font-size: 15px;
      }

      .mobile-title span {
        display: block;
        max-width: 190px;
        color: var(--muted);
        font-size: 11px;
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
      }

      .sidebar {
        position: fixed;
        top: 58px;
        left: 0;
        bottom: 0;
        width: min(88vw, 340px);
        transform: translateX(-105%);
        box-shadow: 0 20px 60px rgba(15, 23, 42, 0.22);
        transition: transform 0.2s ease;
      }

      .sidebar-open {
        transform: translateX(0);
      }

      .sidebar-overlay {
        display: block;
        position: fixed;
        top: 58px;
        left: 0;
        right: 0;
        bottom: 0;
        background: rgba(15, 23, 42, 0.35);
        z-index: 30;
      }

      .main {
        flex: 1;
        height: calc(100% - 58px);
      }

      .header {
        min-height: auto;
        padding: 12px 14px;
        align-items: flex-start;
      }

      .header-title {
        font-size: 15px;
      }

      .header-subtitle {
        white-space: normal;
        line-height: 1.4;
      }

      .header-actions {
        gap: 6px;
      }

      .session-id {
        display: none;
      }

      .chat-area {
        padding: 16px 12px;
      }

      .chat-inner {
        gap: 14px;
      }

      .empty-state {
        margin: 42px auto;
      }

      .empty-state p {
        font-size: 14px;
      }

      .live-progress {
        padding: 14px;
      }

      .live-progress-head,
      .live-footer {
        flex-direction: column;
        gap: 6px;
      }

      .live-subtitle,
      .live-footer span:last-child {
        white-space: normal;
      }

      .message-user,
      .message-ai {
        max-width: 100%;
        font-size: 14px;
      }

      .input-footer {
        padding: 12px;
      }

      .input-wrap {
        border-radius: 15px;
      }

      .send-button {
        padding: 10px 12px;
      }
    }
  `;

  const detailsContent = (
    <>
      <AgentActivity events={progressEvents} />
      <SourcesPanel sources={latestSources} />
      <VaultPanel vaultFiles={vaultFiles} onOpen={(file) => window.open(`${API}/vault/${file}`, "_blank")} />
    </>
  );

  return (
    <div className="app-shell">
      <style>{css}</style>

      <div className="mobile-bar">
        <button className="icon-button" type="button" onClick={() => setMobileSidebarOpen(true)}>
          Menu
        </button>

        <div className="mobile-title">
          <div className="logo">V</div>
          <div>
            <strong>VaultLearn</strong>
            <span>{activeModule ? activeModule.title : "AI documentation workspace"}</span>
          </div>
        </div>

        <button className="icon-button" type="button" onClick={() => setDetailsOpen(true)}>
          Details
        </button>
      </div>

      {mobileSidebarOpen && (
        <div className="sidebar-overlay" onClick={() => setMobileSidebarOpen(false)} />
      )}

      <aside className={`sidebar ${mobileSidebarOpen ? "sidebar-open" : ""}`}>
        <div className="brand">
          <div className="brand-left">
            <div className="logo">V</div>
            <div style={{ minWidth: 0 }}>
              <div className="brand-title">VaultLearn</div>
              <div className="brand-subtitle">AI documentation workspace</div>
            </div>
          </div>

          <button className="theme-button" type="button" onClick={() => setDark((value) => !value)}>
            {dark ? "Light" : "Dark"}
          </button>
        </div>

        <div className="panel">
          <SectionTitle>Documentation source</SectionTitle>
          <input
            className="url-input"
            placeholder="https://fastapi.tiangolo.com"
            value={url}
            onChange={(event) => setUrl(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter") handleSetup();
            }}
          />

          <button
            className="primary-button"
            type="button"
            disabled={settingUp || !url.trim()}
            onClick={handleSetup}
          >
            {settingUp ? "Indexing documentation..." : "Index documentation"}
          </button>
        </div>

        {pastSessions.length > 0 && !studyPlan && (
          <div>
            <SectionTitle>Recent sessions</SectionTitle>
            <div className="session-list">
              {pastSessions.slice(0, 8).map((session) => (
                <button
                  className="session-item"
                  type="button"
                  key={getSessionId(session)}
                  onClick={() => handleResume(session)}
                >
                  <div className="session-title">{getSessionTitle(session)}</div>
                  <div className="session-meta">
                    {formatDate(session.created_at || session.updated_at)} · {getSessionUrl(session)}
                  </div>
                </button>
              ))}
            </div>
          </div>
        )}

        {studyPlan && (
          <div>
            <SectionTitle action={<span>{modules.length} modules</span>}>Learning modules</SectionTitle>

            <div className="module-list">
              {modules.map((module) => {
                const active = currentModule === module.module_number;

                return (
                  <button
                    className={`module-item ${active ? "module-item-active" : ""}`}
                    type="button"
                    key={module.module_number}
                    onClick={() => {
                      setCurrentModule(module.module_number);
                      setMobileSidebarOpen(false);
                    }}
                  >
                    <div className="module-top">
                      <span className="module-num">{String(module.module_number).padStart(2, "0")}</span>
                      <span className="module-title">{module.title}</span>
                    </div>

                    <div className="module-meta">
                      <Pill variant={priorityVariant(module.priority)}>{module.priority || "MODULE"}</Pill>
                      {module.estimated_hours && <span style={{ marginLeft: 8 }}>{module.estimated_hours}h</span>}
                    </div>
                  </button>
                );
              })}
            </div>

            <button className="danger-button" type="button" onClick={() => handleSend("end session")}>
              End session and write vault notes
            </button>
          </div>
        )}
      </aside>

      <main className="main">
        <header className="header">
          <div className="header-main">
            <h2 className="header-title">
              {studyPlan?.title || "Documentation learning session"}
              {sessionId && <Pill variant="success">Active</Pill>}
            </h2>
            <div className="header-subtitle">
              {activeModule
                ? `Module ${String(currentModule).padStart(2, "0")} · ${activeModule.title}`
                : "Index a documentation source or resume a previous session."}
            </div>
          </div>

          <div className="header-actions">
            {notesWritten && <Pill variant="success">Notes saved</Pill>}
            {sessionId && <span className="session-id">{sessionId.slice(0, 8)}</span>}
            <button className="icon-button details-toggle" type="button" onClick={() => setDetailsOpen(true)}>
              Details
            </button>
          </div>
        </header>

        <section className="chat-area" onClick={() => inputRef.current?.focus()}>
          {liveProgress && <LiveProgressCard progress={liveProgress} />}

          {messages.length === 0 ? (
            <EmptyState />
          ) : (
            <div className="chat-inner">
              {messages.map((message, index) => {
                const isLast = index === messages.length - 1;

                if (message.role === "user") {
                  return (
                    <div className="message-row message-row-user" key={index}>
                      <div className="message-user">{message.content}</div>
                    </div>
                  );
                }

                if (message.role === "system") {
                  return (
                    <div className="system-message" key={index}>
                      <div className="system-bubble">{message.content}</div>
                    </div>
                  );
                }

                if (message.role === "ai") {
                  return (
                    <div className="message-row message-row-ai" key={index}>
                      <div className="message-ai">
                        <div className="message-ai-head">
                          <div className="message-ai-logo">V</div>
                          <div className="message-ai-name">VaultLearn</div>
                        </div>

                        <TypeWriter text={message.content || ""} active={Boolean(message.typewrite && isLast)} />

                        {message.citations?.length > 0 && (
                          <div className="citations">
                            {[...new Set(message.citations)].slice(0, 5).map((citation, citationIndex) => {
                              const label =
                                citation.split("#")[1] ||
                                citation.split("/").filter(Boolean).pop() ||
                                "Source";

                              return (
                                <a
                                  className="citation-link"
                                  key={citation}
                                  href={citation}
                                  target="_blank"
                                  rel="noreferrer"
                                >
                                  {citationIndex + 1}. {label}
                                </a>
                              );
                            })}
                          </div>
                        )}

                        {message.struggles && Object.keys(message.struggles).length > 0 && (
                          <div className="struggle">Struggle signal detected — added to review memory.</div>
                        )}
                      </div>
                    </div>
                  );
                }

                return null;
              })}

              {loading && (
                <div className="message-row message-row-ai">
                  <div className="loading-bubble">Thinking through the documentation...</div>
                </div>
              )}

              <div ref={bottomRef} />
            </div>
          )}
        </section>

        <footer className="input-footer">
          <div className="input-wrap">
            <input
              ref={inputRef}
              className="chat-input"
              placeholder={sessionId ? "Ask about this documentation..." : "Index or resume a documentation session first..."}
              value={input}
              onChange={(event) => setInput(event.target.value)}
              onKeyDown={handleKeyDown}
              disabled={!sessionId || loading}
            />

            <button
              className="send-button"
              type="button"
              disabled={!sessionId || loading || !input.trim()}
              onClick={() => handleSend()}
            >
              Send
            </button>
          </div>
        </footer>
      </main>

      <aside className="details">{detailsContent}</aside>

      {detailsOpen && (
        <>
          <div className="drawer-overlay" onClick={() => setDetailsOpen(false)} />
          <aside className="details-drawer details-drawer-open">
            <div className="brand">
              <div>
                <div className="brand-title">Session details</div>
                <div className="brand-subtitle">Activity, citations, and vault notes</div>
              </div>
              <button className="icon-button" type="button" onClick={() => setDetailsOpen(false)}>
                Close
              </button>
            </div>
            {detailsContent}
          </aside>
        </>
      )}
    </div>
  );
}
