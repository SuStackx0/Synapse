import ast
import os
from pathlib import Path
from typing import List, Dict, Any
import structlog

logger = structlog.get_logger()

SUPPORTED_EXTENSIONS = {".py", ".js", ".ts", ".tsx", ".jsx"}


def parse_python_file(path: str, content: str) -> Dict[str, Any]:
    """Extract functions, classes, imports from a Python file via AST."""
    nodes = {"functions": [], "classes": [], "imports": [], "calls": []}
    try:
        tree = ast.parse(content)
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                nodes["functions"].append({
                    "name": node.name,
                    "lineno": node.lineno,
                    "end_lineno": node.end_lineno,
                    "args": [a.arg for a in node.args.args],
                    "docstring": ast.get_docstring(node) or "",
                })
            elif isinstance(node, ast.ClassDef):
                methods = [
                    n.name for n in ast.walk(node)
                    if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef)
                ]
                nodes["classes"].append({
                    "name": node.name,
                    "lineno": node.lineno,
                    "methods": methods,
                    "docstring": ast.get_docstring(node) or "",
                })
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    nodes["imports"].append(alias.name)
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    nodes["imports"].append(node.module)
            elif isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name):
                    nodes["calls"].append(node.func.id)
                elif isinstance(node.func, ast.Attribute):
                    nodes["calls"].append(node.func.attr)
    except SyntaxError as e:
        logger.warning("parse_error", path=path, error=str(e))
    return nodes


def parse_js_file_basic(path: str, content: str) -> Dict[str, Any]:
    """Basic regex-based JS/TS parser for function/class extraction."""
    import re
    nodes = {"functions": [], "classes": [], "imports": [], "calls": []}
    func_pattern = re.compile(r'(?:function\s+(\w+)|const\s+(\w+)\s*=\s*(?:async\s*)?\(|(\w+)\s*:\s*(?:async\s*)?\()')
    class_pattern = re.compile(r'class\s+(\w+)')
    import_pattern = re.compile(r"import\s+.*?from\s+['\"](.+?)['\"]")

    for m in func_pattern.finditer(content):
        name = m.group(1) or m.group(2) or m.group(3)
        if name:
            nodes["functions"].append({"name": name, "lineno": content[:m.start()].count("\n") + 1})
    for m in class_pattern.finditer(content):
        nodes["classes"].append({"name": m.group(1), "lineno": content[:m.start()].count("\n") + 1})
    for m in import_pattern.finditer(content):
        nodes["imports"].append(m.group(1))
    return nodes


def parse_file(path: str) -> Dict[str, Any]:
    ext = Path(path).suffix
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()
    except Exception:
        return {"functions": [], "classes": [], "imports": [], "calls": [], "content": ""}

    if ext == ".py":
        parsed = parse_python_file(path, content)
    elif ext in {".js", ".ts", ".tsx", ".jsx"}:
        parsed = parse_js_file_basic(path, content)
    else:
        parsed = {"functions": [], "classes": [], "imports": [], "calls": []}

    parsed["content"] = content
    parsed["path"] = path
    parsed["language"] = "python" if ext == ".py" else "javascript"
    return parsed


def walk_repo(repo_path: str, max_files: int = 500) -> List[Dict[str, Any]]:
    results = []
    skip_dirs = {".git", "node_modules", "__pycache__", ".venv", "venv", "dist", "build", ".next"}
    for root, dirs, files in os.walk(repo_path):
        dirs[:] = [d for d in dirs if d not in skip_dirs]
        for fname in files:
            if len(results) >= max_files:
                break
            fpath = os.path.join(root, fname)
            if Path(fname).suffix in SUPPORTED_EXTENSIONS:
                parsed = parse_file(fpath)
                parsed["rel_path"] = os.path.relpath(fpath, repo_path)
                results.append(parsed)
    return results
