"use client";
import { useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import { getRepos, addLocalRepo, addGithubRepo, createNewProject, deleteRepo, Repo } from "@/lib/api";
import { GitBranch, Plus, Trash2, Loader2, FolderOpen, Github, Zap, Activity, Brain, Sparkles } from "lucide-react";
import { clsx } from "clsx";

export default function Home() {
  const router = useRouter();
  const [repos, setRepos] = useState<Repo[]>([]);
  const [loading, setLoading] = useState(true);
  const [showAdd, setShowAdd] = useState(false);
  const [addType, setAddType] = useState<"local" | "github" | "new">("local");
  const [localPath, setLocalPath] = useState("");
  const [inPlace, setInPlace] = useState(false);
  const [ghUrl, setGhUrl] = useState("");
  const [ghPat, setGhPat] = useState("");
  const [repoName, setRepoName] = useState("");
  const [projectDescription, setProjectDescription] = useState("");
  const [adding, setAdding] = useState(false);
  const [error, setError] = useState("");

  const load = async () => {
    try {
      setRepos(await getRepos());
    } catch {}
    setLoading(false);
  };

  useEffect(() => {
    load();
    const t = setInterval(load, 1500);
    return () => clearInterval(t);
  }, []);

  const handleAdd = async () => {
    setAdding(true);
    setError("");
    try {
      if (addType === "local") {
        await addLocalRepo(localPath, repoName || undefined, inPlace);
      } else if (addType === "github") {
        await addGithubRepo(ghUrl, ghPat, repoName || undefined);
      } else {
        await createNewProject(repoName || "New Project", projectDescription);
      }
      setShowAdd(false);
      setLocalPath(""); setGhUrl(""); setGhPat(""); setRepoName(""); setProjectDescription("");
      load();
    } catch (e: any) {
      setError(e.message);
    }
    setAdding(false);
  };

  const handleDelete = async (id: string, e: React.MouseEvent) => {
    e.stopPropagation();
    await deleteRepo(id);
    load();
  };

  return (
    <div className="min-h-screen flex flex-col">
      {/* Header */}
      <header className="border-b border-synapse-border px-8 py-5 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 rounded-lg bg-synapse-cyan/10 border border-synapse-cyan/30 flex items-center justify-center">
            <Brain className="w-4 h-4 text-synapse-cyan" />
          </div>
          <span className="font-mono text-lg font-semibold tracking-tight text-synapse-text">
            SYNAPSE
          </span>
          <span className="text-synapse-muted text-xs font-mono ml-1">v1.0</span>
        </div>
        <div className="flex items-center gap-4">
          <a href="/settings" className="text-xs text-synapse-muted hover:text-synapse-text transition-colors font-mono">
            SETTINGS
          </a>
          <button
            onClick={() => setShowAdd(true)}
            className="flex items-center gap-2 px-4 py-2 bg-synapse-cyan/10 border border-synapse-cyan/30 rounded-lg text-synapse-cyan text-sm font-mono hover:bg-synapse-cyan/20 hover:glow-cyan transition-all"
          >
            <Plus className="w-4 h-4" /> NEW REPO
          </button>
        </div>
      </header>

      {/* Hero */}
      <div className="px-8 py-16 text-center max-w-3xl mx-auto">
        <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full border border-synapse-green/30 bg-synapse-green/5 text-synapse-green text-xs font-mono mb-6">
          <Zap className="w-3 h-3" /> AI-POWERED CODEBASE INTELLIGENCE
        </div>
        <h1 className="text-5xl font-bold tracking-tight mb-4">
          <span className="text-synapse-text">Understand your </span>
          <span className="text-synapse-cyan">codebase</span>
          <span className="text-synapse-text">.</span>
          <br />
          <span className="text-synapse-muted text-3xl font-normal">Like you always meant to.</span>
        </h1>
        <p className="text-synapse-muted text-lg">
          Graph-powered code exploration, AI debugging, and instant codebase Q&A.
        </p>
      </div>

      {/* Repo Grid */}
      <main className="flex-1 px-8 max-w-6xl mx-auto w-full pb-16">
        {loading ? (
          <div className="flex items-center justify-center py-32">
            <Loader2 className="w-8 h-8 text-synapse-cyan animate-spin" />
          </div>
        ) : repos.length === 0 ? (
          <div className="text-center py-24 border border-dashed border-synapse-border rounded-2xl">
            <GitBranch className="w-12 h-12 text-synapse-muted mx-auto mb-4" />
            <p className="text-synapse-muted font-mono">No repos connected yet.</p>
            <p className="text-synapse-muted/60 text-sm mt-1">Add a local path or GitHub repo to get started.</p>
            <button onClick={() => setShowAdd(true)} className="mt-6 px-6 py-2.5 bg-synapse-cyan/10 border border-synapse-cyan/30 rounded-lg text-synapse-cyan font-mono text-sm hover:bg-synapse-cyan/20 transition-all">
              + Connect a Repo
            </button>
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {repos.map((r) => (
              <div
                key={r.id}
                onClick={() => r.indexed && router.push(`/repo/${r.id}`)}
                className={clsx(
                  "group relative p-5 rounded-xl border bg-synapse-surface transition-all",
                  r.indexed
                    ? "border-synapse-border hover:border-synapse-cyan/40 hover:glow-cyan cursor-pointer"
                    : "border-synapse-border opacity-60 cursor-default"
                )}
              >
                <div className="flex items-start justify-between mb-3">
                  <div className="flex items-center gap-2">
                    {r.source === "github" ? (
                      <Github className="w-4 h-4 text-synapse-muted" />
                    ) : r.source === "new" ? (
                      <Sparkles className="w-4 h-4 text-synapse-cyan" />
                    ) : (
                      <FolderOpen className="w-4 h-4 text-synapse-muted" />
                    )}
                    <span className="font-mono text-sm font-medium text-synapse-text">{r.name}</span>
                  </div>
                  <button
                    onClick={(e) => handleDelete(r.id, e)}
                    className="opacity-0 group-hover:opacity-100 text-synapse-muted hover:text-red-400 transition-all"
                  >
                    <Trash2 className="w-4 h-4" />
                  </button>
                </div>

                <div className="flex items-center gap-3 text-xs text-synapse-muted font-mono">
                  <span>{r.file_count} files</span>
                  <span>·</span>
                  <span>{r.language}</span>
                </div>

                <div className="mt-3">
                  {r.indexed ? (
                    <span className="flex items-center gap-1.5 text-xs text-synapse-green font-mono">
                      <span className="w-1.5 h-1.5 rounded-full bg-synapse-green animate-pulse" />
                      INDEXED
                    </span>
                  ) : r.indexing_stage === "error" ? (
                    <div className="space-y-1">
                      <span className="flex items-center gap-1.5 text-xs text-red-400 font-mono">
                        <span className="w-1.5 h-1.5 rounded-full bg-red-400" />
                        FAILED
                      </span>
                      <p className="text-[10px] text-red-400/70 font-mono truncate" title={r.indexing_error}>{r.indexing_error}</p>
                    </div>
                  ) : (
                    <div className="space-y-1.5">
                      <div className="flex items-center gap-1.5 text-xs text-synapse-cyan font-mono">
                        <Loader2 className="w-3 h-3 animate-spin shrink-0" />
                        <span className="truncate">{r.indexing_detail || "Queued..."}</span>
                      </div>
                      <div className="h-1 rounded-full bg-synapse-border overflow-hidden">
                        <div
                          className="h-full bg-synapse-cyan transition-all duration-500 ease-out"
                          style={{ width: `${r.indexing_pct ?? 0}%` }}
                        />
                      </div>
                    </div>
                  )}
                </div>

                {r.indexed && (
                  <div className="mt-4 pt-3 border-t border-synapse-border flex gap-3 text-xs text-synapse-muted">
                    <span className="flex items-center gap-1"><Activity className="w-3 h-3" /> Graph</span>
                    <span className="flex items-center gap-1"><Brain className="w-3 h-3" /> Ask AI</span>
                    <span className="flex items-center gap-1"><Zap className="w-3 h-3" /> Health</span>
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </main>

      {/* Add Repo Modal */}
      {showAdd && (
        <div className="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center z-50">
          <div className="w-full max-w-md bg-synapse-surface border border-synapse-border rounded-2xl p-6">
            <h2 className="text-lg font-mono font-semibold text-synapse-text mb-1">Connect Repository</h2>
            <p className="text-synapse-muted text-sm mb-5">Index a codebase for AI analysis.</p>

            <div className="flex gap-2 mb-5">
              {(["local", "github", "new"] as const).map((t) => (
                <button
                  key={t}
                  onClick={() => setAddType(t)}
                  className={clsx(
                    "flex-1 py-2 rounded-lg border text-sm font-mono transition-all",
                    addType === t
                      ? "border-synapse-cyan/50 bg-synapse-cyan/10 text-synapse-cyan"
                      : "border-synapse-border text-synapse-muted hover:border-synapse-border/80"
                  )}
                >
                  {t === "local" ? "Local Path" : t === "github" ? "GitHub" : "New Project"}
                </button>
              ))}
            </div>

            <div className="space-y-3">
              {addType === "new" ? (
                <>
                  <input
                    placeholder="Project name"
                    value={repoName}
                    onChange={(e) => setRepoName(e.target.value)}
                    className="w-full px-4 py-2.5 bg-synapse-bg border border-synapse-border rounded-lg text-synapse-text font-mono text-sm placeholder:text-synapse-muted focus:outline-none focus:border-synapse-cyan/50"
                  />
                  <textarea
                    placeholder="Describe what you want to build — e.g. 'a todo list app with SQLite persistence, add/complete/delete tasks, and a simple web UI'"
                    value={projectDescription}
                    onChange={(e) => setProjectDescription(e.target.value)}
                    rows={4}
                    className="w-full px-4 py-2.5 bg-synapse-bg border border-synapse-border rounded-lg text-synapse-text text-sm placeholder:text-synapse-muted focus:outline-none focus:border-synapse-cyan/50 resize-none"
                  />
                  <div className="flex items-start gap-2 px-1 py-1 text-xs text-synapse-muted leading-relaxed">
                    <Sparkles className="w-3.5 h-3.5 shrink-0 mt-0.5 text-synapse-cyan" />
                    Synapse will scaffold the project from nothing and keep building — structure,
                    dependencies, entry point, data layer — iterating on its own until it's a real,
                    working project. This can take several minutes.
                  </div>
                </>
              ) : addType === "local" ? (
                <>
                  <input
                    placeholder="/path/to/your/repo"
                    value={localPath}
                    onChange={(e) => setLocalPath(e.target.value)}
                    className="w-full px-4 py-2.5 bg-synapse-bg border border-synapse-border rounded-lg text-synapse-text font-mono text-sm placeholder:text-synapse-muted focus:outline-none focus:border-synapse-cyan/50"
                  />
                  <label className="flex items-start gap-2.5 px-1 py-1 cursor-pointer group">
                    <input
                      type="checkbox"
                      checked={inPlace}
                      onChange={(e) => setInPlace(e.target.checked)}
                      className="mt-0.5 accent-synapse-cyan"
                    />
                    <span className="text-xs text-synapse-muted group-hover:text-synapse-text transition-colors">
                      Edit in place — let the implement agent write directly to this path instead of a sandboxed copy.
                    </span>
                  </label>
                </>
              ) : (
                <>
                  <input
                    placeholder="https://github.com/user/repo"
                    value={ghUrl}
                    onChange={(e) => setGhUrl(e.target.value)}
                    className="w-full px-4 py-2.5 bg-synapse-bg border border-synapse-border rounded-lg text-synapse-text font-mono text-sm placeholder:text-synapse-muted focus:outline-none focus:border-synapse-cyan/50"
                  />
                  <input
                    placeholder="GitHub Personal Access Token"
                    type="password"
                    value={ghPat}
                    onChange={(e) => setGhPat(e.target.value)}
                    className="w-full px-4 py-2.5 bg-synapse-bg border border-synapse-border rounded-lg text-synapse-text font-mono text-sm placeholder:text-synapse-muted focus:outline-none focus:border-synapse-cyan/50"
                  />
                </>
              )}
              {addType !== "new" && (
                <input
                  placeholder="Name (optional)"
                  value={repoName}
                  onChange={(e) => setRepoName(e.target.value)}
                  className="w-full px-4 py-2.5 bg-synapse-bg border border-synapse-border rounded-lg text-synapse-text font-mono text-sm placeholder:text-synapse-muted focus:outline-none focus:border-synapse-cyan/50"
                />
              )}
            </div>

            {error && <p className="text-red-400 text-xs font-mono mt-3">{error}</p>}

            <div className="flex gap-3 mt-6">
              <button
                onClick={() => { setShowAdd(false); setError(""); }}
                className="flex-1 py-2.5 border border-synapse-border rounded-lg text-synapse-muted text-sm font-mono hover:border-synapse-muted/50 transition-all"
              >
                Cancel
              </button>
              <button
                onClick={handleAdd}
                disabled={adding || (addType === "new" && (!repoName.trim() || !projectDescription.trim()))}
                className="flex-1 py-2.5 bg-synapse-cyan/10 border border-synapse-cyan/40 rounded-lg text-synapse-cyan text-sm font-mono hover:bg-synapse-cyan/20 transition-all disabled:opacity-50 flex items-center justify-center gap-2"
              >
                {adding
                  ? <><Loader2 className="w-4 h-4 animate-spin" /> {addType === "new" ? "Starting..." : "Connecting..."}</>
                  : addType === "new" ? "Start Building" : "Connect"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
