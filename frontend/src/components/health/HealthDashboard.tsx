"use client";
import { useEffect, useState } from "react";
import { getHealth, HealthData } from "@/lib/api";
import { Loader2, AlertTriangle, CheckCircle, Code, FileText, Layers, Zap } from "lucide-react";

export default function HealthDashboard({ repoId }: { repoId: string }) {
  const [data, setData] = useState<HealthData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    getHealth(repoId)
      .then(setData)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, [repoId]);

  if (loading) return (
    <div className="flex items-center justify-center h-full">
      <div className="text-center">
        <Loader2 className="w-8 h-8 text-synapse-purple animate-spin mx-auto mb-3" />
        <p className="text-synapse-muted font-mono text-sm">Running vibe check...</p>
      </div>
    </div>
  );

  if (error) return (
    <div className="flex items-center justify-center h-full">
      <p className="text-red-400 font-mono text-sm">{error}</p>
    </div>
  );

  if (!data) return null;

  const score = data.score;
  const scoreColor = score >= 80 ? "text-synapse-green" : score >= 60 ? "text-yellow-400" : "text-red-400";
  const scoreBorder = score >= 80 ? "border-synapse-green/40" : score >= 60 ? "border-yellow-400/40" : "border-red-400/40";
  const scoreBg = score >= 80 ? "bg-synapse-green/5" : score >= 60 ? "bg-yellow-400/5" : "bg-red-400/5";
  const scoreLabel = score >= 80 ? "HEALTHY" : score >= 60 ? "NEEDS WORK" : "CRITICAL";

  const totalLangs = Object.values(data.language_breakdown).reduce((a, b) => a + b, 0);

  return (
    <div className="h-full overflow-y-auto p-6">
      <div className="max-w-5xl mx-auto space-y-6">

        {/* Score card */}
        <div className={`flex items-center gap-6 p-6 rounded-2xl border ${scoreBorder} ${scoreBg}`}>
          <div className="text-center">
            <div className={`text-6xl font-bold font-mono ${scoreColor}`}>{score}</div>
            <div className="text-xs font-mono text-synapse-muted mt-1">/ 100</div>
          </div>
          <div>
            <div className={`text-sm font-mono font-semibold ${scoreColor}`}>{scoreLabel}</div>
            <p className="text-synapse-muted text-sm mt-1">
              {score >= 80
                ? "Codebase looks clean. Good engineering habits."
                : score >= 60
                ? "Some complexity and dead code detected. Consider a cleanup pass."
                : "High complexity, many large files. Refactoring recommended."}
            </p>
          </div>
          <div className="ml-auto">
            {score >= 80 ? <CheckCircle className="w-10 h-10 text-synapse-green" /> : <AlertTriangle className="w-10 h-10 text-yellow-400" />}
          </div>
        </div>

        {/* Stats row */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          {[
            { label: "Files", value: data.total_files, icon: FileText, color: "synapse-cyan" },
            { label: "Lines of Code", value: data.total_lines.toLocaleString(), icon: Code, color: "synapse-green" },
            { label: "Functions", value: data.total_functions, icon: Zap, color: "synapse-purple" },
            { label: "Classes", value: data.total_classes, icon: Layers, color: "yellow-400" },
          ].map(({ label, value, icon: Icon, color }) => (
            <div key={label} className="bg-synapse-surface border border-synapse-border rounded-xl p-4">
              <div className={`flex items-center gap-2 text-${color} mb-2`}>
                <Icon className="w-4 h-4" />
                <span className="text-xs font-mono text-synapse-muted uppercase tracking-wider">{label}</span>
              </div>
              <div className={`text-2xl font-bold font-mono text-${color}`}>{value}</div>
            </div>
          ))}
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          {/* Language breakdown */}
          <div className="bg-synapse-surface border border-synapse-border rounded-xl p-5">
            <h3 className="text-sm font-mono font-semibold text-synapse-text mb-4">Language Breakdown</h3>
            <div className="space-y-3">
              {Object.entries(data.language_breakdown).map(([lang, count]) => {
                const pct = Math.round((count / totalLangs) * 100);
                return (
                  <div key={lang}>
                    <div className="flex justify-between text-xs font-mono mb-1">
                      <span className="text-synapse-text capitalize">{lang}</span>
                      <span className="text-synapse-muted">{count} files ({pct}%)</span>
                    </div>
                    <div className="h-1.5 bg-synapse-border rounded-full overflow-hidden">
                      <div
                        className="h-full bg-synapse-cyan rounded-full transition-all duration-700"
                        style={{ width: `${pct}%` }}
                      />
                    </div>
                  </div>
                );
              })}
            </div>
          </div>

          {/* Large files */}
          <div className="bg-synapse-surface border border-synapse-border rounded-xl p-5">
            <h3 className="text-sm font-mono font-semibold text-synapse-text mb-1">Complexity Hotspots</h3>
            <p className="text-xs text-synapse-muted mb-4">Files over 300 lines — consider splitting.</p>
            {data.large_files.length === 0 ? (
              <div className="flex items-center gap-2 text-synapse-green text-sm font-mono">
                <CheckCircle className="w-4 h-4" /> No large files detected
              </div>
            ) : (
              <div className="space-y-2">
                {data.large_files.map((f, i) => (
                  <div key={i} className="flex items-center justify-between py-1.5 border-b border-synapse-border/50">
                    <span className="text-xs font-mono text-synapse-text truncate max-w-[70%]">{f.file}</span>
                    <span className="text-xs font-mono text-yellow-400">{f.lines} lines</span>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>

        {/* Potentially dead code */}
        {data.potentially_dead_functions.length > 0 && (
          <div className="bg-synapse-surface border border-synapse-border rounded-xl p-5">
            <div className="flex items-center gap-2 mb-1">
              <AlertTriangle className="w-4 h-4 text-yellow-400" />
              <h3 className="text-sm font-mono font-semibold text-synapse-text">Potentially Unused Functions</h3>
            </div>
            <p className="text-xs text-synapse-muted mb-4">Not found in call graph — may be dead code or entry points.</p>
            <div className="grid grid-cols-2 gap-2">
              {data.potentially_dead_functions.map((fn, i) => (
                <div key={i} className="flex flex-col p-2 rounded-lg bg-synapse-bg border border-synapse-border">
                  <span className="text-xs font-mono text-synapse-purple">{fn.name}</span>
                  <span className="text-xs text-synapse-muted truncate">{fn.file}</span>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
