"use client";
import { useEffect, useState, useCallback } from "react";
import { Plus, Trash2 } from "lucide-react";
import { clsx } from "clsx";
import { getSessions, deleteSession, ChatSessionInfo } from "@/lib/api";

function relativeTime(iso: string): string {
  const d = new Date(iso).getTime();
  const diffMin = Math.round((Date.now() - d) / 60000);
  if (diffMin < 1) return "now";
  if (diffMin < 60) return `${diffMin}m`;
  const diffHr = Math.round(diffMin / 60);
  if (diffHr < 24) return `${diffHr}h`;
  const diffDay = Math.round(diffHr / 24);
  if (diffDay < 7) return `${diffDay}d`;
  return new Date(iso).toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

export default function SessionSidebar({
  repoId, activeSessionId, onSelect, onNewChat, refreshKey,
}: {
  repoId: string;
  activeSessionId: string | null;
  onSelect: (sessionId: string) => void;
  onNewChat: () => void;
  refreshKey?: number;
}) {
  const [sessions, setSessions] = useState<ChatSessionInfo[]>([]);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    try {
      const rows = await getSessions(repoId);
      setSessions(rows);
    } catch {
      setSessions([]);
    }
    setLoading(false);
  }, [repoId]);

  useEffect(() => { load(); }, [load, refreshKey]);

  const handleDelete = async (e: React.MouseEvent, id: string) => {
    e.stopPropagation();
    await deleteSession(id);
    if (id === activeSessionId) onNewChat();
    load();
  };

  return (
    <div className="flex w-[248px] shrink-0 flex-col border-r border-synapse-border bg-synapse-surface">
      <div className="flex h-14 items-center px-3">
        <button
          onClick={onNewChat}
          className="flex h-8 flex-1 items-center gap-2 rounded-md border border-synapse-border px-2.5 text-[12.5px] font-medium text-synapse-text-2 transition-colors hover:border-synapse-border-strong hover:text-synapse-text"
        >
          <Plus className="h-3.5 w-3.5" /> New chat
        </button>
      </div>
      <div className="px-4 pb-1.5 text-[10.5px] font-medium uppercase tracking-[0.09em] text-synapse-muted">
        Conversations
      </div>
      <div className="flex-1 overflow-y-auto px-2 pb-3">
        {loading ? (
          <div className="px-2 py-3 text-[12px] text-synapse-muted">Loading…</div>
        ) : sessions.length === 0 ? (
          <div className="px-2 py-3 text-[12px] leading-relaxed text-synapse-muted">
            Nothing here yet.
          </div>
        ) : (
          <div>
            {sessions.map((s) => (
              <div
                key={s.id}
                onClick={() => onSelect(s.id)}
                className={clsx(
                  "group relative my-0.5 flex h-8 cursor-pointer items-center gap-2 rounded-md px-2.5 text-[12.5px] transition-colors",
                  s.id === activeSessionId ? "bg-synapse-surface-3 text-synapse-text" : "text-synapse-text-3 hover:bg-synapse-surface-2 hover:text-synapse-text-2"
                )}
              >
                <span className="flex-1 truncate">{s.title || "New chat"}</span>
                <span className="shrink-0 font-mono text-[10.5px] tabular-nums text-synapse-muted group-hover:hidden">
                  {relativeTime(s.updated_at)}
                </span>
                <button
                  onClick={(e) => handleDelete(e, s.id)}
                  className="hidden group-hover:flex text-synapse-muted hover:text-synapse-red transition-colors shrink-0"
                >
                  <Trash2 className="w-3.5 h-3.5" />
                </button>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
