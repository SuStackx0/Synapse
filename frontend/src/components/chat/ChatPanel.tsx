"use client";
import { useState, useRef, useEffect } from "react";
import { streamChat } from "@/lib/api";
import { Brain, Bug, Eye, Send, Loader2, Terminal } from "lucide-react";
import { clsx } from "clsx";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

type AgentType = "qa" | "debug" | "review";
interface Message { role: "user" | "assistant"; content: string; agent?: AgentType; }

const AGENTS: { id: AgentType; label: string; icon: React.ElementType; desc: string; color: string }[] = [
  { id: "qa", label: "Ask", icon: Brain, desc: "Ask anything about the codebase", color: "synapse-cyan" },
  { id: "debug", label: "Debug", icon: Bug, desc: "Paste an error, get root cause", color: "red-400" },
  { id: "review", label: "Review", icon: Eye, desc: "Review code quality", color: "synapse-purple" },
];

const STARTERS: Record<AgentType, string[]> = {
  qa: [
    "What are the main entry points of this project?",
    "How does authentication work?",
    "What changed in the last 10 commits?",
    "List all API endpoints defined",
  ],
  debug: [
    "TypeError: Cannot read properties of undefined",
    "KeyError in Python dict access",
    "CORS error on API call",
    "ModuleNotFoundError at startup",
  ],
  review: [
    "Review the main application file",
    "Check for security vulnerabilities",
    "Identify performance bottlenecks",
    "Look for missing error handling",
  ],
};

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
    const userMsg: Message = { role: "user", content: msg, agent };
    setMessages((m) => [...m, userMsg]);
    setStreaming(true);

    let reply = "";
    const placeholder: Message = { role: "assistant", content: "", agent };
    setMessages((m) => [...m, placeholder]);

    try {
      for await (const chunk of streamChat(repoId, msg, agent)) {
        reply = chunk.content;
        setMessages((m) => [...m.slice(0, -1), { ...placeholder, content: reply }]);
      }
    } catch (e: any) {
      setMessages((m) => [...m.slice(0, -1), { ...placeholder, content: `Error: ${e.message}` }]);
    }
    setStreaming(false);
  };

  return (
    <div className="h-full flex">
      {/* Sidebar: agent selector */}
      <div className="w-52 border-r border-synapse-border p-4 flex flex-col gap-2 bg-synapse-surface/50">
        <p className="text-xs font-mono text-synapse-muted mb-2 uppercase tracking-wider">Mode</p>
        {AGENTS.map(({ id, label, icon: Icon, desc, color }) => (
          <button
            key={id}
            onClick={() => setAgent(id)}
            className={clsx(
              "text-left p-3 rounded-lg border transition-all",
              agent === id
                ? `border-${color}/40 bg-${color}/10`
                : "border-synapse-border hover:border-synapse-border/80 bg-transparent"
            )}
          >
            <div className={clsx("flex items-center gap-2 text-sm font-mono", agent === id ? `text-${color}` : "text-synapse-muted")}>
              <Icon className="w-4 h-4" />
              {label}
            </div>
            <p className="text-xs text-synapse-muted mt-1 leading-tight">{desc}</p>
          </button>
        ))}

        <div className="mt-4 border-t border-synapse-border pt-4">
          <p className="text-xs font-mono text-synapse-muted mb-2 uppercase tracking-wider">Starters</p>
          <div className="flex flex-col gap-1.5">
            {STARTERS[agent].map((s) => (
              <button
                key={s}
                onClick={() => send(s)}
                className="text-left text-xs text-synapse-muted/70 hover:text-synapse-text font-mono leading-snug p-1.5 rounded hover:bg-synapse-border/30 transition-all"
              >
                {s}
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* Chat area */}
      <div className="flex-1 flex flex-col">
        {/* Messages */}
        <div className="flex-1 overflow-y-auto p-6 space-y-5">
          {messages.length === 0 && (
            <div className="flex flex-col items-center justify-center h-full text-center">
              <Terminal className="w-12 h-12 text-synapse-border mb-4" />
              <p className="text-synapse-muted font-mono text-sm">Select a mode and start asking.</p>
              <p className="text-synapse-muted/50 text-xs mt-1">Context is retrieved from the indexed codebase.</p>
            </div>
          )}
          {messages.map((m, i) => (
            <div key={i} className={clsx("flex", m.role === "user" ? "justify-end" : "justify-start")}>
              {m.role === "assistant" && (
                <div className="w-7 h-7 rounded-full bg-synapse-cyan/10 border border-synapse-cyan/30 flex items-center justify-center mr-3 mt-1 flex-shrink-0">
                  <Brain className="w-3.5 h-3.5 text-synapse-cyan" />
                </div>
              )}
              <div className={clsx(
                "max-w-2xl rounded-xl px-4 py-3 text-sm leading-relaxed",
                m.role === "user"
                  ? "bg-synapse-cyan/10 border border-synapse-cyan/20 text-synapse-text font-mono"
                  : "bg-synapse-surface border border-synapse-border text-synapse-text"
              )}>
                {m.role === "assistant" ? (
                  <div className="prose prose-invert prose-sm max-w-none prose-code:text-synapse-cyan prose-code:font-mono prose-pre:bg-synapse-bg">
                    <ReactMarkdown remarkPlugins={[remarkGfm]}>{m.content || "▊"}</ReactMarkdown>
                  </div>
                ) : m.content}
                {m.role === "assistant" && streaming && i === messages.length - 1 && !m.content && (
                  <Loader2 className="w-4 h-4 text-synapse-cyan animate-spin" />
                )}
              </div>
            </div>
          ))}
          <div ref={bottomRef} />
        </div>

        {/* Input */}
        <div className="border-t border-synapse-border p-4">
          <div className="flex gap-3 items-end bg-synapse-surface border border-synapse-border rounded-xl p-3 focus-within:border-synapse-cyan/40 transition-colors">
            <textarea
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); } }}
              placeholder={`${agent === "qa" ? "Ask about the codebase..." : agent === "debug" ? "Paste error or describe the bug..." : "What should I review?"}`}
              rows={1}
              className="flex-1 bg-transparent text-synapse-text font-mono text-sm resize-none focus:outline-none placeholder:text-synapse-muted/50 max-h-32"
              style={{ fieldSizing: "content" } as any}
            />
            <button
              onClick={() => send()}
              disabled={!input.trim() || streaming}
              className="p-2 rounded-lg bg-synapse-cyan/10 border border-synapse-cyan/30 text-synapse-cyan hover:bg-synapse-cyan/20 transition-all disabled:opacity-30"
            >
              {streaming ? <Loader2 className="w-4 h-4 animate-spin" /> : <Send className="w-4 h-4" />}
            </button>
          </div>
          <p className="text-xs text-synapse-muted/40 font-mono mt-2 text-center">Enter to send · Shift+Enter for newline</p>
        </div>
      </div>
    </div>
  );
}
