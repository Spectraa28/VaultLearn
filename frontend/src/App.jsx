import { useEffect, useMemo, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";

const API = import.meta.env.VITE_API_URL || "http://localhost:8001";

function getSessionId(session) {
  return session?.session_id || session?.id;
}

function getSessionTitle(session) {
  return session?.title || session?.name || session?.url || session?.root_url || "Untitled session";
}

function getSessionUrl(session) {
  return session?.url || session?.root_url || session?.source_url || "";
}

function formatDate(value) {
  if (!value) return "Recently";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "Recently";
  return date.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
}

function makeSseParser(onData) {
  let buffer = "";
  return function parse(chunkText) {
    buffer += chunkText;
    const events = buffer.split("\n\n");
    buffer = events.pop() || "";

    for (const rawEvent of events) {
      const dataLine = rawEvent.split("\n").find((line) => line.startsWith("data: "));
      if (!dataLine) continue;

      try {
        onData(JSON.parse(dataLine.replace("data: ", "")));
      } catch (error) {
        console.error("Invalid SSE payload", dataLine, error);
      }
    }
  };
}

async function readSseResponse(response, onData) {
  if (!response.body) throw new Error("Streaming response body is not available");

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  const parse = makeSseParser(onData);

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    parse(decoder.decode(value, { stream: true }));
  }
}

function Markdown({ text, theme }) {
  const components = {
    a: ({ href, children }) => (
      <a href={href} target="_blank" rel="noreferrer" style={{ color: theme.accent, textDecoration: "none", fontWeight: 650, wordBreak: "break-word" }}>
        {children}
      </a>
    ),
    p: ({ children }) => <p style={{ margin: "0 0 12px", lineHeight: 1.75 }}>{children}</p>,
    ul: ({ children }) => <ul style={{ margin: "0 0 12px", paddingLeft: 22, lineHeight: 1.75 }}>{children}</ul>,
    ol: ({ children }) => <ol style={{ margin: "0 0 12px", paddingLeft: 22, lineHeight: 1.75 }}>{children}</ol>,
    li: ({ children }) => <li style={{ marginBottom: 6 }}>{children}</li>,
    strong: ({ children }) => <strong style={{ fontWeight: 750, color: theme.text }}>{children}</strong>,
    code: ({ children }) => (
      <code style={{ background: theme.surfaceSoft, border: `1px solid ${theme.border}`, borderRadius: 6, padding: "2px 6px", fontSize: 13, fontFamily: "JetBrains Mono, monospace" }}>
        {children}
      </code>
    ),
    pre: ({ children }) => (
      <pre style={{ background: theme.codeBg, border: `1px solid ${theme.border}`, borderRadius: 14, padding: 16, overflowX: "auto", margin: "12px 0", fontSize: 13, lineHeight: 1.7, fontFamily: "JetBrains Mono, monospace" }}>
        {children}
      </pre>
    ),
    blockquote: ({ children }) => (
      <blockquote style={{ borderLeft: `3px solid ${theme.accent}`, background: theme.accentSoft, color: theme.muted, borderRadius: 12, padding: "10px 14px", margin: "12px 0" }}>
        {children}
      </blockquote>
    ),
    h1: ({ children }) => <h1 style={{ fontSize: 24, lineHeight: 1.2, margin: "8px 0 12px", fontWeight: 800 }}>{children}</h1>,
    h2: ({ children }) => <h2 style={{ fontSize: 19, lineHeight: 1.3, margin: "8px 0 10px", fontWeight: 780 }}>{children}</h2>,
    h3: ({ children }) => <h3 style={{ fontSize: 16, lineHeight: 1.35, margin: "8px 0 8px", fontWeight: 740 }}>{children}</h3>,
  };

  return <ReactMarkdown components={components}>{text}</ReactMarkdown>;
}

function TypeWriter({ text, theme, active }) {
  const [displayed, setDisplayed] = useState(active ? "" : text);
  const [done, setDone] = useState(!active);
  const idx = useRef(0);

  useEffect(() => {
    if (!active) {
      setDisplayed(text);
      setDone(true);
      return;
    }

    setDisplayed("");
    setDone(false);
    idx.current = 0;

    const interval = setInterval(() => {
      if (idx.current < text.length) {
        setDisplayed(text.slice(0, idx.current + 1));
        idx.current += 1;
      } else {
        clearInterval(interval);
        setDone(true);
      }
    }, 5);

    return () => clearInterval(interval);
  }, [text, active]);

  if (!done) {
    return (
      <span style={{ whiteSpace: "pre-wrap" }}>
        {displayed}
        <span style={{ opacity: 0.7 }}>▋</span>
      </span>
    );
  }

  return <Markdown text={text} theme={theme} />;
}

function Pill({ children, color, background }) {
  return (
    <span style={{ display: "inline-flex", alignItems: "center", borderRadius: 999, padding: "4px 9px", fontSize: 11, fontWeight: 750, color, background, whiteSpace: "nowrap" }}>
      {children}
    </span>
  );
}

function SectionTitle({ children, theme, right }) {
  return (
    <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8, marginBottom: 10 }}>
      <div style={{ fontSize: 12, fontWeight: 760, color: theme.muted, textTransform: "uppercase", letterSpacing: "0.08em" }}>{children}</div>
      {right}
    </div>
  );
}

function EmptyState({ theme }) {
  return (
    <div style={{ maxWidth: 720, margin: "82px auto", textAlign: "center" }}>
      <div style={{ width: 58, height: 58, borderRadius: 18, background: theme.accentSoft, color: theme.accent, display: "flex", alignItems: "center", justifyContent: "center", margin: "0 auto 20px", fontWeight: 850, fontSize: 24 }}>V</div>
      <h1 style={{ margin: "0 0 12px", fontSize: 33, lineHeight: 1.12, letterSpacing: "-0.04em", fontWeight: 840, color: theme.text }}>Learn any documentation with memory.</h1>
      <p style={{ margin: "0 auto 24px", maxWidth: 620, color: theme.muted, fontSize: 15, lineHeight: 1.8 }}>
        Paste a documentation URL, generate a structured study plan, ask grounded questions, and save review notes across sessions.
      </p>
      <div style={{ display: "flex", justifyContent: "center", flexWrap: "wrap", gap: 10 }}>
        <Pill color={theme.accent} background={theme.accentSoft}>Persistent sessions</Pill>
        <Pill color={theme.success} background={theme.successSoft}>Citation grounded</Pill>
        <Pill color={theme.warning} background={theme.warningSoft}>Struggle memory</Pill>
      </div>
    </div>
  );
}

function ActivityPanel({ events, theme }) {
  return (
    <div className="vl-panel-card" style={{ background: theme.surface, border: `1px solid ${theme.border}`, borderRadius: 18, padding: 16, boxShadow: theme.cardShadow }}>
      <SectionTitle theme={theme}>Agent activity</SectionTitle>
      {events.length === 0 ? (
        <div style={{ color: theme.muted, fontSize: 13, lineHeight: 1.7 }}>Indexing, retrieval, reranking, generation, and memory updates will appear here.</div>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
          {events.slice(-14).map((event, index) => (
            <div key={`${event.message}-${index}`} style={{ display: "flex", gap: 10, alignItems: "flex-start", padding: "8px 0", borderBottom: index === events.slice(-14).length - 1 ? "none" : `1px solid ${theme.borderSoft}` }}>
              <div style={{ width: 20, height: 20, borderRadius: 999, background: event.type === "error" ? theme.dangerSoft : event.type === "progress" ? theme.accentSoft : theme.successSoft, color: event.type === "error" ? theme.danger : event.type === "progress" ? theme.accent : theme.success, display: "flex", alignItems: "center", justifyContent: "center", fontSize: 12, fontWeight: 850, flexShrink: 0, marginTop: 1 }}>
                {event.type === "error" ? "!" : "✓"}
              </div>
              <div style={{ minWidth: 0 }}>
                <div style={{ color: theme.text, fontSize: 13, lineHeight: 1.45, fontWeight: 560 }}>{event.message}</div>
                {event.meta && <div style={{ color: theme.faint, fontSize: 11, marginTop: 3, fontFamily: "JetBrains Mono, monospace", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{event.meta}</div>}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function SourcesPanel({ sources, theme }) {
  const uniqueSources = [...new Set(sources || [])].slice(0, 8);

  return (
    <div className="vl-panel-card" style={{ background: theme.surface, border: `1px solid ${theme.border}`, borderRadius: 18, padding: 16, boxShadow: theme.cardShadow }}>
      <SectionTitle theme={theme}>Sources</SectionTitle>
      {uniqueSources.length === 0 ? (
        <div style={{ color: theme.muted, fontSize: 13, lineHeight: 1.7 }}>Citation links from the retrieved documentation will appear here.</div>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          {uniqueSources.map((source, index) => {
            const label = source.split("#")[1] || source.split("/").filter(Boolean).pop() || "Source";
            return (
              <a key={source} href={source} target="_blank" rel="noreferrer" style={{ display: "block", textDecoration: "none", color: theme.text, background: theme.surfaceSoft, border: `1px solid ${theme.borderSoft}`, borderRadius: 12, padding: "10px 11px", fontSize: 12, lineHeight: 1.45 }}>
                <div style={{ color: theme.accent, fontWeight: 780, marginBottom: 4 }}>Source {index + 1}</div>
                <div style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{label}</div>
              </a>
            );
          })}
        </div>
      )}
    </div>
  );
}

function VaultPanel({ vaultFiles, theme, onOpen }) {
  return (
    <div className="vl-panel-card" style={{ background: theme.surface, border: `1px solid ${theme.border}`, borderRadius: 18, padding: 16, boxShadow: theme.cardShadow }}>
      <SectionTitle theme={theme}>Vault memory</SectionTitle>
      {vaultFiles.length === 0 ? (
        <div style={{ color: theme.muted, fontSize: 13, lineHeight: 1.7 }}>Session notes, struggle notes, and review schedules will appear after ending a session.</div>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          {vaultFiles.slice(0, 7).map((file) => (
            <button key={file} onClick={() => onOpen(file)} style={{ textAlign: "left", background: theme.surfaceSoft, border: `1px solid ${theme.borderSoft}`, borderRadius: 12, padding: "10px 11px", color: theme.text, cursor: "pointer", fontSize: 12, lineHeight: 1.4 }}>
              <div style={{ fontWeight: 740, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", marginBottom: 3 }}>{file.replace(".md", "")}</div>
              <div style={{ color: theme.muted, fontSize: 11 }}>Markdown note</div>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

export default function App() {
  const [dark, setDark] = useState(false);
  const [url, setUrl] = useState("");
  const [sessionId, setSessionId] = useState(null);
  const [studyPlan, setStudyPlan] = useState(null);
  const [currentModule, setCurrentModule] = useState(1);
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [settingUp, setSettingUp] = useState(false);
  const [vaultFiles, setVaultFiles] = useState([]);
  const [notesWritten, setNotesWritten] = useState(false);
  const [history, setHistory] = useState([]);
  const [histIdx, setHistIdx] = useState(-1);
  const [pastSessions, setPastSessions] = useState([]);
  const [progressEvents, setProgressEvents] = useState([]);

  const bottomRef = useRef(null);
  const inputRef = useRef(null);

  const theme = useMemo(() => ({
    bg: dark ? "#0B1120" : "#F8FAFC",
    sidebar: dark ? "#0F172A" : "#FFFFFF",
    surface: dark ? "#111827" : "#FFFFFF",
    surfaceSoft: dark ? "#1E293B" : "#F1F5F9",
    codeBg: dark ? "#020617" : "#F8FAFC",
    text: dark ? "#E5E7EB" : "#0F172A",
    muted: dark ? "#94A3B8" : "#64748B",
    faint: dark ? "#64748B" : "#94A3B8",
    border: dark ? "#1F2937" : "#E2E8F0",
    borderSoft: dark ? "#172033" : "#EEF2F7",
    accent: "#4F46E5",
    accentSoft: dark ? "rgba(79,70,229,0.18)" : "#EEF2FF",
    success: "#059669",
    successSoft: dark ? "rgba(5,150,105,0.16)" : "#ECFDF5",
    warning: "#D97706",
    warningSoft: dark ? "rgba(217,119,6,0.16)" : "#FFFBEB",
    danger: "#DC2626",
    dangerSoft: dark ? "rgba(220,38,38,0.16)" : "#FEF2F2",
    cardShadow: dark ? "none" : "0 8px 30px rgba(15, 23, 42, 0.06)",
  }), [dark]);

  const modules = studyPlan?.modules || [];
  const activeModule = modules.find((module) => module.module_number === currentModule);
  const latestSources = [...messages].reverse().find((message) => message.role === "ai" && message.citations?.length)?.citations || [];

  useEffect(() => {
    document.body.style.background = theme.bg;
  }, [theme.bg]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, loading]);

  const addProgress = (message, type = "status", meta = null) => {
    setProgressEvents((previous) => [...previous, { message, type, meta, createdAt: new Date().toISOString() }]);
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
      console.error("Failed to load vault", error);
    }
  };

  useEffect(() => {
    refreshSessions();
    fetchVault();
  }, []);

  useEffect(() => {
    fetchVault();
  }, [notesWritten]);

  const handleSetupPayload = (data) => {
    if (data.type === "progress") {
      addProgress(`Chunking documentation page ${data.current ?? "?"}/${data.total ?? "?"}`, "progress", `${data.module || "Module"} · ${data.page || "Page"}`);
      return;
    }

    if (data.type === "status") {
      addProgress(data.message || "Working...", "status");
      return;
    }

    if (data.type === "done") {
      const plan = data.study_plan || {};
      const moduleCount = plan.modules?.length || 0;
      setSessionId(data.session_id);
      setStudyPlan(plan);
      setCurrentModule(1);
      setMessages((previous) => [...previous, {
        role: "ai",
        content: `The documentation index is ready. I found **${moduleCount} learning modules** and prepared the session.\n\nChoose a module on the left, or ask your first question about the documentation.`,
        citations: [],
        typewrite: true,
      }]);
      addProgress("Documentation index ready", "status");
      refreshSessions();
      return;
    }

    if (data.type === "error") {
      addProgress(data.message || "Setup failed", "error");
      setMessages((previous) => [...previous, { role: "system", content: data.message || "Setup failed. Please try another URL." }]);
    }
  };

  const handleSetup = async () => {
    const trimmedUrl = url.trim();
    if (!trimmedUrl || settingUp) return;

    setSettingUp(true);
    setMessages([]);
    setProgressEvents([]);
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
        const moduleCount = data.study_plan?.modules?.length || 0;
        setSessionId(data.session_id);
        setStudyPlan(data.study_plan);
        setCurrentModule(1);
        setMessages([{ role: "ai", content: `The documentation index is ready. I found **${moduleCount} learning modules** and prepared the session.\n\nChoose a module on the left, or ask your first question about the documentation.`, citations: [], typewrite: true }]);
        addProgress("Documentation index ready", "status");
        refreshSessions();
      } else {
        await readSseResponse(response, handleSetupPayload);
      }
    } catch (error) {
      console.error(error);
      addProgress(error.message || "Setup failed", "error");
      setMessages([{ role: "system", content: "I could not index this documentation source. Try a direct documentation URL." }]);
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
    setNotesWritten(false);
    addProgress(`Resuming ${getSessionTitle(session)}`, "status");

    try {
      const response = await fetch(`${API}/session/${id}/resume`, { method: "POST" });
      if (!response.ok) throw new Error(`Resume failed with status ${response.status}`);

      const contentType = response.headers.get("content-type") || "";
      if (contentType.includes("application/json")) {
        const data = await response.json();
        const plan = data.study_plan || {};
        const moduleCount = plan.modules?.length || 0;
        setSessionId(data.session_id || id);
        setStudyPlan(plan);
        setCurrentModule(1);
        setMessages([{ role: "ai", content: `Resumed **${plan.title || getSessionTitle(session)}**. ${moduleCount} modules are ready.\n\nYou can continue learning from this documentation session.`, citations: [], typewrite: true }]);
        addProgress("Session resumed from persisted index", "status");
      } else {
        await readSseResponse(response, (data) => {
          if (data.type === "status") addProgress(data.message || "Resuming session...", "status");
          if (data.type === "progress") addProgress(`Rebuilding page ${data.current}/${data.total}`, "progress", `${data.module || "Module"} · ${data.page || "Page"}`);
          if (data.type === "error") addProgress(data.message || "Resume failed", "error");
          if (data.type === "done") {
            const plan = data.study_plan || {};
            const moduleCount = plan.modules?.length || 0;
            setSessionId(data.session_id || id);
            setStudyPlan(plan);
            setCurrentModule(1);
            setMessages([{ role: "ai", content: `Resumed **${plan.title || getSessionTitle(session)}**. ${moduleCount} modules are ready.\n\nYou can continue learning from this documentation session.`, citations: [], typewrite: true }]);
            addProgress("Session resumed", "status");
          }
        });
      }
    } catch (error) {
      console.error(error);
      addProgress(error.message || "Resume failed", "error");
      setMessages([{ role: "system", content: "I could not resume this session. Try indexing the URL again." }]);
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

    addProgress("Saving user question", "status");
    addProgress("Loading vault memory and session context", "status");
    addProgress("Retrieving relevant documentation chunks", "progress");

    try {
      const response = await fetch(`${API}/session/${sessionId}/message`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: text }),
      });

      if (!response.ok) throw new Error(`Request failed with status ${response.status}`);

      addProgress("Reranking retrieved context", "progress");
      const data = await response.json();
      addProgress("Generated citation-grounded answer", "status");

      setMessages((previous) => [...previous, {
        role: "ai",
        content: data.answer || "",
        citations: data.citations || data.citation || [],
        struggles: data.struggle_signals || {},
        typewrite: true,
      }]);

      if (data.struggle_signals && Object.keys(data.struggle_signals).length > 0) {
        addProgress("Detected struggle signal and added review memory", "status");
      }

      if (data.notes_written) {
        setNotesWritten(true);
        addProgress("Wrote vault notes and spaced repetition schedule", "status");
        fetchVault();
      }
    } catch (error) {
      console.error(error);
      addProgress(error.message || "Message failed", "error");
      setMessages((previous) => [...previous, { role: "system", content: "The request failed. Please try again." }]);
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

  const priorityStyle = (priority) => {
    if (priority === "RED") return { color: theme.danger, background: theme.dangerSoft };
    if (priority === "YELLOW") return { color: theme.warning, background: theme.warningSoft };
    return { color: theme.success, background: theme.successSoft };
  };

  const globalCss = `
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;500;600&display=swap');
    * { box-sizing: border-box; }
    body { margin: 0; font-family: Inter, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; background: ${theme.bg}; }
    button, input { font-family: inherit; }
    input::placeholder { color: ${theme.faint}; opacity: 1; }
    ::-webkit-scrollbar { width: 7px; height: 7px; }
    ::-webkit-scrollbar-track { background: transparent; }
    ::-webkit-scrollbar-thumb { background: ${theme.border}; border-radius: 999px; }
    .vl-button:hover { transform: translateY(-1px); box-shadow: ${dark ? "none" : "0 8px 18px rgba(79,70,229,0.18)"}; }
    .vl-card-hover:hover { border-color: ${theme.accent} !important; background: ${theme.accentSoft} !important; }
    @media (max-width: 1100px) { .vl-right-panel { display: none !important; } }
    @media (max-width: 820px) {
      .vl-app { flex-direction: column !important; }
      .vl-sidebar { width: 100% !important; min-width: 100% !important; max-height: 42vh; border-right: none !important; border-bottom: 1px solid ${theme.border} !important; }
    }
  `;

  return (
    <div className="vl-app" style={{ display: "flex", height: "100vh", overflow: "hidden", background: theme.bg, color: theme.text }}>
      <style>{globalCss}</style>

      <aside className="vl-sidebar" style={{ width: 330, minWidth: 330, background: theme.sidebar, borderRight: `1px solid ${theme.border}`, display: "flex", flexDirection: "column", gap: 18, padding: 20, overflowY: "auto" }}>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 11 }}>
            <div style={{ width: 38, height: 38, borderRadius: 12, background: theme.accent, color: "white", display: "flex", alignItems: "center", justifyContent: "center", fontWeight: 850, fontSize: 18 }}>V</div>
            <div>
              <div style={{ fontSize: 18, fontWeight: 820, letterSpacing: "-0.02em" }}>VaultLearn</div>
              <div style={{ fontSize: 12, color: theme.muted, marginTop: 2 }}>AI documentation workspace</div>
            </div>
          </div>
          <button onClick={() => setDark((value) => !value)} style={{ border: `1px solid ${theme.border}`, background: theme.surface, color: theme.muted, borderRadius: 10, padding: "8px 10px", cursor: "pointer", fontSize: 12, fontWeight: 680 }}>
            {dark ? "Light" : "Dark"}
          </button>
        </div>

        <div style={{ background: theme.surface, border: `1px solid ${theme.border}`, borderRadius: 18, padding: 14, boxShadow: theme.cardShadow }}>
          <SectionTitle theme={theme}>Documentation source</SectionTitle>
          <input placeholder="https://fastapi.tiangolo.com" value={url} onChange={(event) => setUrl(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter") handleSetup(); }} style={{ width: "100%", background: theme.surfaceSoft, border: `1px solid ${theme.border}`, borderRadius: 12, padding: "12px 12px", color: theme.text, fontSize: 14, outline: "none", marginBottom: 10 }} />
          <button className="vl-button" onClick={handleSetup} disabled={settingUp || !url.trim()} style={{ width: "100%", background: settingUp || !url.trim() ? theme.surfaceSoft : theme.accent, color: settingUp || !url.trim() ? theme.muted : "white", border: "none", borderRadius: 12, padding: "12px 14px", fontSize: 14, fontWeight: 760, cursor: settingUp || !url.trim() ? "not-allowed" : "pointer", transition: "all 0.16s ease" }}>
            {settingUp ? "Indexing documentation..." : "Index documentation"}
          </button>
        </div>

        {pastSessions.length > 0 && !studyPlan && (
          <div>
            <SectionTitle theme={theme}>Recent sessions</SectionTitle>
            <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
              {pastSessions.slice(0, 8).map((session) => (
                <button key={getSessionId(session)} className="vl-card-hover" onClick={() => handleResume(session)} style={{ textAlign: "left", background: theme.surface, border: `1px solid ${theme.border}`, borderRadius: 14, padding: "11px 12px", color: theme.text, cursor: "pointer", transition: "all 0.14s ease", boxShadow: theme.cardShadow }}>
                  <div style={{ fontSize: 13, fontWeight: 740, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", marginBottom: 4 }}>{getSessionTitle(session)}</div>
                  <div style={{ fontSize: 11, color: theme.muted, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{formatDate(session.created_at || session.updated_at)} · {getSessionUrl(session)}</div>
                </button>
              ))}
            </div>
          </div>
        )}

        {studyPlan && (
          <div>
            <SectionTitle theme={theme} right={<span style={{ fontSize: 12, color: theme.muted }}>{modules.length} modules</span>}>Learning modules</SectionTitle>
            <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
              {modules.map((module) => {
                const active = currentModule === module.module_number;
                const style = priorityStyle(module.priority);
                return (
                  <button key={module.module_number} onClick={() => setCurrentModule(module.module_number)} style={{ textAlign: "left", background: active ? theme.accentSoft : theme.surface, border: `1px solid ${active ? theme.accent : theme.border}`, borderRadius: 14, padding: "11px 12px", color: theme.text, cursor: "pointer", transition: "all 0.14s ease" }}>
                    <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 6 }}>
                      <span style={{ color: active ? theme.accent : theme.muted, fontSize: 12, fontWeight: 780, fontFamily: "JetBrains Mono, monospace" }}>{String(module.module_number).padStart(2, "0")}</span>
                      <span style={{ flex: 1, fontSize: 13, fontWeight: 740, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{module.title}</span>
                    </div>
                    <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                      <Pill color={style.color} background={style.background}>{module.priority || "MODULE"}</Pill>
                      {module.estimated_hours && <span style={{ color: theme.muted, fontSize: 11 }}>{module.estimated_hours}h</span>}
                    </div>
                  </button>
                );
              })}
            </div>
            <button onClick={() => handleSend("end session")} style={{ marginTop: 12, width: "100%", background: theme.dangerSoft, color: theme.danger, border: `1px solid ${theme.dangerSoft}`, borderRadius: 12, padding: "11px 14px", fontSize: 14, fontWeight: 740, cursor: "pointer" }}>
              End session and write vault notes
            </button>
          </div>
        )}
      </aside>

      <main style={{ flex: 1, minWidth: 0, display: "flex", flexDirection: "column", overflow: "hidden" }}>
        <header style={{ height: 70, padding: "0 26px", borderBottom: `1px solid ${theme.border}`, display: "flex", alignItems: "center", justifyContent: "space-between", gap: 18, background: theme.bg }}>
          <div style={{ minWidth: 0 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 4 }}>
              <h2 style={{ fontSize: 17, fontWeight: 790, margin: 0, letterSpacing: "-0.02em" }}>{studyPlan?.title || "Documentation learning session"}</h2>
              {sessionId && <Pill color={theme.success} background={theme.successSoft}>Active</Pill>}
            </div>
            <div style={{ color: theme.muted, fontSize: 13, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", maxWidth: 740 }}>
              {activeModule ? `Module ${String(currentModule).padStart(2, "0")} · ${activeModule.title}` : "Index a documentation source or resume a previous session."}
            </div>
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 8, flexShrink: 0 }}>
            {notesWritten && <Pill color={theme.success} background={theme.successSoft}>Notes saved</Pill>}
            {sessionId && <span style={{ color: theme.faint, fontSize: 12, fontFamily: "JetBrains Mono, monospace" }}>{sessionId.slice(0, 8)}</span>}
          </div>
        </header>

        <section onClick={() => inputRef.current?.focus()} style={{ flex: 1, overflowY: "auto", padding: "28px 30px" }}>
          {messages.length === 0 ? (
            <EmptyState theme={theme} />
          ) : (
            <div style={{ maxWidth: 920, margin: "0 auto", display: "flex", flexDirection: "column", gap: 18 }}>
              {messages.map((message, index) => {
                const isLast = index === messages.length - 1;
                if (message.role === "user") {
                  return (
                    <div key={index} style={{ display: "flex", justifyContent: "flex-end" }}>
                      <div style={{ maxWidth: "74%", background: theme.accent, color: "white", padding: "13px 15px", borderRadius: "18px 18px 5px 18px", fontSize: 14, lineHeight: 1.65, boxShadow: dark ? "none" : "0 8px 20px rgba(79,70,229,0.18)" }}>{message.content}</div>
                    </div>
                  );
                }

                if (message.role === "system") {
                  return (
                    <div key={index} style={{ display: "flex", justifyContent: "center" }}>
                      <div style={{ background: theme.warningSoft, color: theme.warning, borderRadius: 999, padding: "8px 12px", fontSize: 12, fontWeight: 680 }}>{message.content}</div>
                    </div>
                  );
                }

                if (message.role === "ai") {
                  return (
                    <div key={index} style={{ display: "flex", justifyContent: "flex-start" }}>
                      <div style={{ maxWidth: "82%", background: theme.surface, color: theme.text, border: `1px solid ${theme.border}`, boxShadow: theme.cardShadow, padding: 18, borderRadius: "18px 18px 18px 5px", fontSize: 14, lineHeight: 1.75 }}>
                        <div style={{ display: "flex", alignItems: "center", gap: 9, marginBottom: 12 }}>
                          <div style={{ width: 26, height: 26, borderRadius: 9, background: theme.accentSoft, color: theme.accent, display: "flex", alignItems: "center", justifyContent: "center", fontWeight: 850, fontSize: 13 }}>V</div>
                          <div style={{ fontSize: 13, fontWeight: 760, color: theme.text }}>VaultLearn</div>
                        </div>
                        <TypeWriter text={message.content || ""} theme={theme} active={message.typewrite && isLast} />

                        {message.citations?.length > 0 && (
                          <div style={{ marginTop: 16, display: "flex", flexWrap: "wrap", gap: 8 }}>
                            {[...new Set(message.citations)].slice(0, 5).map((citation, citationIndex) => {
                              const label = citation.split("#")[1] || citation.split("/").filter(Boolean).pop() || "Source";
                              return (
                                <a key={citation} href={citation} target="_blank" rel="noreferrer" style={{ fontSize: 12, color: theme.accent, background: theme.accentSoft, border: `1px solid ${theme.borderSoft}`, padding: "7px 10px", borderRadius: 999, textDecoration: "none", fontWeight: 740, maxWidth: 230, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                                  {citationIndex + 1}. {label}
                                </a>
                              );
                            })}
                          </div>
                        )}

                        {message.struggles && Object.keys(message.struggles).length > 0 && (
                          <div style={{ marginTop: 14, fontSize: 13, color: theme.warning, background: theme.warningSoft, padding: "10px 12px", borderRadius: 12, fontWeight: 700 }}>Struggle signal detected — added to review memory.</div>
                        )}
                      </div>
                    </div>
                  );
                }

                return null;
              })}

              {loading && (
                <div style={{ display: "flex", justifyContent: "flex-start" }}>
                  <div style={{ background: theme.surface, border: `1px solid ${theme.border}`, boxShadow: theme.cardShadow, padding: "14px 16px", borderRadius: "18px 18px 18px 5px", color: theme.muted, fontSize: 14 }}>Thinking through the documentation...</div>
                </div>
              )}
              <div ref={bottomRef} />
            </div>
          )}
        </section>

        <footer style={{ borderTop: `1px solid ${theme.border}`, background: theme.surface, padding: 18 }}>
          <div style={{ maxWidth: 920, margin: "0 auto", display: "flex", gap: 12, alignItems: "center", background: theme.bg, border: `1px solid ${theme.border}`, borderRadius: 18, padding: 10 }}>
            <input ref={inputRef} placeholder={sessionId ? "Ask about this documentation..." : "Index or resume a documentation session first..."} value={input} onChange={(event) => setInput(event.target.value)} onKeyDown={handleKeyDown} disabled={!sessionId || loading} style={{ flex: 1, minWidth: 0, background: "transparent", border: "none", color: theme.text, fontSize: 14, outline: "none", padding: "8px 8px" }} />
            <button onClick={() => handleSend()} disabled={!sessionId || loading || !input.trim()} style={{ background: !sessionId || loading || !input.trim() ? theme.surfaceSoft : theme.accent, color: !sessionId || loading || !input.trim() ? theme.muted : "white", border: "none", borderRadius: 13, padding: "10px 15px", fontSize: 14, fontWeight: 760, cursor: !sessionId || loading || !input.trim() ? "not-allowed" : "pointer" }}>Send</button>
          </div>
        </footer>
      </main>

      <aside className="vl-right-panel" style={{ width: 340, minWidth: 340, borderLeft: `1px solid ${theme.border}`, background: theme.bg, padding: 20, overflowY: "auto", display: "flex", flexDirection: "column", gap: 16 }}>
        <ActivityPanel events={progressEvents} theme={theme} />
        <SourcesPanel sources={latestSources} theme={theme} />
        <VaultPanel vaultFiles={vaultFiles} theme={theme} onOpen={(file) => window.open(`${API}/vault/${file}`, "_blank")} />
      </aside>
    </div>
  );
}
