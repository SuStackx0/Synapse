"use client";
import { useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import { getProviders, getPresets, createProvider, activateProvider, deleteProvider, Provider } from "@/lib/api";
import { ArrowLeft, Plus, Trash2, CheckCircle, Loader2, Brain, Zap } from "lucide-react";
import { clsx } from "clsx";

const TYPE_LABELS: Record<string, string> = {
  openai: "OpenAI", anthropic: "Anthropic", vllm: "vLLM",
  sglang: "SGLang", ollama: "Ollama", gemma_local: "Gemma (Local)",
};

export default function SettingsPage() {
  const router = useRouter();
  const [providers, setProviders] = useState<Provider[]>([]);
  const [presets, setPresets] = useState<Record<string, { base_url: string; model: string }>>({});
  const [showAdd, setShowAdd] = useState(false);
  const [form, setForm] = useState({ name: "", provider_type: "vllm", base_url: "", api_key: "", model: "" });
  const [saving, setSaving] = useState(false);

  const load = async () => {
    const [ps, pr] = await Promise.all([getProviders(), getPresets()]);
    setProviders(ps);
    setPresets(pr);
  };
  useEffect(() => { load(); }, []);

  const applyPreset = (key: string) => {
    const preset = presets[key];
    if (!preset) return;
    setForm((f) => ({ ...f, provider_type: key, base_url: preset.base_url, model: preset.model, name: TYPE_LABELS[key] || key }));
  };

  const handleSave = async () => {
    setSaving(true);
    try {
      await createProvider(form);
      setShowAdd(false);
      setForm({ name: "", provider_type: "vllm", base_url: "", api_key: "", model: "" });
      load();
    } catch (e) {}
    setSaving(false);
  };

  const activate = async (id: string) => {
    await activateProvider(id);
    load();
  };

  const remove = async (id: string) => {
    await deleteProvider(id);
    load();
  };

  return (
    <div className="min-h-screen">
      <header className="border-b border-synapse-border px-8 py-5 flex items-center gap-4">
        <button onClick={() => router.back()} className="text-synapse-muted hover:text-synapse-text">
          <ArrowLeft className="w-4 h-4" />
        </button>
        <div className="flex items-center gap-2">
          <Brain className="w-4 h-4 text-synapse-cyan" />
          <span className="font-mono font-semibold text-synapse-text">SYNAPSE</span>
        </div>
        <span className="text-synapse-muted text-sm font-mono">/ Settings</span>
      </header>

      <div className="max-w-3xl mx-auto px-8 py-10 space-y-8">
        {/* LLM Providers */}
        <section>
          <div className="flex items-center justify-between mb-4">
            <div>
              <h2 className="text-lg font-mono font-semibold text-synapse-text">LLM Providers</h2>
              <p className="text-sm text-synapse-muted">Connect any OpenAI-compatible endpoint. One active at a time.</p>
            </div>
            <button
              onClick={() => setShowAdd(!showAdd)}
              className="flex items-center gap-2 px-4 py-2 border border-synapse-cyan/30 bg-synapse-cyan/10 text-synapse-cyan text-sm font-mono rounded-lg hover:bg-synapse-cyan/20 transition-all"
            >
              <Plus className="w-4 h-4" /> Add Provider
            </button>
          </div>

          {/* Add form */}
          {showAdd && (
            <div className="mb-6 bg-synapse-surface border border-synapse-border rounded-xl p-5 space-y-4">
              <div>
                <p className="text-xs font-mono text-synapse-muted mb-2 uppercase">Presets</p>
                <div className="flex flex-wrap gap-2">
                  {Object.keys(presets).map((key) => (
                    <button
                      key={key}
                      onClick={() => applyPreset(key)}
                      className={clsx(
                        "px-3 py-1.5 rounded-lg border text-xs font-mono transition-all",
                        form.provider_type === key
                          ? "border-synapse-cyan/40 bg-synapse-cyan/10 text-synapse-cyan"
                          : "border-synapse-border text-synapse-muted hover:border-synapse-muted"
                      )}
                    >
                      {TYPE_LABELS[key] || key}
                    </button>
                  ))}
                </div>
              </div>
              <div className="grid grid-cols-2 gap-3">
                {[
                  { label: "Name", key: "name", placeholder: "My Provider" },
                  { label: "Model ID", key: "model", placeholder: "gpt-4o / gemma4 / ..." },
                  { label: "Base URL", key: "base_url", placeholder: "https://api.openai.com/v1" },
                  { label: "API Key", key: "api_key", placeholder: "sk-... (leave empty for local)" },
                ].map(({ label, key, placeholder }) => (
                  <div key={key}>
                    <label className="text-xs font-mono text-synapse-muted uppercase mb-1 block">{label}</label>
                    <input
                      value={(form as any)[key]}
                      onChange={(e) => setForm((f) => ({ ...f, [key]: e.target.value }))}
                      placeholder={placeholder}
                      type={key === "api_key" ? "password" : "text"}
                      className="w-full px-3 py-2 bg-synapse-bg border border-synapse-border rounded-lg text-synapse-text font-mono text-sm placeholder:text-synapse-muted/50 focus:outline-none focus:border-synapse-cyan/50"
                    />
                  </div>
                ))}
              </div>
              <div className="flex gap-3">
                <button onClick={() => setShowAdd(false)} className="px-4 py-2 border border-synapse-border rounded-lg text-synapse-muted text-sm font-mono">Cancel</button>
                <button onClick={handleSave} disabled={saving} className="px-4 py-2 bg-synapse-cyan/10 border border-synapse-cyan/40 rounded-lg text-synapse-cyan text-sm font-mono flex items-center gap-2 disabled:opacity-50">
                  {saving ? <Loader2 className="w-4 h-4 animate-spin" /> : null} Save Provider
                </button>
              </div>
            </div>
          )}

          {/* Provider list */}
          <div className="space-y-3">
            {providers.length === 0 && (
              <div className="text-center py-10 border border-dashed border-synapse-border rounded-xl">
                <Zap className="w-8 h-8 text-synapse-muted mx-auto mb-3" />
                <p className="text-synapse-muted text-sm font-mono">No providers yet. Add one above.</p>
                <p className="text-synapse-muted/50 text-xs mt-1">Default: Gemma 26 via vLLM at 10.29.210.8</p>
              </div>
            )}
            {providers.map((p) => (
              <div key={p.id} className={clsx(
                "flex items-center gap-4 p-4 rounded-xl border transition-all",
                p.is_active ? "border-synapse-green/40 bg-synapse-green/5" : "border-synapse-border bg-synapse-surface"
              )}>
                <div className="flex-1">
                  <div className="flex items-center gap-2">
                    <span className="font-mono text-sm font-semibold text-synapse-text">{p.name}</span>
                    {p.is_active && (
                      <span className="flex items-center gap-1 text-xs text-synapse-green font-mono">
                        <span className="w-1.5 h-1.5 rounded-full bg-synapse-green animate-pulse" /> ACTIVE
                      </span>
                    )}
                  </div>
                  <div className="text-xs text-synapse-muted font-mono mt-0.5">
                    {p.model} · {p.base_url}
                  </div>
                </div>
                <div className="flex items-center gap-2">
                  {!p.is_active && (
                    <button
                      onClick={() => activate(p.id)}
                      className="px-3 py-1.5 border border-synapse-border text-xs font-mono text-synapse-muted rounded-lg hover:border-synapse-green/40 hover:text-synapse-green transition-all"
                    >
                      Set Active
                    </button>
                  )}
                  <button onClick={() => remove(p.id)} className="text-synapse-muted hover:text-red-400 transition-colors">
                    <Trash2 className="w-4 h-4" />
                  </button>
                </div>
              </div>
            ))}
          </div>
        </section>
      </div>
    </div>
  );
}
