import { useState, useRef, useEffect } from "react";
import ReactMarkdown from "react-markdown";

const API = import.meta.env.VITE_API_URL || "http://localhost:8001";

function TypeWriter({ text, speed = 8, G, DIM, DARK, BORD }) {
  const [displayed, setDisplayed] = useState("");
  const [done, setDone] = useState(false);
  const idx = useRef(0);

  useEffect(() => {
    setDisplayed("");
    setDone(false);
    idx.current = 0;
    const iv = setInterval(() => {
      if (idx.current < text.length) {
        setDisplayed(text.slice(0, idx.current + 1));
        idx.current++;
      } else {
        clearInterval(iv);
        setDone(true);
      }
    }, speed);
    return () => clearInterval(iv);
  }, [text]);

  const mdComponents = {
    a: ({ href, children }) => (
      <a href={href} target="_blank" rel="noreferrer"
        style={{ color: G, textDecoration: "underline", wordBreak: "break-all" }}>
        {children}
      </a>
    ),
    code: ({ children }) => (
      <code style={{ background: DARK, padding: "2px 8px", borderRadius: 2, fontSize: 13, color: G, fontFamily: "JetBrains Mono, monospace" }}>
        {children}
      </code>
    ),
    pre: ({ children }) => (
      <pre style={{ background: DARK, border: `1px solid ${BORD}`, padding: 16, borderRadius: 4, overflowX: "auto", marginTop: 10, marginBottom: 10, fontSize: 13, lineHeight: 1.7, fontFamily: "JetBrains Mono, monospace" }}>
        {children}
      </pre>
    ),
    p: ({ children }) => <p style={{ marginBottom: 12, lineHeight: 1.85 }}>{children}</p>,
    ul: ({ children }) => <ul style={{ paddingLeft: 22, marginBottom: 12 }}>{children}</ul>,
    ol: ({ children }) => <ol style={{ paddingLeft: 22, marginBottom: 12 }}>{children}</ol>,
    li: ({ children }) => <li style={{ marginBottom: 6, lineHeight: 1.75 }}>{children}</li>,
    strong: ({ children }) => <strong style={{ color: G, fontWeight: 700 }}>{children}</strong>,
    h1: ({ children }) => <h1 style={{ fontSize: 18, fontWeight: 700, marginBottom: 12, marginTop: 8, color: G }}>{children}</h1>,
    h2: ({ children }) => <h2 style={{ fontSize: 16, fontWeight: 700, marginBottom: 10, marginTop: 8, color: G }}>{children}</h2>,
    h3: ({ children }) => <h3 style={{ fontSize: 15, fontWeight: 600, marginBottom: 8, marginTop: 6, color: G }}>{children}</h3>,
    blockquote: ({ children }) => (
      <blockquote style={{ borderLeft: `3px solid ${BORD}`, paddingLeft: 14, color: DIM, margin: "10px 0", fontStyle: "italic" }}>
        {children}
      </blockquote>
    ),
  };

  if (done) {
    return <ReactMarkdown components={mdComponents}>{text}</ReactMarkdown>;
  }

  return (
    <span style={{ fontSize: 15, lineHeight: 1.85, whiteSpace: "pre-wrap" }}>
      {displayed}
      <span style={{ animation: "blink 0.8s infinite" }}>█</span>
    </span>
  );
}

function BootSequence({ onDone, G, DIM }) {
  const lines = [
    "VAULTLEARN v1.0.0 — Documentation Learning Agent",
    "Initializing RAG pipeline...",
    "Loading embedding model: all-MiniLM-L6-v2",
    "ChromaDB persistent client: READY",
    "LangGraph agent: COMPILED",
    "Obsidian vault: MOUNTED at ./vault",
    "System ready. Awaiting input.",
  ];
  const [shown, setShown] = useState(0);

  useEffect(() => {
    if (shown >= lines.length) { onDone(); return; }
    const t = setTimeout(() => setShown(s => s + 1), 300);
    return () => clearTimeout(t);
  }, [shown]);

  return (
    <div style={{ padding: 40, fontFamily: "JetBrains Mono, monospace", color: G, fontSize: 15, lineHeight: 2.4 }}>
      {lines.slice(0, shown).map((l, i) => (
        <div key={i}>
          <span style={{ color: DIM }}>[{String(i).padStart(2, "0")}] </span>
          <span>{l}</span>
          {i === shown - 1 && <span style={{ animation: "blink 0.8s infinite" }}>_</span>}
        </div>
      ))}
    </div>
  );
}

function Scanlines({ dark }) {
  if (!dark) return null;
  return (
    <div style={{
      position: "fixed", top: 0, left: 0, right: 0, bottom: 0,
      pointerEvents: "none", zIndex: 999,
      background: "repeating-linear-gradient(0deg, transparent, transparent 2px, rgba(0,0,0,0.05) 2px, rgba(0,0,0,0.05) 4px)"
    }} />
  );
}

export default function App() {
  const [dark, setDark] = useState(true);
  const [booted, setBooted] = useState(false);
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
  const bottomRef = useRef(null);
  const inputRef = useRef(null);

  const G    = dark ? "#00FF41" : "#1B5E20";
  const DIM  = dark ? "#00AA2A" : "#388E3C";
  const DARK = dark ? "#0A1A0A" : "#E8F5E9";
  const BG   = dark ? "#000000" : "#F1F8F1";
  const SURF = dark ? "#050E05" : "#FFFFFF";
  const BORD = dark ? "#1A2E1A" : "#C8E6C9";
  const MUTED= dark ? "#005500" : "#81C784";

  useEffect(() => { document.body.style.background = BG; }, [dark]);
  useEffect(() => { bottomRef.current?.scrollIntoView({ behavior: "smooth" }); }, [messages, loading]);

  const fetchVault = async () => {
    try {
      const r = await fetch(`${API}/vault`);
      const d = await r.json();
      setVaultFiles(d.files || []);
    } catch {}
  };

  useEffect(() => { if (booted) fetchVault(); }, [booted, notesWritten]);

  const handleSetup = async () => {
  if (!url.trim() || settingUp) return;
  setSettingUp(true);
  setMessages([]);
  setNotesWritten(false);

  const response = await fetch(`${API}/setup`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ url: url.trim() }),
  });

  const reader = response.body.getReader();
  const decoder = new TextDecoder();

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    const text = decoder.decode(value);
    const lines = text.split("\n").filter(l => l.startsWith("data: "));

    for (const line of lines) {
      const data = JSON.parse(line.replace("data: ", ""));

      if (data.type === "progress") {
  setMessages(p => {
    const filtered = p.filter(m => m.role !== "progress");
    return [...filtered, {
      role: "progress",
      content: `> [${data.current}/${data.total}] ${data.module} — ${data.page}`
    }];
  });
}

      if (data.type === "status") {
        setMessages(p => {
          const last = p[p.length - 1];
          if (last?.role === "system") {
            return [...p.slice(0, -1), { role: "system", content: `> ${data.message}` }];
          }
          return [...p, { role: "system", content: `> ${data.message}` }];
        });
      }

      if (data.type === "done") {
        setSessionId(data.session_id);
        setStudyPlan(data.study_plan);
        setCurrentModule(1);
        setMessages(p => [...p,
          { role: "system", content: `> SESSION: ${data.session_id}` },
          { role: "ai", content: `Index loaded. **${data.study_plan.modules.length} modules** ready.\n\nSelect a module and start asking questions.`, citations: [], typewrite: true }
        ]);
      }

      if (data.type === "error") {
        setMessages(p => [...p, { role: "system", content: `> ERROR: ${data.message}` }]);
      }
    }
  }

  setSettingUp(false);
};

  const handleSend = async (override) => {
    const text = override || input.trim();
    if (!text || !sessionId || loading) return;
    setInput("");
    setHistory(h => [text, ...h]);
    setHistIdx(-1);
    setMessages(p => [...p, { role: "user", content: text }]);
    setLoading(true);
    try {
      const r = await fetch(`${API}/session/${sessionId}/message`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: text }),
      });
      const d = await r.json();
      setMessages(p => [...p, {
        role: "ai",
        content: d.answer,
        citations: d.citations || [],
        struggles: d.struggle_signals || {},
        typewrite: true,
      }]);
      if (d.notes_written) { setNotesWritten(true); fetchVault(); }
    } catch {
      setMessages(p => [...p, { role: "system", content: "> ERROR: Request failed." }]);
    }
    setLoading(false);
  };

  const handleKeyDown = (e) => {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); handleSend(); }
    if (e.key === "ArrowUp") {
      e.preventDefault();
      const next = Math.min(histIdx + 1, history.length - 1);
      setHistIdx(next);
      setInput(history[next] || "");
    }
    if (e.key === "ArrowDown") {
      e.preventDefault();
      const next = Math.max(histIdx - 1, -1);
      setHistIdx(next);
      setInput(next === -1 ? "" : history[next]);
    }
  };

  const priorityColor = (p) => p === "RED" ? "#FF4444" : p === "YELLOW" ? "#FFAA00" : DIM;
  const activeModule = studyPlan?.modules?.find(m => m.module_number === currentModule);

  const globalCss = `
    @import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;700&display=swap');
    @keyframes blink { 0%,100%{opacity:1} 50%{opacity:0} }
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body { margin: 0; font-family: 'JetBrains Mono', monospace; }
    ::-webkit-scrollbar { width: 4px; }
    ::-webkit-scrollbar-thumb { background: ${BORD}; border-radius: 2px; }
    input::placeholder { color: ${MUTED}; opacity: 1; }
    @media (max-width: 768px) {
      .vl-app { flex-direction: column !important; }
      .vl-sidebar { width: 100% !important; min-width: unset !important; max-height: 42vh; border-right: none !important; border-bottom: 1px solid ${BORD} !important; }
    }
  `;

  if (!booted) return (
    <div style={{ background: BG, minHeight: "100vh" }}>
      <Scanlines dark={dark} />
      <style>{globalCss}</style>
      <BootSequence onDone={() => setBooted(true)} G={G} DIM={DIM} />
    </div>
  );

  return (
    <div className="vl-app" style={{ display: "flex", height: "100vh", background: BG, color: G, fontFamily: "JetBrains Mono, monospace", overflow: "hidden", position: "relative" }}>
      <Scanlines dark={dark} />
      <style>{globalCss}</style>

      {/* SIDEBAR */}
      <div className="vl-sidebar" style={{ width: 300, minWidth: 300, background: SURF, borderRight: `1px solid ${BORD}`, display: "flex", flexDirection: "column", padding: "20px 14px", gap: 20, overflowY: "auto" }}>

        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
          <div style={{ fontSize: 17, fontWeight: 700, color: G, letterSpacing: 3 }}>
            VAULT<span style={{ color: DIM }}>LEARN</span>
            <span style={{ animation: "blink 1s infinite", marginLeft: 3 }}>_</span>
          </div>
          <button
            onClick={() => setDark(d => !d)}
            style={{ background: "transparent", border: `1px solid ${BORD}`, color: DIM, fontFamily: "JetBrains Mono, monospace", fontSize: 10, padding: "4px 10px", cursor: "pointer", letterSpacing: 1 }}
          >
            {dark ? "LIGHT" : "DARK"}
          </button>
        </div>

        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          <div style={{ fontSize: 10, color: DIM, letterSpacing: "0.15em" }}>// TARGET URL</div>
          <input
            style={{ background: BG, border: `1px solid ${BORD}`, borderRadius: 2, color: G, fontFamily: "JetBrains Mono, monospace", fontSize: 12, padding: "10px 12px", outline: "none", width: "100%" }}
            placeholder="https://docs.example.com"
            value={url}
            onChange={e => setUrl(e.target.value)}
            onKeyDown={e => e.key === "Enter" && handleSetup()}
            onFocus={e => e.target.style.borderColor = G}
            onBlur={e => e.target.style.borderColor = BORD}
          />
          <button
            onClick={handleSetup}
            disabled={settingUp || !url.trim()}
            style={{ background: settingUp || !url.trim() ? "transparent" : DARK, border: `1px solid ${settingUp || !url.trim() ? BORD : G}`, borderRadius: 2, color: settingUp || !url.trim() ? MUTED : G, fontFamily: "JetBrains Mono, monospace", fontSize: 12, fontWeight: 700, padding: "10px", cursor: settingUp || !url.trim() ? "not-allowed" : "pointer", letterSpacing: 2 }}
          >
            {settingUp ? "LOADING..." : "{'>'} CONNECT"}
          </button>
        </div>

        {studyPlan && (
          <>
            <div>
              <div style={{ fontSize: 10, color: DIM, letterSpacing: "0.15em", marginBottom: 8 }}>// MODULES</div>
              {studyPlan.modules.map(m => (
                <div
                  key={m.module_number}
                  onClick={() => setCurrentModule(m.module_number)}
                  style={{ display: "flex", alignItems: "center", gap: 8, padding: "9px 10px", cursor: "pointer", marginBottom: 2, background: currentModule === m.module_number ? DARK : "transparent", borderLeft: `2px solid ${currentModule === m.module_number ? G : "transparent"}`, color: currentModule === m.module_number ? G : DIM, fontSize: 13, transition: "all 0.1s" }}
                >
                  <span style={{ color: MUTED, minWidth: 28, fontSize: 11 }}>[{String(m.module_number).padStart(2, "0")}]</span>
                  <span style={{ flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{m.title.toUpperCase()}</span>
                  <span style={{ fontSize: 9, color: priorityColor(m.priority), flexShrink: 0 }}>{m.priority}</span>
                </div>
              ))}
            </div>

            <button
              onClick={() => handleSend("end session")}
              style={{ background: "transparent", border: "1px solid #FF444466", borderRadius: 2, color: "#FF4444", fontFamily: "JetBrains Mono, monospace", fontSize: 12, padding: "9px", cursor: "pointer", letterSpacing: 1 }}
            >
              {'>'} END SESSION
            </button>
          </>
        )}

        {vaultFiles.length > 0 && (
          <div>
            <div style={{ fontSize: 10, color: DIM, letterSpacing: "0.15em", marginBottom: 8 }}>// VAULT NOTES</div>
            {vaultFiles.map(f => (
              <div
                key={f}
                onClick={() => window.open(`${API}/vault/${f}`, "_blank")}
                style={{ fontSize: 12, color: DIM, padding: "6px 8px", cursor: "pointer", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", borderLeft: "2px solid transparent", transition: "all 0.1s" }}
                onMouseEnter={e => { e.currentTarget.style.color = G; e.currentTarget.style.borderLeftColor = G; }}
                onMouseLeave={e => { e.currentTarget.style.color = DIM; e.currentTarget.style.borderLeftColor = "transparent"; }}
                title={f}
              >
                [NOTE] {f.replace(".md", "").toUpperCase()}
              </div>
            ))}
          </div>
        )}
      </div>

      {/* MAIN */}
      <div style={{ flex: 1, display: "flex", flexDirection: "column", overflow: "hidden" }}>

        {/* TOPBAR */}
        <div style={{ padding: "13px 24px", borderBottom: `1px solid ${BORD}`, display: "flex", alignItems: "center", gap: 16, fontSize: 13, flexWrap: "wrap" }}>
          <span style={{ color: DIM }}>SESSION:</span>
          <span style={{ color: G }}>{sessionId ? sessionId.split("-")[0].toUpperCase() : "NONE"}</span>
          <span style={{ color: BORD }}>|</span>
          <span style={{ color: DIM }}>MODULE:</span>
          <span style={{ color: G, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", maxWidth: 320 }}>
            {activeModule ? `[${String(currentModule).padStart(2, "0")}] ${activeModule.title.toUpperCase()}` : "—"}
          </span>
          {notesWritten && (
            <>
              <span style={{ color: BORD }}>|</span>
              <span style={{ color: "#00FF41", animation: "blink 2s infinite", fontSize: 12 }}>✓ NOTES SAVED</span>
            </>
          )}
        </div>

        {/* MESSAGES */}
        <div
          style={{ flex: 1, overflowY: "auto", padding: "28px 32px", display: "flex", flexDirection: "column", gap: 24 }}
          onClick={() => inputRef.current?.focus()}
        >
          {messages.length === 0 && (
            <div style={{ color: DIM, fontSize: 15, lineHeight: 2.4 }}>
              <div>VAULTLEARN TERMINAL v1.0</div>
              <div>━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━</div>
              <div style={{ marginTop: 10 }}>Paste a documentation URL in the sidebar.</div>
              <div>Ask questions about any module.</div>
              <div>Use ↑ ↓ for command history.</div>
              <div>Type "end session" to save vault notes.</div>
              <div style={{ marginTop: 16, animation: "blink 1s infinite" }}>█</div>
            </div>
          )}

          {messages.map((m, i) => (
            <div key={i}>
              {m.role === "user" && (
                <div style={{ fontSize: 15, lineHeight: 1.7 }}>
                  <span style={{ color: DIM, userSelect: "none" }}>root@vaultlearn:~$ </span>
                  <span style={{ color: G }}>{m.content}</span>
                </div>
              )}
              {m.role === "system" && (
                <div style={{ color: MUTED, fontSize: 12, letterSpacing: 1 }}>{m.content}</div>
              )}
              {m.role === "progress" && (
                <div style={{ color: MUTED, fontSize: 12, letterSpacing: 1, fontFamily: "JetBrains Mono, monospace" }}>
                  {m.content}
                </div>
              )}
              {m.role === "ai" && (
                <div style={{ borderLeft: `2px solid ${BORD}`, paddingLeft: 20, marginLeft: 10 }}>
                  <div style={{ fontSize: 10, color: MUTED, letterSpacing: "0.15em", marginBottom: 12 }}>// AGENT OUTPUT</div>
                  <div style={{ color: G, fontSize: 15, lineHeight: 1.85 }}>
                    <TypeWriter
                      text={m.content}
                      speed={m.typewrite && i === messages.length - 1 ? 6 : 0}
                      G={G} DIM={DIM} DARK={DARK} BORD={BORD}
                    />
                  </div>

                  {m.citations?.length > 0 && (
                    <div style={{ marginTop: 16, display: "flex", flexWrap: "wrap", gap: 8 }}>
                      <span style={{ fontSize: 10, color: MUTED, letterSpacing: "0.1em", width: "100%", marginBottom: 4 }}>// SOURCES</span>
                      {[...new Set(m.citations)].slice(0, 5).map((c, j) => {
                        const label = c.split("#")[1]?.toUpperCase() || c.split("/").filter(Boolean).pop()?.toUpperCase() || "SRC";
                        return (
                          <a key={j} href={c} target="_blank" rel="noreferrer"
                            style={{ fontSize: 12, color: DIM, border: `1px solid ${BORD}`, padding: "4px 12px", textDecoration: "none", letterSpacing: 1, transition: "all 0.1s" }}
                            onMouseEnter={e => { e.currentTarget.style.color = G; e.currentTarget.style.borderColor = G; }}
                            onMouseLeave={e => { e.currentTarget.style.color = DIM; e.currentTarget.style.borderColor = BORD; }}
                          >
                            [{j + 1}] {label.slice(0, 35)}
                          </a>
                        );
                      })}
                    </div>
                  )}

                  {m.struggles && Object.keys(m.struggles).length > 0 && (
                    <div style={{ marginTop: 12, fontSize: 13, color: "#FFAA00", letterSpacing: 1, padding: "8px 12px", border: "1px solid #FFAA0033", display: "inline-block" }}>
                      ⚠ STRUGGLE FLAGGED — added to review schedule
                    </div>
                  )}
                </div>
              )}
            </div>
          ))}

          {loading && (
            <div style={{ borderLeft: `2px solid ${BORD}`, paddingLeft: 20, marginLeft: 10 }}>
              <div style={{ fontSize: 10, color: MUTED, letterSpacing: "0.15em", marginBottom: 12 }}>// AGENT OUTPUT</div>
              <div style={{ color: DIM, fontSize: 15 }}>
                PROCESSING<span style={{ animation: "blink 0.4s infinite" }}>...</span>
              </div>
            </div>
          )}
          <div ref={bottomRef} />
        </div>

        {/* INPUT */}
        <div style={{ padding: "16px 24px", borderTop: `1px solid ${BORD}`, display: "flex", alignItems: "center", gap: 12, background: SURF }}>
          <span style={{ color: DIM, fontSize: 15, whiteSpace: "nowrap", userSelect: "none" }}>root@vaultlearn:~$</span>
          <input
            ref={inputRef}
            style={{ flex: 1, background: "transparent", border: "none", color: G, fontFamily: "JetBrains Mono, monospace", fontSize: 15, outline: "none", caretColor: G }}
            placeholder={sessionId ? "type your question..." : "connect to a session first..."}
            value={input}
            onChange={e => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            disabled={!sessionId || loading}
            autoFocus
          />
          {loading && (
            <span style={{ color: MUTED, fontSize: 12, animation: "blink 0.5s infinite", whiteSpace: "nowrap" }}>THINKING</span>
          )}
        </div>
      </div>
    </div>
  );
}