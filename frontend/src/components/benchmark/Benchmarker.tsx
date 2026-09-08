"use client";
import { useEffect, useState } from "react";
import { getProviders, runBenchmark, voteBenchmark, Provider, BenchmarkResult } from "@/lib/api";
import { Loader2, Scale, Zap, ThumbsUp, Clock } from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

export default function Benchmarker({ repoId }: { repoId: string }) {
  const [providers, setProviders] = useState<Provider[]>([]);
  const [provA, setProvA] = useState("");
  const [provB, setProvB] = useState("");
  const [query, setQuery] = useState("");
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<BenchmarkResult | null>(null);
  const [voted, setVoted] = useState<"a" | "b" | null>(null);
  const [error, setError] = useState("");

  useEffect(() => { getProviders().then(setProviders); }, []);

  const run = async () => {
    if (!provA || !provB || !query.trim()) return;
    setRunning(true);
    setResult(null);
    setVoted(null);
    setError("");
    try {
      const res = await runBenchmark({ repo_id: repoId, query, provider_a_id: provA, provider_b_id: provB });
      setResult(res);
    } catch (e: any) {
      setError(e.message);
    }
    setRunning(false);
  };

  const vote = async (winner: "a" | "b") => {
    if (!result || voted) return;
    await voteBenchmark(result.id, winner);
    setVoted(winner);
  };

  const providerName = (id: string) => providers.find((p) => p.id === id)?.name || id;

  if (providers.length < 2) return (
    <div className="flex flex-col items-center justify-center h-full gap-4 text-center">
      <Scale className="w-12 h-12 text-synapse-border" />
      <div>
        <p className="text-synapse-muted font-mono text-sm">Need at least 2 LLM providers to benchmark.</p>
        <a href="/settings" className="text-synapse-cyan text-xs font-mono underline mt-1 inline-block">Add providers in Settings →</a>
      </div>
    </div>
  );

  return (
    <div className="h-full overflow-y-auto p-6">
      <div className="max-w-5xl mx-auto space-y-6">
        <div>
          <h2 className="text-xl font-mono font-bold text-synapse-text mb-1">Model Benchmarker</h2>
          <p className="text-synapse-muted text-sm">Compare two LLM providers on your actual codebase. Rate the winner.</p>
        </div>

        {/* Config */}
        <div className="bg-synapse-surface border border-synapse-border rounded-xl p-5 space-y-4">
          <div className="grid grid-cols-2 gap-4">
            {[
              { label: "Provider A", val: provA, set: setProvA },
              { label: "Provider B", val: provB, set: setProvB },
            ].map(({ label, val, set }) => (
              <div key={label}>
                <label className="text-xs font-mono text-synapse-muted uppercase mb-1.5 block">{label}</label>
                <select
                  value={val}
                  onChange={(e) => set(e.target.value)}
                  className="w-full px-3 py-2.5 bg-synapse-bg border border-synapse-border rounded-lg text-synapse-text font-mono text-sm focus:outline-none focus:border-synapse-cyan/50"
                >
                  <option value="">Select provider...</option>
                  {providers.map((p) => (
                    <option key={p.id} value={p.id}>{p.name} ({p.model})</option>
                  ))}
                </select>
              </div>
            ))}
          </div>
          <div>
            <label className="text-xs font-mono text-synapse-muted uppercase mb-1.5 block">Query</label>
            <textarea
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Ask something about the codebase that both models will answer..."
              rows={3}
              className="w-full px-4 py-3 bg-synapse-bg border border-synapse-border rounded-lg text-synapse-text font-mono text-sm resize-none focus:outline-none focus:border-synapse-cyan/50 placeholder:text-synapse-muted/50"
            />
          </div>
          <button
            onClick={run}
            disabled={running || !provA || !provB || !query.trim()}
            className="flex items-center gap-2 px-5 py-2.5 bg-yellow-400/10 border border-yellow-400/40 rounded-lg text-yellow-400 font-mono text-sm hover:bg-yellow-400/20 transition-all disabled:opacity-40"
          >
            {running ? <><Loader2 className="w-4 h-4 animate-spin" /> Running both models...</> : <><Zap className="w-4 h-4" /> Run Benchmark</>}
          </button>
          {error && <p className="text-red-400 text-xs font-mono">{error}</p>}
        </div>

        {/* Results */}
        {result && (
          <div className="space-y-4">
            <div className="grid grid-cols-2 gap-4">
              {(["a", "b"] as const).map((side) => {
                const response = side === "a" ? result.response_a : result.response_b;
                const latency = side === "a" ? result.latency_a : result.latency_b;
                const id = side === "a" ? provA : provB;
                const isWinner = voted === side;
                return (
                  <div
                    key={side}
                    className={`bg-synapse-surface border rounded-xl overflow-hidden transition-all ${
                      isWinner ? "border-synapse-green/50 glow-green" : "border-synapse-border"
                    }`}
                  >
                    <div className="px-4 py-3 border-b border-synapse-border flex items-center justify-between">
                      <div>
                        <span className="text-xs font-mono text-synapse-muted uppercase">{side === "a" ? "Model A" : "Model B"}</span>
                        <p className="text-sm font-mono text-synapse-text font-semibold">{providerName(id)}</p>
                      </div>
                      <div className="flex items-center gap-1.5 text-xs text-synapse-muted font-mono">
                        <Clock className="w-3 h-3" /> {latency}s
                      </div>
                    </div>
                    <div className="p-4 max-h-64 overflow-y-auto prose prose-invert prose-sm">
                      <ReactMarkdown remarkPlugins={[remarkGfm]}>{response}</ReactMarkdown>
                    </div>
                    <div className="px-4 py-3 border-t border-synapse-border">
                      <button
                        onClick={() => vote(side)}
                        disabled={!!voted}
                        className={`flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-mono transition-all ${
                          isWinner
                            ? "bg-synapse-green/10 border border-synapse-green/40 text-synapse-green"
                            : "border border-synapse-border text-synapse-muted hover:border-synapse-muted disabled:opacity-40"
                        }`}
                      >
                        <ThumbsUp className="w-3.5 h-3.5" />
                        {isWinner ? "Winner!" : "This one was better"}
                      </button>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
