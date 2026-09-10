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

const TABS: { id: Tab; label: string; icon: React.ElementType; color: string }[] = [
  { id: "chat", label: "Ask AI", icon: Brain, color: "text-synapse-cyan" },
  { id: "graph", label: "Repo Brain", icon: GitBranch, color: "text-synapse-green" },
  { id: "health", label: "Vibe Check", icon: Activity, color: "text-synapse-purple" },
  { id: "benchmark", label: "Benchmark", icon: Scale, color: "text-yellow-400" },
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
      <div className="text-synapse-cyan font-mono animate-pulse">Loading...</div>
    </div>
  );

  return (
    <div className="h-screen flex flex-col">
      {/* Header */}
      <header className="border-b border-synapse-border px-6 py-4 flex items-center gap-4">
        <button onClick={() => router.push("/")} className="text-synapse-muted hover:text-synapse-text transition-colors">
          <ArrowLeft className="w-4 h-4" />
        </button>
        <div className="flex items-center gap-2">
          <Brain className="w-4 h-4 text-synapse-cyan" />
          <span className="font-mono font-semibold text-synapse-text">{repo.name}</span>
          <span className="text-synapse-muted text-xs font-mono">· {repo.file_count} files</span>
        </div>
        <div className="flex items-center gap-1.5 ml-2">
          <span className="w-1.5 h-1.5 rounded-full bg-synapse-green animate-pulse" />
          <span className="text-synapse-green text-xs font-mono">INDEXED</span>
        </div>
        <div className="flex-1" />
        <a href="/settings" className="text-synapse-muted hover:text-synapse-text transition-colors">
          <Settings className="w-4 h-4" />
        </a>
      </header>

      {/* Tab Bar */}
      <div className="border-b border-synapse-border px-6 flex gap-1">
        {TABS.map(({ id: tid, label, icon: Icon, color }) => (
          <button
            key={tid}
            onClick={() => setTab(tid)}
            className={clsx(
              "flex items-center gap-2 px-4 py-3 text-sm font-mono border-b-2 transition-all",
              tab === tid
                ? `border-current ${color}`
                : "border-transparent text-synapse-muted hover:text-synapse-text"
            )}
          >
            <Icon className="w-3.5 h-3.5" />
            {label}
          </button>
        ))}
      </div>

      {/* Content */}
      <div className="flex-1 overflow-hidden">
        {tab === "chat" && <ChatPanel repoId={id} />}
        {tab === "graph" && <GraphExplorer repoId={id} />}
        {tab === "health" && <HealthDashboard repoId={id} />}
        {tab === "benchmark" && <Benchmarker repoId={id} />}
      </div>
    </div>
  );
}
