import ast
import os
from pathlib import Path
from typing import List, Dict, Any, Optional
import structlog

logger = structlog.get_logger()

SUPPORTED_EXTENSIONS = {".py", ".js", ".ts", ".tsx", ".jsx"}


def _first_sentence(doc: str, max_words: int = 12) -> str:
    if not doc:
        return ""
    sentence = doc.split(".")[0].strip()
    words = sentence.split()
    return " ".join(words[:max_words])


def _name_redundant(doc: str, qualname: str) -> bool:
    """True if the doc adds no info beyond the function name."""
    name_words = set(qualname.lower().replace("_", " ").replace(".", " ").split())
    doc_words = set(doc.lower().split())
    overlap = doc_words & name_words
    return len(overlap) >= len(doc_words) * 0.6 if doc_words else True


class PythonVisitor(ast.NodeVisitor):
    """Walks a Python AST and collects structured symbol info per scope."""

    def __init__(self, source_lines: List[str]):
        self.source_lines = source_lines
        self.functions: List[Dict] = []
        self.classes: List[Dict] = []
        self.imports: List[str] = []
        self.decorators: List[str] = []
        self._class_stack: List[str] = []

    def visit_Import(self, node: ast.Import):
        for alias in node.names:
            self.imports.append(alias.name)

    def visit_ImportFrom(self, node: ast.ImportFrom):
        if node.module:
            self.imports.append(node.module)

    def _get_decorator_names(self, node) -> List[str]:
        decos = []
        for d in node.decorator_list:
            if isinstance(d, ast.Name):
                decos.append(d.id)
            elif isinstance(d, ast.Attribute):
                decos.append(f"{ast.unparse(d)}")
            elif isinstance(d, ast.Call):
                if isinstance(d.func, ast.Attribute):
                    decos.append(ast.unparse(d.func))
                elif isinstance(d.func, ast.Name):
                    decos.append(d.func.id)
        return decos

    def _collect_calls(self, node) -> List[str]:
        """Collect function calls within a specific node scope (not whole tree)."""
        calls = []
        for child in ast.walk(node):
            if isinstance(child, ast.Call):
                if isinstance(child.func, ast.Name):
                    calls.append(child.func.id)
                elif isinstance(child.func, ast.Attribute):
                    calls.append(child.func.attr)
        return list(set(calls))

    def _collect_raises(self, node) -> List[str]:
        raises = []
        for child in ast.walk(node):
            if isinstance(child, ast.Raise) and child.exc:
                if isinstance(child.exc, ast.Call):
                    if isinstance(child.exc.func, ast.Name):
                        raises.append(child.exc.func.id)
                    elif isinstance(child.exc.func, ast.Attribute):
                        raises.append(child.exc.func.attr)
                elif isinstance(child.exc, ast.Name):
                    raises.append(child.exc.id)
        return list(set(raises))

    def _return_annotation(self, node) -> str:
        if node.returns:
            try:
                return ast.unparse(node.returns)
            except Exception:
                return ""
        return ""

    def _build_sig(self, node) -> str:
        try:
            args = []
            for arg in node.args.args:
                ann = f":{ast.unparse(arg.annotation)}" if arg.annotation else ""
                args.append(f"{arg.arg}{ann}")
            ret = self._return_annotation(node)
            ret_str = f"->{ret}" if ret else ""
            prefix = "async " if isinstance(node, ast.AsyncFunctionDef) else ""
            return f"{prefix}({', '.join(args)}){ret_str}"
        except Exception:
            return ""

    def visit_ClassDef(self, node: ast.ClassDef):
        raw_doc = ast.get_docstring(node) or ""
        doc = _first_sentence(raw_doc)
        qualname = ".".join(self._class_stack + [node.name])
        if _name_redundant(doc, qualname):
            doc = ""

        bases = []
        for b in node.bases:
            try:
                bases.append(ast.unparse(b))
            except Exception:
                pass

        decos = self._get_decorator_names(node)
        fields = []
        for item in node.body:
            if isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name):
                try:
                    fields.append(f"{item.target.id}:{ast.unparse(item.annotation)}")
                except Exception:
                    fields.append(item.target.id)

        self.classes.append({
            "name": node.name,
            "qualname": qualname,
            "lineno": node.lineno,
            "end_lineno": node.end_lineno,
            "doc": doc,
            "doc_src": "authored" if raw_doc else "",
            "bases": bases,
            "decorators": decos,
            "fields": fields,
            "parent_class": self._class_stack[-1] if self._class_stack else None,
        })

        self._class_stack.append(node.name)
        self.generic_visit(node)
        self._class_stack.pop()

    def _visit_func(self, node):
        raw_doc = ast.get_docstring(node) or ""
        doc = _first_sentence(raw_doc)
        qualname = ".".join(self._class_stack + [node.name])
        if _name_redundant(doc, qualname):
            doc = ""

        is_method = bool(self._class_stack)
        is_test = node.name.startswith("test_") or node.name == "test"
        decos = self._get_decorator_names(node)

        # Detect entrypoints
        is_entry = (
            node.name in {"main", "app", "run", "cli"}
            or any(d in {"router.get", "router.post", "router.put", "router.delete",
                         "router.patch", "app.get", "app.post", "app.put",
                         "app.delete", "app.route", "pytest.fixture"} for d in decos)
        )

        self.functions.append({
            "name": node.name,
            "qualname": qualname,
            "lineno": node.lineno,
            "end_lineno": node.end_lineno,
            "sig": self._build_sig(node),
            "doc": doc,
            "doc_src": "authored" if raw_doc else "",
            "is_async": isinstance(node, ast.AsyncFunctionDef),
            "is_method": is_method,
            "is_test": is_test,
            "is_entrypoint": is_entry,
            "parent_class": self._class_stack[-1] if self._class_stack else None,
            "decorators": decos,
            # calls and raises collected per-function scope:
            "calls": self._collect_calls(node),
            "raises": self._collect_raises(node),
            "loc": (node.end_lineno or node.lineno) - node.lineno,
        })
        # Don't generic_visit — we handle nesting via class stack only for classes
        # (nested functions would need a function stack; skip for now)

    def visit_FunctionDef(self, node: ast.FunctionDef):
        self._visit_func(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef):
        self._visit_func(node)


def parse_python_file(path: str, content: str) -> Dict[str, Any]:
    try:
        tree = ast.parse(content)
    except SyntaxError as e:
        logger.warning("parse_error", path=path, error=str(e))
        return {"functions": [], "classes": [], "imports": [], "calls": []}

    lines = content.splitlines()
    visitor = PythonVisitor(lines)
    visitor.visit(tree)
    return {
        "functions": visitor.functions,
        "classes": visitor.classes,
        "imports": visitor.imports,
        "calls": [],  # top-level calls — not used; per-function calls are in functions[].calls
    }


def parse_js_file_basic(path: str, content: str) -> Dict[str, Any]:
    import re
    functions = []
    classes = []
    imports = []

    func_pattern = re.compile(
        r'(?:export\s+)?(?:async\s+)?function\s+(\w+)\s*\(([^)]*)\)'
        r'|(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s+)?\(([^)]*)\)\s*=>'
        r'|(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s+)?function\s*\('
    )
    class_pattern = re.compile(r'(?:export\s+)?class\s+(\w+)(?:\s+extends\s+(\w+))?')
    import_pattern = re.compile(r"(?:import|require)\s*(?:\{[^}]*\}|\*\s+as\s+\w+|\w+)?\s*from\s*['\"](.+?)['\"]")
    deco_pattern = re.compile(r'@(\w+(?:\.\w+)*)')
    comment_pattern = re.compile(r'/\*\*?\s*(.*?)\s*\*/', re.DOTALL)
    single_comment = re.compile(r'//\s*(.+)')

    for m in func_pattern.finditer(content):
        name = m.group(1) or m.group(3) or m.group(5)
        if not name:
            continue
        lineno = content[:m.start()].count("\n") + 1
        functions.append({
            "name": name, "qualname": name, "lineno": lineno, "end_lineno": lineno,
            "sig": "", "doc": "", "doc_src": "",
            "is_async": "async" in (m.group(0) or ""),
            "is_method": False, "is_test": name.startswith("test"),
            "is_entrypoint": False, "parent_class": None,
            "decorators": [], "calls": [], "raises": [], "loc": 10,
        })

    for m in class_pattern.finditer(content):
        lineno = content[:m.start()].count("\n") + 1
        classes.append({
            "name": m.group(1), "qualname": m.group(1), "lineno": lineno,
            "end_lineno": lineno, "doc": "", "doc_src": "",
            "bases": [m.group(2)] if m.group(2) else [],
            "decorators": [], "fields": [], "parent_class": None,
        })

    for m in import_pattern.finditer(content):
        imports.append(m.group(1))

    return {"functions": functions, "classes": classes, "imports": imports, "calls": []}


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
