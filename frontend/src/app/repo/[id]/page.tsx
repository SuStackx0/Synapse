"use client";
import { useState, useEffect } from "react";
import { useParams, useRouter } from "next/navigation";
import { getRepo, Repo } from "@/lib/api";
import { Brain, GitBranch, Activity, Zap, ArrowLeft, Scale, Settings } from "lucide-react";
import { clsx } from "clsx";
import dynamic from "next/dynamic";

const ChatPanel = dynamic(() => import("@/components/chat/ChatPanel"), { ssr: false });
const GraphExplorer = dynamic(() => import("@/components/graph/GraphExplorer"), { ssr: false });
const HealthDashboard = dynamic(() => import("@/components/health/HealthDashboard"), { ssr: false });
const Benchmarker = dynamic(() => import("@/components/benchmark/Benchmarker"), { ssr: false });

type Tab = "chat" | "graph" | "health" | "benchmark";

const TABS: { id: Tab; label: string; icon: React.ElementType }[] = [
  { id: "chat", label: "Ask AI", icon: Brain },
  { id: "graph", label: "Repo Brain", icon: GitBranch },
  { id: "health", label: "Vibe Check", icon: Activity },
  { id: "benchmark", label: "Benchmark", icon: Scale },
];

export default function RepoPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const [repo, setRepo] = useState<Repo | null>(null);
  const [tab, setTab] = useState<Tab>("chat");

  useEffect(() => {
    getRepo(id).then(setRepo).catch(() => router.push("/"));
  }, [id]);

  if (!repo) return (
    <div className="h-screen flex items-center justify-center">
      <div className="text-synapse-text-2 animate-pulse">Loading…</div>
    </div>
  );

  return (
    <div className="h-screen flex flex-col">
      {/* Header */}
      <header className="h-12 shrink-0 border-b border-synapse-border px-4 flex items-center gap-3">
        <button onClick={() => router.push("/")} className="text-synapse-muted hover:text-synapse-text transition-colors">
          <ArrowLeft className="w-4 h-4" />
        </button>
        <div className="flex items-center gap-2 text-[13px]">
          <span className="font-medium text-synapse-text">{repo.name}</span>
          <span className="text-synapse-muted">· {repo.file_count} files</span>
        </div>
        <div className="flex items-center gap-1.5 ml-1">
          <span className="w-1.5 h-1.5 rounded-full bg-synapse-green" />
          <span className="text-synapse-text-2 text-[13px]">Indexed</span>
        </div>
        <div className="flex-1" />
        <a href="/settings" className="text-synapse-muted hover:text-synapse-text transition-colors">
          <Settings className="w-4 h-4" />
        </a>
      </header>

      {/* Tab Bar */}
      <div className="h-10 shrink-0 border-b border-synapse-border px-4 flex gap-1">
        {TABS.map(({ id: tid, label, icon: Icon }) => (
          <button
            key={tid}
            onClick={() => setTab(tid)}
            className={clsx(
              "relative flex items-center gap-1.5 px-3 h-10 text-[13px] transition-colors",
              tab === tid
                ? "text-synapse-text after:absolute after:bottom-0 after:left-0 after:right-0 after:h-[2px] after:bg-synapse-cyan"
                : "text-synapse-muted hover:text-synapse-text-2"
            )}
          >
            <Icon className="w-3.5 h-3.5" />
            {label}
          </button>
        ))}
      </div>

      {/* Content */}
      <div className="flex-1 overflow-hidden">
        {tab === "chat" && <ChatPanel repoId={id} buildSessionId={repo.build_session_id} />}
        {tab === "graph" && <GraphExplorer repoId={id} />}
        {tab === "health" && <HealthDashboard repoId={id} />}
        {tab === "benchmark" && <Benchmarker repoId={id} />}
      </div>
    </div>
  );
}
