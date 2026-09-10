"use client";
import { useState, useRef, useEffect } from "react";
import {
  Brain, Send, Loader2, Terminal, FileCode, GitBranch, CheckCircle2,
  XCircle, FilePlus2, FileEdit, Sparkles, ChevronDown, ChevronRight,
  HelpCircle, Plus,
} from "lucide-react";
import { clsx } from "clsx";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { getSessionMessages, ChatMessageInfo } from "@/lib/api";

const BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

interface RetrievalTrace { anchors: string[]; intent: string; has_commits: boolean; coverage: string; trace: any[]; }
interface PlanFile { rel_path: string; op: string; intent: string; }
interface WriteResult { rel_path: string; op: string; ok: boolean; applied: boolean; lines: number; added: number; removed: number; diff: string; error?: string; }
interface WriteState {
  placementDir?: string;
  exemplars?: string[];
  plan?: PlanFile[];
  planSummary?: string;
  writingPath?: string;
  results: Record<string, WriteResult>;
}
interface ActivityStep { id: string; label: string; status: "active" | "done" | "error"; }
interface Message {
  role: "user" | "assistant";
  content: string;
  mode?: "read" | "write";
  retrieval?: RetrievalTrace;
  write?: WriteState;
  loading?: boolean;
  activity?: ActivityStep[];
  isClarifying?: boolean;
}

const STARTERS = [
  "What are the main entry points?",
  "How does authentication work?",
  "List all API endpoints",
  "TypeError: Cannot read property of undefined",
  "Review the main app file for security issues",
  "Implement rate limiting on the login endpoint",
];

async function* streamChat(repoId: string, message: string, sessionId: string | null) {
  const res = await fetch(`${BASE}/agents/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ repo_id: repoId, message, session_id: sessionId }),
  });
  const reader = res.body!.getReader();
  const dec = new TextDecoder();
  let buf = "";
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buf += dec.decode(value, { stream: true });
    const lines = buf.split("\n");
    buf = lines.pop() || "";
    for (const line of lines) {
      if (line.startsWith("data: ")) {
        try { yield JSON.parse(line.slice(6)); } catch {}
      }
    }
  }
}

function opIcon(op: string, ok: boolean) {
  if (!ok) return <XCircle className="w-3.5 h-3.5 text-red-400" />;
  return op === "create"
    ? <FilePlus2 className="w-3.5 h-3.5 text-synapse-green" />
    : <FileEdit className="w-3.5 h-3.5 text-synapse-cyan" />;
}

function FileRow({ file, result }: { file: PlanFile; result?: WriteResult }) {
  const [open, setOpen] = useState(false);
  const pending = !result;
  return (
    <div className="border border-synapse-border rounded-lg overflow-hidden">
      <button
        onClick={() => result?.diff && setOpen((o) => !o)}
        className={clsx(
          "w-full flex items-center gap-2.5 px-3 py-2 text-left transition-colors",
          result?.diff ? "hover:bg-synapse-border/20 cursor-pointer" : "cursor-default"
        )}
      >
        {pending ? (
          <Loader2 className="w-3.5 h-3.5 text-synapse-cyan animate-spin shrink-0" />
        ) : (
          opIcon(file.op, result.ok)
        )}
        <span className="font-mono text-xs text-synapse-text truncate flex-1">{file.rel_path}</span>
        {result && result.ok && (
          <span className="text-[10px] font-mono shrink-0">
            <span className="text-synapse-green">+{result.added}</span>{" "}
            <span className="text-red-400/80">-{result.removed}</span>
          </span>
        )}
        {result && !result.ok && (
          <span className="text-[10px] font-mono text-red-400 shrink-0 max-w-[160px] truncate">{result.error}</span>
        )}
        {result?.diff && (open ? <ChevronDown className="w-3 h-3 text-synapse-muted shrink-0" /> : <ChevronRight className="w-3 h-3 text-synapse-muted shrink-0" />)}
      </button>
      <p className="px-3 pb-2 -mt-0.5 text-[11px] text-synapse-muted font-mono truncate">{file.intent}</p>
      {open && result?.diff && (
        <pre className="text-[10px] font-mono leading-relaxed px-3 py-2 bg-synapse-bg border-t border-synapse-border overflow-x-auto max-h-64 overflow-y-auto">
          {result.diff.split("\n").map((l, i) => (
            <div key={i} className={clsx(
              l.startsWith("+") && !l.startsWith("+++") ? "text-synapse-green" :
              l.startsWith("-") && !l.startsWith("---") ? "text-red-400" :
              "text-synapse-muted"
            )}>{l || " "}</div>
          ))}
        </pre>
      )}
    </div>
  );
}

function ActivityFeed({ activity }: { activity: ActivityStep[] }) {
  if (!activity.length) return null;
  return (
    <div className="space-y-1.5 mb-2.5">
      {activity.map((a, i) => (
        <div key={a.id} className="flex items-start gap-2 text-xs font-mono">
          <span className="mt-0.5 shrink-0">
            {a.status === "active" && <Loader2 className="w-3 h-3 animate-spin text-synapse-cyan" />}
            {a.status === "done" && <CheckCircle2 className="w-3 h-3 text-synapse-green" />}
            {a.status === "error" && <XCircle className="w-3 h-3 text-red-400" />}
          </span>
          <span className={clsx(
            a.status === "done" ? "text-synapse-muted/70" :
            a.status === "error" ? "text-red-400/90" : "text-synapse-text"
          )}>{a.label}</span>
        </div>
      ))}
    </div>
  );
}

function WritePanel({ w }: { w: WriteState }) {
  return (
    <div className="mt-3 space-y-2.5 border border-synapse-purple/20 bg-synapse-purple/[0.03] rounded-xl p-3.5">
      <div className="flex items-center gap-2 text-[11px] font-mono text-synapse-purple">
        <Sparkles className="w-3.5 h-3.5" />
        <span>IMPLEMENT</span>
        {w.placementDir !== undefined && (
          <span className="text-synapse-muted">
            · placement <span className="text-synapse-text">{w.placementDir || "repo root"}</span>
          </span>
        )}
      </div>
      {!!w.exemplars?.length && (
        <div className="flex flex-wrap gap-1.5">
          {w.exemplars.map((e) => (
            <span key={e} className="flex items-center gap-1 px-2 py-0.5 rounded-full bg-synapse-border/30 border border-synapse-border text-[10px] font-mono text-synapse-muted">
              <FileCode className="w-2.5 h-2.5" /> {e}
            </span>
          ))}
        </div>
      )}
      {!!w.plan?.length && (
        <div className="space-y-1.5 pt-1">
          {w.plan.map((f) => (
            <FileRow key={f.rel_path} file={f} result={w.results[f.rel_path]} />
          ))}
        </div>
      )}
    </div>
  );
}

function messagesFromHistory(rows: ChatMessageInfo[]): Message[] {
  return rows.map((r) => {
    if (r.role === "user") return { role: "user", content: r.content };
    const meta = r.meta || {};
    const msg: Message = { role: "assistant", content: r.content, mode: meta.mode, isClarifying: !!meta.is_clarifying };
    if (meta.retrieval) {
      msg.retrieval = {
        anchors: meta.retrieval.anchors || [], intent: meta.retrieval.intent || "semantic",
        has_commits: meta.retrieval.has_commits || false, coverage: meta.retrieval.coverage || "",
        trace: meta.retrieval.trace || [],
      };
    }
    if (meta.write_results) {
      const results: Record<string, WriteResult> = {};
      for (const wr of meta.write_results) results[wr.rel_path] = wr;
      msg.write = {
        results,
        placementDir: meta.placement_dir,
        plan: meta.write_results.map((wr: WriteResult) => ({ rel_path: wr.rel_path, op: wr.op, intent: "" })),
        planSummary: meta.plan_summary,
      };
    }
    return msg;
  });
}

export default function ChatPanel({ repoId }: { repoId: string }) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [hydrated, setHydrated] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);

  const storageKey = `synapse_session_${repoId}`;

  useEffect(() => {
    let cancelled = false;
    (async () => {
      const saved = typeof window !== "undefined" ? localStorage.getItem(storageKey) : null;
      if (saved) {
        try {
          const rows = await getSessionMessages(saved);
          if (!cancelled) {
            setSessionId(saved);
            setMessages(messagesFromHistory(rows));
          }
        } catch {
          localStorage.removeItem(storageKey);
        }
      }
      if (!cancelled) setHydrated(true);
    })();
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [repoId]);

  useEffect(() => { bottomRef.current?.scrollIntoView({ behavior: "smooth" }); }, [messages]);

  const startNewChat = () => {
    localStorage.removeItem(storageKey);
    setSessionId(null);
    setMessages([]);
  };

  const send = async (text?: string) => {
    const msg = text || input.trim();
    if (!msg || streaming) return;
    setInput("");
    setMessages((m) => [...m, { role: "user", content: msg }]);
    setStreaming(true);
    const placeholder: Message = { role: "assistant", content: "", loading: true, activity: [] };
    setMessages((m) => [...m, placeholder]);

    const update = (fn: (m: Message) => Message) =>
      setMessages((m) => [...m.slice(0, -1), fn(m[m.length - 1])]);

    // Live, Claude-Code-style step trail: each call either updates an existing
    // line (by id) in place or appends a new one, auto-completing the previous
    // generic step when a new one starts.
    const pushActivity = (id: string, label: string, status: ActivityStep["status"] = "active") => {
      update((m) => {
        const list = m.activity ? [...m.activity] : [];
        const idx = list.findIndex((a) => a.id === id);
        if (idx >= 0) {
          list[idx] = { ...list[idx], label, status };
        } else {
          for (let j = 0; j < list.length; j++) {
            if (list[j].status === "active" && !list[j].id.startsWith("file:") && list[j].id !== "clarify") {
              list[j] = { ...list[j], status: "done" };
            }
          }
          list.push({ id, label, status });
        }
        return { ...m, activity: list };
      });
    };

    try {
      const stepLabels: Record<string, string> = {
        routing: "Classifying your request",
        retrieving: "Searching the code graph",
        read: "Searching the code graph",
        write: "Preparing to implement",
        planning: "Planning the change",
        coding: "Generating code",
        applying: "Applying changes to disk",
        clarifying: "Waiting on a clarifying question",
      };
      for await (const event of streamChat(repoId, msg, sessionId)) {
        if (event.event === "session") {
          if (event.session_id && event.session_id !== sessionId) {
            setSessionId(event.session_id);
            localStorage.setItem(storageKey, event.session_id);
          }
        } else if (event.event === "step") {
          pushActivity(`step:${event.stage}`, stepLabels[event.stage] || event.stage);
        } else if (event.event === "mode") {
          update((m) => ({ ...m, mode: event.mode }));
        } else if (event.event === "context_ready") {
          const dir = event.placement_dir || "repo root";
          const n = event.exemplars?.length || 0;
          pushActivity("context_ready", `Found placement — \`${dir}\`${n ? `, ${n} exemplar file(s)` : ""}`, "done");
          update((m) => ({
            ...m,
            write: { results: {}, ...m.write, placementDir: event.placement_dir, exemplars: event.exemplars },
          }));
        } else if (event.event === "clarify") {
          pushActivity("clarify", "Needs your input", "active");
          update((m) => ({ ...m, isClarifying: true }));
        } else if (event.event === "plan_ready") {
          pushActivity("plan_ready", `Plan ready — ${event.files?.length || 0} file(s)`, "done");
          update((m) => ({
            ...m,
            write: { results: {}, ...m.write, plan: event.files, planSummary: event.summary },
          }));
        } else if (event.event === "writing_file") {
          pushActivity(`file:${event.rel_path}`, `Writing \`${event.rel_path}\``, "active");
          update((m) => ({
            ...m,
            write: { results: {}, ...m.write, writingPath: event.rel_path },
          }));
        } else if (event.event === "file_written") {
          pushActivity(
            `file:${event.rel_path}`,
            event.ok ? `\`${event.rel_path}\` written (+${event.added}/-${event.removed})` : `\`${event.rel_path}\` failed — ${event.error}`,
            event.ok ? "done" : "error"
          );
          update((m) => ({
            ...m,
            write: {
              ...(m.write || { results: {} }),
              results: { ...(m.write?.results || {}), [event.rel_path]: event },
            },
          }));
        } else if (event.event === "retrieval_done") {
          pushActivity("retrieval_done", `Context retrieved — ${event.intent}, coverage ${event.coverage}`, "done");
          update((m) => ({ ...m, retrieval: { anchors: event.anchors || [], intent: event.intent || "semantic", has_commits: event.has_commits || false, coverage: event.coverage || "", trace: event.trace } }));
        } else if (event.event === "answer") {
          update((m) => {
            const list = (m.activity || []).map((a) =>
              a.status === "active" && a.id !== "clarify" ? { ...a, status: "done" as const } : a
            );
            return { ...m, content: event.content, loading: false, activity: list };
          });
        }
      }
    } catch (e: any) {
      update((m) => ({ ...m, content: `Error: ${e.message}`, loading: false }));
    }
    setStreaming(false);
  };

  return (
    <div className="h-full flex flex-col">
      {messages.length > 0 && (
        <div className="flex items-center justify-end px-4 py-2 border-b border-synapse-border shrink-0">
          <button
            onClick={startNewChat}
            className="flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-synapse-muted hover:text-synapse-text hover:bg-synapse-border/30 text-xs font-mono transition-all"
          >
            <Plus className="w-3 h-3" /> New chat
          </button>
        </div>
      )}
      <div className="flex-1 overflow-y-auto p-6 space-y-5">
        {hydrated && messages.length === 0 && (
          <div className="h-full flex flex-col items-center justify-center text-center">
            <Terminal className="w-10 h-10 text-synapse-border mb-3" />
            <p className="text-synapse-muted font-mono text-sm">Ask, debug, review, or implement — just say what you need.</p>
            <p className="text-synapse-muted/60 text-xs mt-1 mb-6">Context retrieved from code + call graph. Code changes are graph-planned and written to disk.</p>
            <div className="flex flex-wrap justify-center gap-2 max-w-xl">
              {STARTERS.map((s) => (
                <button
                  key={s}
                  onClick={() => send(s)}
                  className="px-3 py-1.5 rounded-full border border-synapse-border text-synapse-muted hover:text-synapse-text hover:border-synapse-cyan/40 text-xs font-mono transition-all"
                >
                  {s}
                </button>
              ))}
            </div>
          </div>
        )}

        {messages.map((m, i) => (
          <div key={i} className={clsx("flex", m.role === "user" ? "justify-end" : "justify-start")}>
            {m.role === "assistant" && (
              <div className={clsx(
                "w-6 h-6 rounded-full border flex items-center justify-center mr-2.5 mt-1 shrink-0",
                m.isClarifying ? "bg-yellow-400/10 border-yellow-400/30" : "bg-synapse-cyan/10 border-synapse-cyan/30"
              )}>
                {m.isClarifying ? <HelpCircle className="w-3 h-3 text-yellow-400" /> : <Brain className="w-3 h-3 text-synapse-cyan" />}
              </div>
            )}
            <div className="max-w-2xl min-w-0 w-full">
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
                  {m.retrieval.coverage && (
                    <span className={`text-[10px] font-mono px-1.5 py-0.5 rounded border ${
                      m.retrieval.coverage === "complete" ? "text-synapse-green border-synapse-green/30 bg-synapse-green/10" :
                      m.retrieval.coverage === "partial" ? "text-synapse-cyan border-synapse-cyan/30 bg-synapse-cyan/10" :
                      m.retrieval.coverage === "sparse" ? "text-yellow-400 border-yellow-400/30 bg-yellow-400/10" :
                      "text-red-400 border-red-400/30 bg-red-400/10"
                    }`}>{m.retrieval.coverage}</span>
                  )}
                </div>
              )}

              {m.role === "assistant" && m.isClarifying && !m.loading && (
                <div className="flex items-center gap-1.5 mb-2">
                  <span className="flex items-center gap-1 px-2 py-0.5 rounded-full bg-yellow-400/10 border border-yellow-400/20 text-[10px] font-mono text-yellow-400">
                    <HelpCircle className="w-2.5 h-2.5" /> needs your input
                  </span>
                </div>
              )}

              <div className={clsx(
                "rounded-xl px-4 py-3 text-sm leading-relaxed",
                m.role === "user"
                  ? "bg-synapse-cyan/10 border border-synapse-cyan/20 text-synapse-text font-mono ml-auto inline-block max-w-full"
                  : m.isClarifying
                    ? "bg-yellow-400/[0.06] border border-yellow-400/25 text-synapse-text"
                    : "bg-synapse-surface border border-synapse-border text-synapse-text"
              )}>
                {m.role === "assistant" ? (
                  <>
                    {!!m.activity?.length && <ActivityFeed activity={m.activity} />}
                    {m.loading && !m.content && !m.activity?.length && (
                      <div className="flex items-center gap-2 text-synapse-muted text-xs font-mono">
                        <Loader2 className="w-3 h-3 animate-spin text-synapse-cyan" />
                        Thinking...
                      </div>
                    )}
                    {m.content && (
                      <div className="prose prose-invert prose-sm max-w-none prose-code:text-synapse-cyan prose-code:font-mono prose-pre:bg-synapse-bg prose-pre:border prose-pre:border-synapse-border">
                        <ReactMarkdown remarkPlugins={[remarkGfm]}>{m.content}</ReactMarkdown>
                      </div>
                    )}
                  </>
                ) : m.content}
              </div>

              {m.role === "assistant" && m.write && (m.write.plan?.length || m.write.placementDir !== undefined) && (
                <WritePanel w={m.write} />
              )}
            </div>
          </div>
        ))}
        <div ref={bottomRef} />
      </div>

      <div className="border-t border-synapse-border p-4">
        <div className="flex gap-3 items-end bg-synapse-surface border border-synapse-border rounded-xl px-4 py-3 focus-within:border-synapse-cyan/40 transition-colors">
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); } }}
            placeholder="Ask, debug, review, or implement something..."
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
  );
}
