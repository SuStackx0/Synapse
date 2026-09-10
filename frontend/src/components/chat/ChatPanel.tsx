"use client";
import { useState, useRef, useEffect } from "react";
import {
  Brain, Send, Loader2, Terminal, FileCode, GitBranch, CheckCircle2,
  XCircle, FilePlus2, FileEdit, ChevronDown, ChevronRight,
  HelpCircle, Maximize2,
} from "lucide-react";
import { clsx } from "clsx";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { getSessionMessages, ChatMessageInfo } from "@/lib/api";
import SessionSidebar from "./SessionSidebar";
import FilePanel from "./FilePanel";

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
  liveTail?: Record<string, { tail: string; lines: number; chars: number }>;
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
  if (!ok) return <XCircle className="w-3.5 h-3.5 text-synapse-red" />;
  return op === "create"
    ? <FilePlus2 className="w-3.5 h-3.5 text-synapse-green" />
    : <FileEdit className="w-3.5 h-3.5 text-synapse-text-2" />;
}

function FileRow({ file, result, live, onOpen }: {
  file: PlanFile; result?: WriteResult; live?: { tail: string; lines: number; chars: number };
  onOpen: (path: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const pending = !result;
  return (
    <div className="border-b border-synapse-border last:border-0">
      <div className="w-full flex items-center gap-2.5 h-9 px-3 hover:bg-synapse-surface-2 transition-colors">
        {pending ? (
          <Loader2 className="w-3.5 h-3.5 text-synapse-text-2 animate-spin shrink-0" />
        ) : (
          opIcon(file.op, result.ok)
        )}
        <button
          onClick={() => onOpen(file.rel_path)}
          className="font-mono text-[12px] text-synapse-text-2 truncate flex-1 text-left hover:text-synapse-text transition-colors"
          title="Open in editor"
        >
          {file.rel_path}
        </button>
        {pending && live && (
          <span className="text-[11px] font-mono tabular-nums text-synapse-muted shrink-0">{live.lines}L</span>
        )}
        {result && result.ok && (
          <span className="text-[11px] font-mono tabular-nums shrink-0">
            <span className="text-synapse-green">+{result.added}</span>{" "}
            <span className="text-synapse-red">−{result.removed}</span>
          </span>
        )}
        {result && !result.ok && (
          <span className="text-[11px] font-mono text-synapse-red shrink-0 max-w-[160px] truncate">{result.error}</span>
        )}
        <button onClick={() => onOpen(file.rel_path)} className="text-synapse-muted hover:text-synapse-cyan transition-colors shrink-0" title="Open in editor">
          <Maximize2 className="w-3.5 h-3.5" />
        </button>
        {result?.diff && (
          <button onClick={() => setOpen((o) => !o)} className="text-synapse-muted hover:text-synapse-text-2 transition-colors shrink-0" title="Toggle diff">
            {open ? <ChevronDown className="w-3.5 h-3.5" /> : <ChevronRight className="w-3.5 h-3.5" />}
          </button>
        )}
      </div>
      {pending && live?.tail && (
        <pre className="text-[11px] font-mono leading-relaxed px-3 py-2 bg-synapse-bg border-t border-synapse-border overflow-hidden max-h-24 text-synapse-green/70 whitespace-pre-wrap break-all">
          {live.tail}
          <span className="inline-block w-1.5 h-3 bg-synapse-cyan/70 align-middle ml-0.5 animate-pulse" />
        </pre>
      )}
      {open && result?.diff && (
        <pre className="text-[11px] font-mono leading-relaxed px-3 py-2 bg-synapse-bg border-t border-synapse-border overflow-x-auto max-h-64 overflow-y-auto">
          {result.diff.split("\n").map((l, i) => (
            <div key={i} className={clsx(
              l.startsWith("+") && !l.startsWith("+++") ? "text-synapse-green" :
              l.startsWith("-") && !l.startsWith("---") ? "text-synapse-red" :
              "text-synapse-muted"
            )}>{l || " "}</div>
          ))}
        </pre>
      )}
    </div>
  );
}

function ActivityFeed({ activity, done }: { activity: ActivityStep[]; done: boolean }) {
  const [expanded, setExpanded] = useState(false);
  if (!activity.length) return null;

  if (done && !expanded) {
    const hasError = activity.some((a) => a.status === "error");
    return (
      <button
        onClick={() => setExpanded(true)}
        className="mb-4 flex h-7 items-center gap-1.5 text-[12px] text-synapse-muted hover:text-synapse-text-2 transition-colors"
      >
        <ChevronRight className="w-3.5 h-3.5" />
        <span>{activity.length} step{activity.length === 1 ? "" : "s"}</span>
        {hasError && <XCircle className="w-3 h-3 text-synapse-red" />}
      </button>
    );
  }

  return (
    <div className={clsx("mb-4", done && "ml-1.5 border-l border-synapse-border pl-4")}>
      {done && (
        <button onClick={() => setExpanded(false)} className="flex items-center gap-1.5 text-[12px] text-synapse-muted hover:text-synapse-text-2 mb-1.5 -ml-[19px] transition-colors">
          <ChevronDown className="w-3.5 h-3.5" />
          <span>{activity.length} steps</span>
        </button>
      )}
      <div className="space-y-1.5">
        {activity.map((a) => (
          <div key={a.id} className="flex items-start gap-2 text-[12px]">
            {!done && (
              <span className="mt-0.5 shrink-0">
                {a.status === "active" && <Loader2 className="w-3 h-3 animate-spin text-synapse-text-2" />}
                {a.status === "done" && <CheckCircle2 className="w-3 h-3 text-synapse-green" />}
                {a.status === "error" && <XCircle className="w-3 h-3 text-synapse-red" />}
              </span>
            )}
            <span className={clsx(
              a.status === "error" ? "text-synapse-red" : "text-synapse-text-2"
            )}>{a.label}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

function WritePanel({ w, onOpenFile }: { w: WriteState; onOpenFile: (path: string) => void }) {
  const files = w.plan || [];
  const totals = files.reduce((acc, f) => {
    const r = w.results[f.rel_path];
    if (r) { acc.added += r.added; acc.removed += r.removed; }
    return acc;
  }, { added: 0, removed: 0 });

  return (
    <div className="my-4 rounded-lg border border-synapse-border bg-synapse-surface overflow-hidden">
      <div className="flex h-9 items-center gap-3 border-b border-synapse-border px-3">
        <span className="text-[13px] font-medium text-synapse-text">
          {files.length} file{files.length !== 1 ? "s" : ""} changed
        </span>
        {(totals.added > 0 || totals.removed > 0) && (
          <span className="font-mono text-[11px] tabular-nums">
            <span className="text-synapse-green">+{totals.added}</span>{" "}
            <span className="text-synapse-red">−{totals.removed}</span>
          </span>
        )}
        {w.placementDir !== undefined && (
          <span className="ml-auto text-[11px] font-mono text-synapse-muted truncate">
            {w.placementDir || "repo root"}
          </span>
        )}
      </div>
      {!!w.exemplars?.length && (
        <div className="px-3 py-2 border-b border-synapse-border flex flex-wrap gap-x-3 gap-y-1 text-[11px] font-mono text-synapse-muted">
          <span className="text-synapse-text-2">referenced:</span>
          {w.exemplars.map((e) => <span key={e}>{e}</span>)}
        </div>
      )}
      {!!files.length && (
        <div>
          {files.map((f) => (
            <FileRow key={f.rel_path} file={f} result={w.results[f.rel_path]} live={w.liveTail?.[f.rel_path]} onOpen={onOpenFile} />
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

export default function ChatPanel({ repoId, buildSessionId }: { repoId: string; buildSessionId?: string }) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [hydrated, setHydrated] = useState(false);
  const [sidebarRefresh, setSidebarRefresh] = useState(0);
  const [openFilePath, setOpenFilePath] = useState<string | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);

  const storageKey = `synapse_session_${repoId}`;

  const loadSession = async (id: string) => {
    try {
      const rows = await getSessionMessages(id);
      setSessionId(id);
      setMessages(messagesFromHistory(rows));
      localStorage.setItem(storageKey, id);
    } catch {
      localStorage.removeItem(storageKey);
    }
  };

  useEffect(() => {
    let cancelled = false;
    (async () => {
      const saved = typeof window !== "undefined" ? localStorage.getItem(storageKey) : null;
      const target = saved || buildSessionId;
      if (target && !cancelled) await loadSession(target);
      if (!cancelled) setHydrated(true);
    })();
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [repoId, buildSessionId]);

  useEffect(() => { bottomRef.current?.scrollIntoView({ behavior: "smooth" }); }, [messages]);

  const startNewChat = () => {
    localStorage.removeItem(storageKey);
    setSessionId(null);
    setMessages([]);
    setOpenFilePath(null);
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

    let wasNewSession = !sessionId;

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
          pushActivity("context_ready", `Found placement — ${dir}${n ? `, ${n} exemplar file(s)` : ""}`, "done");
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
          pushActivity(`file:${event.rel_path}`, `Writing ${event.rel_path}`, "active");
          update((m) => ({
            ...m,
            write: { results: {}, ...m.write, writingPath: event.rel_path },
          }));
        } else if (event.event === "coding_progress") {
          if (!event.done) {
            pushActivity(`file:${event.rel_path}`, `Writing ${event.rel_path} — ${event.lines} line${event.lines === 1 ? "" : "s"} (${event.chars} chars)`, "active");
            update((m) => ({
              ...m,
              write: {
                results: {}, ...m.write,
                liveTail: { ...(m.write?.liveTail || {}), [event.rel_path]: { tail: event.tail, lines: event.lines, chars: event.chars } },
              },
            }));
          }
        } else if (event.event === "file_written") {
          pushActivity(
            `file:${event.rel_path}`,
            event.ok ? `${event.rel_path} written (+${event.added}/−${event.removed})` : `${event.rel_path} failed — ${event.error}`,
            event.ok ? "done" : "error"
          );
          update((m) => ({
            ...m,
            write: {
              ...(m.write || { results: {} }),
              results: { ...(m.write?.results || {}), [event.rel_path]: event },
            },
          }));
          if (event.ok) setOpenFilePath(event.rel_path);
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
    if (wasNewSession) setSidebarRefresh((n) => n + 1);
  };

  return (
    <div className="h-full flex">
      <SessionSidebar
        repoId={repoId}
        activeSessionId={sessionId}
        onSelect={loadSession}
        onNewChat={startNewChat}
        refreshKey={sidebarRefresh}
      />

      <div className="flex-1 min-w-0 flex">
        <div className={clsx("flex flex-col min-w-0", openFilePath ? "flex-1" : "w-full")}>
          <div className="flex-1 overflow-y-auto">
            {hydrated && messages.length === 0 && (
              <div className="h-full flex flex-col items-center justify-center text-center px-6">
                <Terminal className="w-9 h-9 text-synapse-border mb-3" strokeWidth={1.5} />
                <p className="text-synapse-text-2 text-[14px]">Ask, debug, review, or implement — just say what you need.</p>
                <p className="text-synapse-muted text-[13px] mt-1 mb-6">Context retrieved from code + call graph. Code changes are graph-planned and written to disk.</p>
                <div className="flex flex-wrap justify-center gap-2 max-w-xl">
                  {STARTERS.map((s) => (
                    <button
                      key={s}
                      onClick={() => send(s)}
                      className="px-3 py-1.5 rounded-md border border-synapse-border text-synapse-text-2 hover:text-synapse-text hover:border-synapse-border-strong text-[13px] transition-all"
                    >
                      {s}
                    </button>
                  ))}
                </div>
              </div>
            )}

            <div className="max-w-[780px] mx-auto px-6 py-8 space-y-8">
              {messages.map((m, i) => (
                <div key={i} className="group">
                  <div className="mb-2 flex items-center gap-2">
                    <span className="text-[12px] font-medium text-synapse-text-2">
                      {m.role === "user" ? "You" : "Synapse"}
                    </span>

                    {m.role === "assistant" && m.retrieval && (
                      <div className="flex flex-wrap items-center gap-2 text-[11px] font-mono text-synapse-muted">
                        <span>{m.retrieval.intent}</span>
                        {m.retrieval.has_commits && (
                          <span className="flex items-center gap-1">
                            <GitBranch className="w-2.5 h-2.5" /> history
                          </span>
                        )}
                        <span className={clsx(
                          m.retrieval.coverage === "complete" ? "text-synapse-green" :
                          m.retrieval.coverage === "empty" ? "text-synapse-red" : "text-synapse-amber"
                        )}>cov {m.retrieval.coverage}</span>
                      </div>
                    )}
                    {m.role === "assistant" && m.isClarifying && !m.loading && (
                      <span className="flex items-center gap-1 text-[11px] text-synapse-amber">
                        <HelpCircle className="w-3 h-3" /> needs your input
                      </span>
                    )}
                  </div>

                  {m.role === "assistant" && m.retrieval && !!m.retrieval.anchors.length && (
                    <div className="mb-2 text-[11px] font-mono text-synapse-muted truncate">
                      {m.retrieval.anchors.slice(0, 5).join(" · ")}
                    </div>
                  )}

                  {m.role === "user" ? (
                    <div className="border-l-2 border-synapse-border-strong pl-4 text-[15px] leading-[1.6] text-synapse-text whitespace-pre-wrap">
                      {m.content}
                    </div>
                  ) : (
                    <>
                      {!!m.activity?.length && <ActivityFeed activity={m.activity} done={!m.loading} />}
                      {m.loading && !m.content && !m.activity?.length && (
                        <div className="flex items-center gap-2 text-synapse-muted text-[13px]">
                          <Loader2 className="w-3.5 h-3.5 animate-spin" />
                          Thinking...
                        </div>
                      )}
                      {m.content && (
                        <div className="prose-synapse text-[15px] leading-[1.65] text-synapse-text">
                          <ReactMarkdown remarkPlugins={[remarkGfm]}>{m.content}</ReactMarkdown>
                        </div>
                      )}
                      {m.write && (m.write.plan?.length || m.write.placementDir !== undefined) && (
                        <WritePanel w={m.write} onOpenFile={setOpenFilePath} />
                      )}
                    </>
                  )}
                </div>
              ))}
              <div ref={bottomRef} />
            </div>
          </div>

          <div className="border-t border-synapse-border px-6 py-4">
            <div className="max-w-[780px] mx-auto">
              <div className="rounded-lg border border-synapse-border bg-synapse-surface-2 focus-within:border-synapse-cyan/50 focus-within:ring-1 focus-within:ring-synapse-cyan/20 transition-all">
                <textarea
                  value={input}
                  onChange={(e) => setInput(e.target.value)}
                  onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); } }}
                  placeholder="Ask about this repo…"
                  rows={1}
                  className="w-full max-h-[200px] bg-transparent px-3.5 py-3 text-[15px] leading-[1.5] text-synapse-text resize-none focus:outline-none placeholder:text-synapse-muted"
                />
                <div className="flex h-10 items-center px-2.5">
                  <button onClick={() => send()} disabled={!input.trim() || streaming}
                    className="ml-auto flex h-7 items-center gap-1.5 rounded-md bg-synapse-cyan px-2.5 text-[13px] font-medium text-synapse-bg disabled:bg-synapse-surface-3 disabled:text-synapse-muted transition-colors">
                    {streaming ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Send className="w-3.5 h-3.5" />}
                    Send
                  </button>
                </div>
              </div>
              <p className="text-[11px] text-synapse-muted mt-2 text-center">Enter to send · Shift+Enter for newline</p>
            </div>
          </div>
        </div>

        {openFilePath && (
          <div className="w-[45%] min-w-[420px] max-w-[720px] shrink-0">
            <FilePanel repoId={repoId} path={openFilePath} onClose={() => setOpenFilePath(null)} />
          </div>
        )}
      </div>
    </div>
  );
}
