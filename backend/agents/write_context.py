"""
Graph-guided context minimization for the write path.

Same philosophy as the read path's retrieve_context: use the graph to
find the minimum slice of the repo the LLM needs, instead of dumping
everything. For writes that means: which directory new code belongs in,
which existing files are the best pattern to copy, and which file wires
new code into the app.
"""
from dataclasses import dataclass, field
from typing import Dict, List, Tuple
import os

from ingestion.graph_builder import graph_builder, serialize_cards_to_sgl


@dataclass
class WriteContext:
    repo_map: str
    placement_dir: str
    exemplars: List[Tuple[str, str]] = field(default_factory=list)   # (rel_path, source)
    wiring_files: List[Tuple[str, str]] = field(default_factory=list)
    imports_by_file: Dict[str, List[str]] = field(default_factory=dict)
    anchors: List[str] = field(default_factory=list)
    roles: List[str] = field(default_factory=list)


def _read_file(repo_root: str, rel_path: str, max_lines: int = 500) -> str:
    abs_path = os.path.join(repo_root, rel_path)
    try:
        with open(abs_path, "r", encoding="utf-8", errors="ignore") as fh:
            lines = fh.readlines()
    except Exception:
        return ""
    if len(lines) > max_lines:
        lines = lines[:max_lines] + [f"\n# ...truncated at {max_lines} lines...\n"]
    return "".join(lines)


async def build_write_context(repo_id: str, repo_root: str, roles: List[str],
                               anchors: List[str], max_exemplars: int = 3,
                               max_body_lines: int = 400) -> WriteContext:
    repo_map = await graph_builder.repo_map(repo_id)

    placement_rows = await graph_builder.find_placement_files(repo_id, roles, limit=8)
    placement_dir = ""
    if placement_rows:
        top_path = placement_rows[0]["path"]
        placement_dir = os.path.dirname(top_path)

    exemplars: List[Tuple[str, str]] = []
    for row in placement_rows[:max_exemplars]:
        src = _read_file(repo_root, row["path"], max_body_lines)
        if src.strip():
            exemplars.append((row["path"], src))

    wiring_rows = await graph_builder.find_wiring_files(repo_id)
    wiring_files: List[Tuple[str, str]] = []
    exemplar_paths = {p for p, _ in exemplars}
    for row in wiring_rows[:2]:
        if row["path"] in exemplar_paths:
            continue
        src = _read_file(repo_root, row["path"], max_body_lines)
        if src.strip():
            wiring_files.append((row["path"], src))

    all_paths = [p for p, _ in exemplars] + [p for p, _ in wiring_files]
    imports_by_file = await graph_builder.file_imports(repo_id, all_paths) if all_paths else {}

    return WriteContext(
        repo_map=repo_map,
        placement_dir=placement_dir,
        exemplars=exemplars,
        wiring_files=wiring_files,
        imports_by_file=imports_by_file,
        anchors=anchors,
        roles=roles,
    )


def render_write_context(wc: WriteContext) -> str:
    parts = [f"### Repository map\n{wc.repo_map}\n"]
    parts.append(f"### Placement — new code likely belongs under: {wc.placement_dir or '(repo root)'}\n")

    for path, src in wc.exemplars:
        imports = wc.imports_by_file.get(path, [])
        imp_line = f"# available imports: {', '.join(imports[:15])}\n" if imports else ""
        parts.append(f"### Exemplar file (existing pattern to follow) — {path}\n{imp_line}```\n{src}\n```\n")

    for path, src in wc.wiring_files:
        parts.append(f"### Wiring file (may need editing to register new code) — {path}\n```\n{src}\n```\n")

    return "\n".join(parts)
