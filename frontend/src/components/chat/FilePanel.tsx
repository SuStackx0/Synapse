"use client";
import { useEffect, useState, useCallback } from "react";
import CodeMirror from "@uiw/react-codemirror";
import { python } from "@codemirror/lang-python";
import { javascript } from "@codemirror/lang-javascript";
import { oneDark } from "@codemirror/theme-one-dark";
import { X, Save, FileCode, Loader2, Check, AlertCircle } from "lucide-react";
import { clsx } from "clsx";
import { getFileContent, saveFileContent } from "@/lib/api";

function langExtension(path: string) {
  if (path.endsWith(".py")) return [python()];
  if (/\.(ts|tsx|js|jsx)$/.test(path)) return [javascript({ jsx: /\.(tsx|jsx)$/.test(path), typescript: /\.tsx?$/.test(path) })];
  return [];
}

interface FilePanelProps {
  repoId: string;
  path: string;
  initialContent?: string;
  onClose: () => void;
}

export default function FilePanel({ repoId, path, initialContent, onClose }: FilePanelProps) {
  const [content, setContent] = useState(initialContent ?? "");
  const [original, setOriginal] = useState(initialContent ?? "");
  const [loading, setLoading] = useState(!initialContent);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    setLoading(!initialContent);
    setError("");
    setSaved(false);
    if (initialContent !== undefined) {
      setContent(initialContent);
      setOriginal(initialContent);
    }
    (async () => {
      try {
        const res = await getFileContent(repoId, path);
        if (!cancelled) {
          setContent(res.content);
          setOriginal(res.content);
        }
      } catch (e: any) {
        if (!cancelled) setError(e.message || "Could not load file");
      }
      if (!cancelled) setLoading(false);
    })();
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [repoId, path]);

  const dirty = content !== original;

  const handleSave = useCallback(async () => {
    setSaving(true);
    setError("");
    try {
      await saveFileContent(repoId, path, content);
      setOriginal(content);
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
    } catch (e: any) {
      setError(e.message || "Save failed");
    }
    setSaving(false);
  }, [repoId, path, content]);

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === "s") {
        e.preventDefault();
        if (dirty && !saving) handleSave();
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [dirty, saving, handleSave]);

  const fileName = path.split("/").pop() || path;
  const dirName = path.split("/").slice(0, -1).join("/");

  return (
    <div className="w-full h-full flex flex-col bg-synapse-bg">
      <div className="flex items-center gap-3 px-4 py-3 border-b border-synapse-border shrink-0">
        <FileCode className="w-4 h-4 text-synapse-cyan shrink-0" />
        <div className="min-w-0 flex-1">
          <div className="flex items-baseline gap-1.5 font-mono text-sm">
            <span className="text-synapse-text truncate">{fileName}</span>
            {dirty && <span className="w-1.5 h-1.5 rounded-full bg-synapse-cyan shrink-0" title="Unsaved changes" />}
          </div>
          {dirName && <p className="text-[10px] text-synapse-muted/60 font-mono truncate">{dirName}/</p>}
        </div>
        <div className="flex items-center gap-2 shrink-0">
          {error && (
            <span className="flex items-center gap-1 text-[11px] font-mono text-red-400">
              <AlertCircle className="w-3 h-3" /> {error}
            </span>
          )}
          {saved && !error && (
            <span className="flex items-center gap-1 text-[11px] font-mono text-synapse-green">
              <Check className="w-3 h-3" /> Saved
            </span>
          )}
          <button
            onClick={handleSave}
            disabled={!dirty || saving}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-synapse-cyan/10 border border-synapse-cyan/30 text-synapse-cyan text-xs font-mono hover:bg-synapse-cyan/20 transition-all disabled:opacity-30 disabled:cursor-default"
          >
            {saving ? <Loader2 className="w-3 h-3 animate-spin" /> : <Save className="w-3 h-3" />}
            Save
          </button>
          <button onClick={onClose} className="text-synapse-muted hover:text-synapse-text transition-colors p-1">
            <X className="w-4 h-4" />
          </button>
        </div>
      </div>

      <div className="flex-1 overflow-hidden relative">
        {loading ? (
          <div className="h-full flex items-center justify-center">
            <Loader2 className="w-5 h-5 animate-spin text-synapse-muted" />
          </div>
        ) : (
          <CodeMirror
            value={content}
            onChange={setContent}
            theme={oneDark}
            extensions={langExtension(path)}
            height="100%"
            basicSetup={{ lineNumbers: true, foldGutter: true, highlightActiveLine: true }}
            style={{ height: "100%", fontSize: "13px" }}
            className="h-full [&_.cm-editor]:h-full [&_.cm-scroller]:font-mono"
          />
        )}
      </div>

      <div className="px-4 py-1.5 border-t border-synapse-border text-[10px] font-mono text-synapse-muted/50 flex items-center justify-between shrink-0">
        <span>{content.split("\n").length} lines</span>
        <span>⌘S to save</span>
      </div>
    </div>
  );
}
