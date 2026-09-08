"use client";
import { useState, useRef, useEffect } from "react";
import { Brain, Bug, Eye, Send, Loader2, Terminal, FileCode, GitBranch } from "lucide-react";
import { clsx } from "clsx";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

const BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

type AgentType = "qa" | "debug" | "review";
interface RetrievalTrace { anchors: string[]; intent: string; has_commits: boolean; trace: any[]; }
interface Message {
  role: "user" | "assistant";
  content: string;
  agent?: AgentType;
  retrieval?: RetrievalTrace;
  loading?: boolean;
}

const AGENTS: { id: AgentType; label: string; icon: React.ElementType; desc: string; accent: string }[] = [
  { id: "qa", label: "Ask", icon: Brain, desc: "Ask anything about the codebase", accent: "cyan" },
  { id: "debug", label: "Debug", icon: Bug, desc: "Paste an error, get root cause", accent: "red" },
  { id: "review", label: "Review", icon: Eye, desc: "Review code for quality issues", accent: "purple" },
];

const STARTERS: Record<AgentType, string[]> = {
  qa: ["What are the main entry points?", "How does authentication work?", "What changed in the last 10 commits?", "List all API endpoints"],
  debug: ["TypeError: Cannot read property of undefined", "CORS error on API call", "ModuleNotFoundError at startup", "Async function never resolves"],
  review: ["Review the main app file", "Check for security vulnerabilities", "Identify performance bottlenecks", "Find missing error handling"],
};

async function* streamChat(repoId: string, message: string, agentType: string) {
  const res = await fetch(`${BASE}/agents/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ repo_id: repoId, message, agent_type: agentType }),
  });
  const reader = res.body!.getReader();
  const dec = new TextDecoder();
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    for (const line of dec.decode(value).split("\n")) {
      if (line.startsWith("data: ")) {
        try { yield JSON.parse(line.slice(6)); } catch {}
      }
    }
  }
}

export default function ChatPanel({ repoId }: { repoId: string }) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [agent, setAgent] = useState<AgentType>("qa");
  const [streaming, setStreaming] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => { bottomRef.current?.scrollIntoView({ behavior: "smooth" }); }, [messages]);

  const send = async (text?: string) => {
    const msg = text || input.trim();
    if (!msg || streaming) return;
    setInput("");
    setMessages((m) => [...m, { role: "user", content: msg, agent }]);
    setStreaming(true);
    const placeholder: Message = { role: "assistant", content: "", agent, loading: true };
    setMessages((m) => [...m, placeholder]);

    try {
      for await (const event of streamChat(repoId, msg, agent)) {
        if (event.event === "retrieval_done") {
          setMessages((m) => [
            ...m.slice(0, -1),
            { ...placeholder, retrieval: { anchors: event.anchors || [], intent: event.intent || "semantic", has_commits: event.has_commits || false, trace: event.trace } },
          ]);
        } else if (event.event === "answer" || event.content) {
          setMessages((m) => [
            ...m.slice(0, -1),
            { ...placeholder, content: event.content, loading: false, retrieval: m[m.length - 1].retrieval },
          ]);
        }
      }
    } catch (e: any) {
      setMessages((m) => [...m.slice(0, -1), { ...placeholder, content: `Error: ${e.message}`, loading: false }]);
    }
    setStreaming(false);
  };

  return (
    <div className="h-full flex">
      {/* Sidebar */}
      <div className="w-52 border-r border-synapse-border p-4 flex flex-col gap-2 bg-synapse-surface/40 shrink-0">
        <p className="text-[10px] font-mono text-synapse-muted mb-1 uppercase tracking-widest">Mode</p>
        {AGENTS.map(({ id, label, icon: Icon, desc, accent }) => (
          <button
            key={id}
            onClick={() => setAgent(id)}
            className={clsx(
              "text-left p-3 rounded-lg border transition-all",
              agent === id
                ? `border-${accent}-400/40 bg-${accent}-400/10`
                : "border-synapse-border hover:border-synapse-border/80"
            )}
          >
            <div className={clsx("flex items-center gap-2 text-sm font-mono font-medium", agent === id ? `text-${accent}-400` : "text-synapse-muted")}>
              <Icon className="w-3.5 h-3.5" /> {label}
            </div>
            <p className="text-[11px] text-synapse-muted mt-1 leading-snug">{desc}</p>
          </button>
        ))}

        <div className="mt-4 border-t border-synapse-border pt-3">
          <p className="text-[10px] font-mono text-synapse-muted mb-2 uppercase tracking-widest">Quick Start</p>
          {STARTERS[agent].map((s) => (
            <button key={s} onClick={() => send(s)}
              className="block w-full text-left text-[11px] text-synapse-muted/70 hover:text-synapse-text font-mono py-1.5 px-1.5 rounded hover:bg-synapse-border/30 transition-all leading-snug mb-0.5">
              {s}
            </button>
          ))}
        </div>
      </div>

      {/* Chat */}
      <div className="flex-1 flex flex-col min-w-0">
        <div className="flex-1 overflow-y-auto p-6 space-y-5">
          {messages.length === 0 && (
            <div className="flex flex-col items-center justify-center h-full text-center opacity-50">
              <Terminal className="w-10 h-10 text-synapse-border mb-3" />
              <p className="text-synapse-muted font-mono text-sm">Ask anything about the codebase.</p>
              <p className="text-synapse-muted/60 text-xs mt-1">Context retrieved from code + call graph.</p>
            </div>
          )}

          {messages.map((m, i) => (
            <div key={i} className={clsx("flex", m.role === "user" ? "justify-end" : "justify-start")}>
              {m.role === "assistant" && (
                <div className="w-6 h-6 rounded-full bg-synapse-cyan/10 border border-synapse-cyan/30 flex items-center justify-center mr-2.5 mt-1 shrink-0">
                  <Brain className="w-3 h-3 text-synapse-cyan" />
                </div>
              )}
              <div className="max-w-2xl min-w-0">
                {/* Retrieval trace badge */}
                {m.role === "assistant" && m.retrieval && (
                  <div className="flex flex-wrap items-center gap-1.5 mb-2">
                    <span className={`text-[10px] font-mono px-1.5 py-0.5 rounded border ${
                      m.retrieval.intent === "structural" ? "text-synapse-green border-synapse-green/30 bg-synapse-green/10" :
                      m.retrieval.intent === "historical" ? "text-yellow-400 border-yellow-400/30 bg-yellow-400/10" :
                      "text-synapse-cyan border-synapse-cyan/30 bg-synapse-cyan/10"
                    }`}>{m.retrieval.intent}</span>
                    {m.retrieval.anchors.slice(0, 3).map((a) => (
                      <span key={a} className="flex items-center gap-1 px-2 py-0.5 rounded-full bg-synapse-purple/10 border border-synapse-purple/20 text-[10px] font-mono text-synapse-purple">
                        <FileCode className="w-2.5 h-2.5" /> {a}
                      </span>
                    ))}
                    {m.retrieval.has_commits && (
                      <span className="flex items-center gap-1 px-2 py-0.5 rounded-full bg-yellow-400/10 border border-yellow-400/20 text-[10px] font-mono text-yellow-400">
                        <GitBranch className="w-2.5 h-2.5" /> git history
                      </span>
                    )}
                  </div>
                )}
                <div className={clsx(
                  "rounded-xl px-4 py-3 text-sm leading-relaxed",
                  m.role === "user"
                    ? "bg-synapse-cyan/10 border border-synapse-cyan/20 text-synapse-text font-mono"
                    : "bg-synapse-surface border border-synapse-border text-synapse-text"
                )}>
                  {m.role === "assistant" ? (
                    m.loading && !m.content
                      ? <div className="flex items-center gap-2 text-synapse-muted text-xs font-mono">
                          <Loader2 className="w-3 h-3 animate-spin text-synapse-cyan" />
                          {m.retrieval ? "Generating answer..." : "Retrieving context..."}
                        </div>
                      : <div className="prose prose-invert prose-sm max-w-none prose-code:text-synapse-cyan prose-code:font-mono prose-pre:bg-synapse-bg prose-pre:border prose-pre:border-synapse-border">
                          <ReactMarkdown remarkPlugins={[remarkGfm]}>{m.content}</ReactMarkdown>
                        </div>
                  ) : m.content}
                </div>
              </div>
            </div>
          ))}
          <div ref={bottomRef} />
        </div>

        {/* Input */}
        <div className="border-t border-synapse-border p-4">
          <div className="flex gap-3 items-end bg-synapse-surface border border-synapse-border rounded-xl px-4 py-3 focus-within:border-synapse-cyan/40 transition-colors">
            <textarea
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); } }}
              placeholder={agent === "qa" ? "Ask about the codebase..." : agent === "debug" ? "Paste error or describe the bug..." : "What should I review?"}
              rows={1}
              className="flex-1 bg-transparent text-synapse-text font-mono text-sm resize-none focus:outline-none placeholder:text-synapse-muted/50 max-h-32"
            />
            <button onClick={() => send()} disabled={!input.trim() || streaming}
              className="p-2 rounded-lg bg-synapse-cyan/10 border border-synapse-cyan/30 text-synapse-cyan hover:bg-synapse-cyan/20 transition-all disabled:opacity-30 shrink-0">
              {streaming ? <Loader2 className="w-4 h-4 animate-spin" /> : <Send className="w-4 h-4" />}
            </button>
          </div>
          <p className="text-[10px] text-synapse-muted/40 font-mono mt-2 text-center">Enter · Shift+Enter for newline</p>
        </div>
      </div>
    </div>
  );
}
