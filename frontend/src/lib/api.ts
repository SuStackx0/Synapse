const BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export async function apiFetch<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!res.ok) {
    const err = await res.text();
    throw new Error(err || res.statusText);
  }
  return res.json();
}

// Repos
export const getRepos = () => apiFetch<Repo[]>("/repos/");
export const getRepo = (id: string) => apiFetch<Repo>(`/repos/${id}`);
export const addLocalRepo = (path: string, name?: string) =>
  apiFetch("/repos/local", { method: "POST", body: JSON.stringify({ path, name }) });
export const addGithubRepo = (url: string, pat: string, name?: string) =>
  apiFetch("/repos/github", { method: "POST", body: JSON.stringify({ url, pat, name }) });
export const deleteRepo = (id: string) => apiFetch(`/repos/${id}`, { method: "DELETE" });

// Graph
export const getGraph = (repoId: string) => apiFetch<GraphData>(`/graph/${repoId}`);
export const getGraphNode = (repoId: string, nodeId: number) =>
  apiFetch(`/graph/${repoId}/node/${nodeId}`);

// Health
export const getHealth = (repoId: string) => apiFetch<HealthData>(`/health/${repoId}`);

// Settings
export const getProviders = () => apiFetch<Provider[]>("/settings/providers");
export const getPresets = () => apiFetch<Record<string, { base_url: string; model: string }>>("/settings/providers/presets");
export const createProvider = (data: ProviderCreate) =>
  apiFetch("/settings/providers", { method: "POST", body: JSON.stringify(data) });
export const activateProvider = (id: string) =>
  apiFetch(`/settings/providers/${id}/activate`, { method: "POST" });
export const deleteProvider = (id: string) =>
  apiFetch(`/settings/providers/${id}`, { method: "DELETE" });

// Benchmark
export const runBenchmark = (data: BenchmarkRequest) =>
  apiFetch<BenchmarkResult>("/agents/benchmark", { method: "POST", body: JSON.stringify(data) });
export const voteBenchmark = (benchId: string, winner: "a" | "b") =>
  apiFetch(`/agents/benchmark/${benchId}/vote?winner=${winner}`, { method: "POST" });

// Chat (streaming)
export async function* streamChat(repoId: string, message: string, agentType: string) {
  const res = await fetch(`${BASE}/agents/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ repo_id: repoId, message, agent_type: agentType }),
  });
  const reader = res.body!.getReader();
  const dec = new TextDecoder();
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    const lines = dec.decode(value).split("\n");
    for (const line of lines) {
      if (line.startsWith("data: ")) {
        try {
          yield JSON.parse(line.slice(6));
        } catch {}
      }
    }
  }
}

// Types
export interface Repo {
  id: string; name: string; source: string; indexed: boolean;
  file_count: number; language: string; created_at: string;
}
export interface GraphNode {
  id: number; name: string; type: string; rel_path?: string;
  file_path?: string; lineno?: number;
}
export interface GraphEdge { source: number; target: number; rel: string; }
export interface GraphData { nodes: GraphNode[]; edges: GraphEdge[]; }
export interface HealthData {
  score: number; total_files: number; total_lines: number;
  total_functions: number; total_classes: number;
  large_files: { file: string; lines: number }[];
  potentially_dead_functions: { name: string; file: string }[];
  language_breakdown: Record<string, number>;
}
export interface Provider {
  id: string; name: string; provider_type: string;
  base_url: string; model: string; is_active: boolean;
}
export interface ProviderCreate {
  name: string; provider_type: string; base_url: string;
  api_key?: string; model: string;
}
export interface BenchmarkRequest {
  repo_id: string; query: string;
  provider_a_id: string; provider_b_id: string;
}
export interface BenchmarkResult {
  id: string; response_a: string; response_b: string;
  latency_a: number; latency_b: number;
}
