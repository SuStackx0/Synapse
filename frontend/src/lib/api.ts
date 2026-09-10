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
export const addLocalRepo = (path: string, name?: string, inPlace?: boolean) =>
  apiFetch("/repos/local", { method: "POST", body: JSON.stringify({ path, name, in_place: !!inPlace }) });
export const addGithubRepo = (url: string, pat: string, name?: string) =>
  apiFetch("/repos/github", { method: "POST", body: JSON.stringify({ url, pat, name }) });
export const createNewProject = (name: string, description: string, inPlace?: boolean, path?: string) =>
  apiFetch("/repos/new", { method: "POST", body: JSON.stringify({ name, description, in_place: !!inPlace, path }) });
export const deleteRepo = (id: string) => apiFetch(`/repos/${id}`, { method: "DELETE" });

// Graph
export const getGraph = (repoId: string) => apiFetch<GraphData>(`/graph/${repoId}`);
export const getGraphNode = (repoId: string, nodeUid: string) =>
  apiFetch(`/graph/${repoId}/node/${encodeURIComponent(nodeUid)}`);

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

// Sessions
export const getSessions = (repoId: string) =>
  apiFetch<ChatSessionInfo[]>(`/sessions/?repo_id=${encodeURIComponent(repoId)}`);
export const createSession = (repoId: string, title?: string) =>
  apiFetch<ChatSessionInfo>("/sessions/", { method: "POST", body: JSON.stringify({ repo_id: repoId, title }) });
export const getSessionMessages = (sessionId: string) =>
  apiFetch<ChatMessageInfo[]>(`/sessions/${sessionId}/messages`);
export const deleteSession = (sessionId: string) =>
  apiFetch(`/sessions/${sessionId}`, { method: "DELETE" });

// File content (side-panel editor)
export const getFileContent = (repoId: string, path: string) =>
  apiFetch<FileContent>(`/repos/${repoId}/file?path=${encodeURIComponent(path)}`);
export const saveFileContent = (repoId: string, path: string, content: string) =>
  apiFetch<{ saved: string; lines: number }>(`/repos/${repoId}/file`, {
    method: "PUT", body: JSON.stringify({ path, content }),
  });

// Benchmark
export const runBenchmark = (data: BenchmarkRequest) =>
  apiFetch<BenchmarkResult>("/agents/benchmark", { method: "POST", body: JSON.stringify(data) });
export const voteBenchmark = (benchId: string, winner: "a" | "b") =>
  apiFetch(`/agents/benchmark/${benchId}/vote?winner=${winner}`, { method: "POST" });

// Types
export interface Repo {
  id: string; name: string; source: string; indexed: boolean;
  file_count: number; language: string; created_at: string;
  path?: string;
  indexing_stage?: string;
  indexing_detail?: string;
  indexing_pct?: number;
  indexing_error?: string;
  build_session_id?: string;
}
export interface GraphNode {
  id: string; name: string; type: string; rel_path?: string;
  file_path?: string; lineno?: number;
}
export interface GraphEdge { source: string; target: string; rel: string; }
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
export interface ChatSessionInfo {
  id: string; repo_id: string; title: string; created_at: string; updated_at: string;
}
export interface ChatMessageInfo {
  id: string; session_id: string; role: "user" | "assistant";
  content: string; meta: Record<string, any>; created_at: string;
}
export interface FileContent {
  path: string; content: string; lines: number;
}
