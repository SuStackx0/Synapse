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
      <div className="flex h-14 shrink-0 items-center gap-2.5 border-b border-synapse-border px-4">
        <FileCode className="h-3.5 w-3.5 shrink-0 text-synapse-text-3" />
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-1.5 font-mono text-[12.5px]">
            <span className="truncate text-synapse-text">{fileName}</span>
            {dirty && <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-synapse-amber" title="Unsaved changes" />}
          </div>
          {dirName && <p className="truncate font-mono text-[10.5px] text-synapse-muted">{dirName}/</p>}
        </div>
        <div className="flex items-center gap-2 shrink-0">
          {error && (
            <span className="flex items-center gap-1 text-[11px] text-synapse-red">
              <AlertCircle className="h-3 w-3" /> {error}
            </span>
          )}
          {saved && !error && (
            <span className="flex items-center gap-1 text-[11px] text-synapse-green">
              <Check className="h-3 w-3" /> Saved
            </span>
          )}
          <button
            onClick={handleSave}
            disabled={!dirty || saving}
            className="flex h-7 items-center gap-1.5 rounded-md border border-synapse-border px-2.5 text-[12px] font-medium text-synapse-text-2 transition-colors hover:border-synapse-border-strong hover:text-synapse-text disabled:border-synapse-border-subtle disabled:text-synapse-muted"
          >
            {saving ? <Loader2 className="h-3 w-3 animate-spin" /> : <Save className="h-3 w-3" />}
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

      <div className="flex shrink-0 items-center justify-between border-t border-synapse-border px-4 py-2 text-[10.5px] font-mono text-synapse-muted">
        <span>{content.split("\n").length} lines</span>
        <span>⌘S to save</span>
      </div>
    </div>
  );
}
