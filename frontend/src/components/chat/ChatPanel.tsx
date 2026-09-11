"use client";
import { useState, useRef, useEffect, ReactNode, isValidElement } from "react";
import {
  ArrowUp, Check, ChevronRight, Copy, FileEdit, FilePlus2, GitBranch,
  HelpCircle, Loader2, Maximize2, XCircle,
} from "lucide-react";
import { clsx } from "clsx";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import rehypeHighlight from "rehype-highlight";
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

const LABEL = "text-[10.5px] font-medium uppercase tracking-[0.09em] text-synapse-muted";

function splitPath(p: string) {
  const i = p.lastIndexOf("/");
  return i === -1 ? { dir: "", name: p } : { dir: p.slice(0, i + 1), name: p.slice(i + 1) };
}

/* ── Code blocks ─────────────────────────────────────────────── */

function nodeText(node: ReactNode): string {
  if (node == null || typeof node === "boolean") return "";
  if (typeof node === "string" || typeof node === "number") return String(node);
  if (Array.isArray(node)) return node.map(nodeText).join("");
  if (isValidElement(node)) return nodeText((node.props as any)?.children);
  return "";
}

function CodeBlock({ children }: { children?: ReactNode }) {
  const [copied, setCopied] = useState(false);
  const child = Array.isArray(children) ? children[0] : children;
  const props: any = isValidElement(child) ? child.props : null;
  const lang = /language-([\w+#.-]+)/.exec(props?.className || "")?.[1] || "";
  const copy = () => {
    navigator.clipboard?.writeText(nodeText(props?.children)).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 1600);
    }).catch(() => {});
  };
  return (
    <div className="group/code my-4 overflow-hidden rounded-lg border border-synapse-border-subtle bg-synapse-surface-code">
      <div className="flex h-8 items-center justify-between border-b border-synapse-border-subtle pl-3.5 pr-2">
        <span className="font-mono text-[10.5px] tracking-[0.06em] text-synapse-muted">{lang || "code"}</span>
        <button
          onClick={copy}
          className="flex items-center gap-1 rounded px-1.5 py-0.5 text-[11px] text-synapse-muted opacity-0 transition-opacity hover:text-synapse-text-2 focus:opacity-100 group-hover/code:opacity-100"
        >
          {copied ? <Check className="h-3 w-3" /> : <Copy className="h-3 w-3" />}
          {copied ? "Copied" : "Copy"}
        </button>
      </div>
      <pre className="code-body overflow-x-auto px-3.5 py-3">{children}</pre>
    </div>
  );
}

/* ── Step trail ──────────────────────────────────────────────── */

function StepTrail({ activity, live }: { activity: ActivityStep[]; live: boolean }) {
  return (
    <ol className="ml-[3px] space-y-[7px] border-l border-synapse-border-subtle pl-[18px]">
      {activity.map((a) => (
        <li key={a.id} className="relative text-[12.5px] leading-[1.45]">
          <span
            className={clsx(
              "absolute -left-[22px] top-[5px] h-[7px] w-[7px] rounded-full ring-[3px] ring-synapse-bg",
              a.status === "error" ? "bg-synapse-red"
                : a.status === "active" ? "animate-pulse bg-synapse-cyan"
                : "bg-synapse-border-strong"
            )}
          />
          <span
            className={clsx(
              a.status === "error" ? "text-synapse-red"
                : a.status === "active" && live ? "text-synapse-text"
                : "text-synapse-text-3"
            )}
          >
            {a.label}
          </span>
        </li>
      ))}
    </ol>
  );
}

function LiveTrail({ activity }: { activity: ActivityStep[] }) {
  return (
    <div className="mb-5">
      <div className={clsx(LABEL, "mb-2.5 flex items-center gap-1.5")}>
        <Loader2 className="h-3 w-3 animate-spin" />
        Working
      </div>
      <StepTrail activity={activity} live />
    </div>
  );
}

/* ── Answer footer: steps + retrieval provenance, demoted below the answer ── */

function AnswerMeta({ activity, retrieval }: { activity: ActivityStep[]; retrieval?: RetrievalTrace }) {
  const [open, setOpen] = useState(false);
  const hasError = activity.some((a) => a.status === "error");
  const cov = retrieval?.coverage;
  const rule = <span className="h-2.5 w-px bg-synapse-border" />;

  return (
    <div className="mt-5 border-t border-synapse-border-subtle pt-2.5">
      <div className="flex flex-wrap items-center gap-x-2.5 gap-y-1.5 text-[11.5px] text-synapse-muted">
        {!!activity.length && (
          <button onClick={() => setOpen((o) => !o)} className="flex items-center gap-1.5 transition-colors hover:text-synapse-text-2">
            <ChevronRight className={clsx("h-3 w-3 transition-transform", open && "rotate-90")} />
            <span className="tabular-nums">{activity.length} step{activity.length === 1 ? "" : "s"}</span>
            {hasError && <XCircle className="h-3 w-3 text-synapse-red" />}
          </button>
        )}
        {retrieval && (
          <>
            {!!activity.length && rule}
            <span className="font-mono">{retrieval.intent}</span>
            {retrieval.has_commits && (
              <>
                {rule}
                <span className="flex items-center gap-1"><GitBranch className="h-2.5 w-2.5" />history</span>
              </>
            )}
            {cov && (
              <>
                {rule}
                <span className="flex items-center gap-1.5">
                  <span className={clsx(
                    "h-[5px] w-[5px] rounded-full",
                    cov === "complete" ? "bg-synapse-green" : cov === "empty" ? "bg-synapse-red" : "bg-synapse-amber"
                  )} />
                  {cov} coverage
                </span>
              </>
            )}
          </>
        )}
      </div>

      {open && (
        <div className="mt-3.5 space-y-4 pb-1">
          {!!activity.length && <StepTrail activity={activity} live={false} />}
          {!!retrieval?.anchors.length && (
            <div>
              <div className={clsx(LABEL, "mb-1.5")}>Context anchors</div>
              <div className="flex flex-wrap gap-x-3 gap-y-1 font-mono text-[11.5px] text-synapse-text-3">
                {retrieval.anchors.slice(0, 10).map((a) => <span key={a}>{a}</span>)}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

/* ── File diff manifest ──────────────────────────────────────── */

function FileRow({ file, result, live, onOpen }: {
  file: PlanFile; result?: WriteResult; live?: { tail: string; lines: number; chars: number };
  onOpen: (path: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const pending = !result;
  const canToggle = !!result?.diff;
  const { dir, name } = splitPath(file.rel_path);

  return (
    <div className="border-t border-synapse-border-subtle first:border-t-0">
      <div
        onClick={canToggle ? () => setOpen((o) => !o) : undefined}
        className={clsx(
          "group/row flex h-9 items-center gap-2.5 pl-2.5 pr-3 transition-colors",
          canToggle && "cursor-pointer hover:bg-synapse-surface-2"
        )}
      >
        <span className="flex h-3.5 w-3.5 shrink-0 items-center justify-center text-synapse-muted">
          {canToggle && <ChevronRight className={clsx("h-3.5 w-3.5 transition-transform", open && "rotate-90")} />}
        </span>
        <span className="shrink-0">
          {pending ? <Loader2 className="h-3.5 w-3.5 animate-spin text-synapse-text-3" />
            : !result.ok ? <XCircle className="h-3.5 w-3.5 text-synapse-red" />
            : file.op === "create" ? <FilePlus2 className="h-3.5 w-3.5 text-synapse-green" />
            : <FileEdit className="h-3.5 w-3.5 text-synapse-text-3" />}
        </span>
        <button
          onClick={(e) => { e.stopPropagation(); onOpen(file.rel_path); }}
          className="min-w-0 flex-1 truncate text-left font-mono text-[12px]"
          title="Open in editor"
        >
          <span className="text-synapse-muted">{dir}</span>
          <span className="text-synapse-text-2 group-hover/row:text-synapse-text">{name}</span>
        </button>
        {pending && live && (
          <span className="shrink-0 font-mono text-[11px] tabular-nums text-synapse-muted">{live.lines} L</span>
        )}
        {result?.ok && (
          <span className="shrink-0 font-mono text-[11px] tabular-nums">
            <span className="text-synapse-green">+{result.added}</span>{" "}
            <span className="text-synapse-red">−{result.removed}</span>
          </span>
        )}
        {result && !result.ok && (
          <span className="max-w-[180px] shrink-0 truncate font-mono text-[11px] text-synapse-red">{result.error}</span>
        )}
        <button
          onClick={(e) => { e.stopPropagation(); onOpen(file.rel_path); }}
          className="shrink-0 text-synapse-muted opacity-0 transition-opacity hover:text-synapse-text group-hover/row:opacity-100"
          title="Open in editor"
        >
          <Maximize2 className="h-3.5 w-3.5" />
        </button>
      </div>

      {pending && live?.tail && (
        <pre className="max-h-24 overflow-hidden whitespace-pre-wrap break-all border-t border-synapse-border-subtle bg-synapse-surface-code px-3.5 py-2 font-mono text-[11px] leading-[1.6] text-synapse-text-3">
          {live.tail}
          <span className="ml-0.5 inline-block h-3 w-[6px] animate-pulse bg-synapse-cyan/60 align-middle" />
        </pre>
      )}

      {open && result?.diff && (
        <div className="max-h-72 overflow-auto border-t border-synapse-border-subtle bg-synapse-surface-code">
          <pre className="py-2 font-mono text-[11.5px] leading-[1.6]">
            {result.diff.split("\n").map((l, i) => {
              const add = l.startsWith("+") && !l.startsWith("+++");
              const del = l.startsWith("-") && !l.startsWith("---");
              const hunk = l.startsWith("@@");
              return (
                <div key={i} className={clsx(
                  "px-3.5",
                  add ? "bg-synapse-green/[0.07] text-[#8FD69B]"
                    : del ? "bg-synapse-red/[0.07] text-[#E3948F]"
                    : hunk ? "text-synapse-cyan-dim"
                    : "text-synapse-text-3/80"
                )}>{l || " "}</div>
              );
            })}
          </pre>
        </div>
      )}
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
    <div className="my-5 overflow-hidden rounded-lg border border-synapse-border bg-synapse-surface">
      <div className="flex h-10 items-center gap-2.5 border-b border-synapse-border px-3.5">
        <GitBranch className="h-3.5 w-3.5 shrink-0 text-synapse-text-3" />
        <span className="text-[12.5px] font-medium text-synapse-text">
          {files.length} file{files.length !== 1 ? "s" : ""} changed
        </span>
        {(totals.added > 0 || totals.removed > 0) && (
          <span className="font-mono text-[11px] tabular-nums">
            <span className="text-synapse-green">+{totals.added}</span>{" "}
            <span className="text-synapse-red">−{totals.removed}</span>
          </span>
        )}
        {w.placementDir !== undefined && (
          <span className="ml-auto truncate font-mono text-[11px] text-synapse-muted" title={w.placementDir || "repo root"}>
            {w.placementDir || "repo root"}
          </span>
        )}
      </div>
      {!!w.exemplars?.length && (
        <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1 border-b border-synapse-border-subtle px-3.5 py-2.5">
          <span className={LABEL}>Patterned on</span>
          <span className="font-mono text-[11px] text-synapse-text-3">{w.exemplars.join("  ·  ")}</span>
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
              <div className="flex h-full items-center justify-center px-8">
                <div className="w-full max-w-[560px] pb-10">
                  <h1 className="text-[22px] font-semibold tracking-[-0.02em] text-synapse-text">
                    What should we look at?
                  </h1>
                  <p className="mt-2.5 max-w-[480px] text-[13.5px] leading-[1.65] text-synapse-text-3">
                    Answers are grounded in this repo&apos;s code graph — files, call paths and history.
                    Implementation requests are planned, written to disk and returned as diffs.
                  </p>
                  <div className={clsx(LABEL, "mt-8")}>Try</div>
                  <div className="mt-2.5 grid grid-cols-2 gap-2">
                    {STARTERS.map((s) => (
                      <button
                        key={s}
                        onClick={() => send(s)}
                        className="rounded-lg border border-synapse-border bg-synapse-surface px-3 py-2.5 text-left text-[12.5px] leading-snug text-synapse-text-2 transition-colors hover:border-synapse-border-strong hover:text-synapse-text"
                      >
                        {s}
                      </button>
                    ))}
                  </div>
                </div>
              </div>
            )}

            <div className="mx-auto max-w-[760px] px-8 py-10">
              {messages.map((m, i) => (
                <div key={i} className={clsx("group", i > 0 && (m.role === "user" ? "mt-11" : "mt-5"))}>
                  {m.role === "user" ? (
                    <div className="whitespace-pre-wrap rounded-lg border border-synapse-border bg-synapse-surface px-4 py-3 text-[14.5px] leading-[1.6] text-synapse-text">
                      {m.content}
                    </div>
                  ) : (
                    <>
                      {m.loading && !!m.activity?.length && <LiveTrail activity={m.activity} />}

                      {m.loading && !m.content && !m.activity?.length && (
                        <div className="flex items-center gap-2 text-[12.5px] text-synapse-text-3">
                          <Loader2 className="h-3.5 w-3.5 animate-spin" />
                          Thinking…
                        </div>
                      )}

                      {m.isClarifying && !m.loading && (
                        <div className="mb-3.5 flex items-start gap-2 border-l-2 border-synapse-amber/50 pl-3 text-[12.5px] leading-[1.5] text-synapse-amber/90">
                          <HelpCircle className="mt-[2px] h-3.5 w-3.5 shrink-0" />
                          <span>Needs your input before continuing.</span>
                        </div>
                      )}

                      {m.content && (
                        <div className="prose-synapse">
                          <ReactMarkdown
                            remarkPlugins={[remarkGfm]}
                            rehypePlugins={[[rehypeHighlight, { detect: true, ignoreMissing: true }]]}
                            components={{ pre: ({ children }) => <CodeBlock>{children}</CodeBlock> }}
                          >
                            {m.content}
                          </ReactMarkdown>
                        </div>
                      )}

                      {m.write && (m.write.plan?.length || m.write.placementDir !== undefined) && (
                        <WritePanel w={m.write} onOpenFile={setOpenFilePath} />
                      )}

                      {!m.loading && (!!m.activity?.length || !!m.retrieval) && (
                        <AnswerMeta activity={m.activity || []} retrieval={m.retrieval} />
                      )}
                    </>
                  )}
                </div>
              ))}
              <div ref={bottomRef} className="h-2" />
            </div>
          </div>

          <div className="border-t border-synapse-border px-8 pb-5 pt-4">
            <div className="mx-auto max-w-[760px]">
              <div className="rounded-xl border border-synapse-border bg-synapse-surface px-3.5 pb-2.5 pt-3 transition-colors focus-within:border-synapse-border-strong">
                <textarea
                  value={input}
                  onChange={(e) => setInput(e.target.value)}
                  onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); } }}
                  placeholder="Ask about this repo, or describe a change to make…"
                  rows={1}
                  className="block max-h-[200px] w-full resize-none bg-transparent text-[14.5px] leading-[1.6] text-synapse-text placeholder:text-synapse-muted focus:outline-none"
                />
                <div className="mt-2 flex items-center">
                  <span className="text-[11px] text-synapse-muted">
                    <kbd className="font-sans">Enter</kbd> to send · <kbd className="font-sans">Shift+Enter</kbd> for newline
                  </span>
                  <button
                    onClick={() => send()}
                    disabled={!input.trim() || streaming}
                    title="Send"
                    className="ml-auto flex h-7 w-7 items-center justify-center rounded-md bg-synapse-text text-synapse-bg transition-colors hover:bg-white disabled:bg-synapse-surface-3 disabled:text-synapse-muted"
                  >
                    {streaming ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <ArrowUp className="h-4 w-4" />}
                  </button>
                </div>
              </div>
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
