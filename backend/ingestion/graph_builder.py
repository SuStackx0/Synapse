"""
Neo4j graph builder.

Architecture principle (per Opus review):
  Graph = structure (navigation, call chains, containment, inheritance)
  Qdrant = meaning (prose only: docstrings, summaries, commit messages)

Every text token that reaches the LLM should come from the graph, not from
raw code chunks. Qdrant returns UIDs; Neo4j returns the serialized context.
"""
from neo4j import AsyncGraphDatabase
from core.config import settings
from typing import List, Dict, Any, Optional
import structlog

logger = structlog.get_logger()

# ── UID helpers ───────────────────────────────────────────────────────────

def file_uid(repo_id: str, rel_path: str) -> str:
    return f"{repo_id}|{rel_path}"


def sym_uid(repo_id: str, rel_path: str, qualname: str) -> str:
    return f"{repo_id}|{rel_path}#{qualname}"


# ── GraphBuilder ──────────────────────────────────────────────────────────

class GraphBuilder:
    def __init__(self):
        self._driver = None

    async def connect(self):
        self._driver = AsyncGraphDatabase.driver(
            settings.neo4j_uri,
            auth=(settings.neo4j_user, settings.neo4j_password),
        )
        await self._ensure_schema()

    async def _ensure_schema(self):
        async with self._driver.session() as s:
            constraints = [
                "CREATE CONSTRAINT sym_uid  IF NOT EXISTS FOR (s:Symbol)    REQUIRE s.uid IS UNIQUE",
                "CREATE CONSTRAINT file_uid IF NOT EXISTS FOR (f:File)      REQUIRE f.uid IS UNIQUE",
                "CREATE CONSTRAINT mod_uid  IF NOT EXISTS FOR (m:Module)    REQUIRE m.uid IS UNIQUE",
            ]
            indexes = [
                "CREATE INDEX sym_name  IF NOT EXISTS FOR (s:Symbol) ON (s.repo_id, s.name)",
                "CREATE INDEX sym_rank  IF NOT EXISTS FOR (s:Symbol) ON (s.repo_id, s.rank)",
                "CREATE INDEX file_path IF NOT EXISTS FOR (f:File)   ON (f.repo_id, f.rel_path)",
            ]
            for stmt in constraints + indexes:
                try:
                    await s.run(stmt)
                except Exception:
                    pass  # may already exist

    async def close(self):
        if self._driver:
            await self._driver.close()

    async def clear_repo(self, repo_id: str):
        async with self._driver.session() as s:
            await s.run("MATCH (n {repo_id: $rid}) DETACH DELETE n", rid=repo_id)

    async def build_graph(self, repo_id: str, parsed_files: List[Dict[str, Any]]):
        await self.clear_repo(repo_id)

        # Build lookup: function name → list of (uid, file_path) for CALLS resolution
        name_to_symbols: Dict[str, List[Dict]] = {}
        for f in parsed_files:
            rel = f.get("rel_path", "")
            for fn in f.get("functions", []):
                uid = sym_uid(repo_id, rel, fn["qualname"])
                name_to_symbols.setdefault(fn["name"], []).append({
                    "uid": uid, "rel_path": rel, "qualname": fn["qualname"],
                    "imports": f.get("imports", []),
                })

        async with self._driver.session() as s:
            # ── File nodes ─────────────────────────────────────────────
            file_rows = [
                {
                    "uid": file_uid(repo_id, f.get("rel_path", "")),
                    "rel_path": f.get("rel_path", ""),
                    "language": f.get("language", "unknown"),
                    "repo_id": repo_id,
                    "loc": len(f.get("content", "").splitlines()),
                }
                for f in parsed_files
            ]
            await s.run(
                """
                UNWIND $rows AS row
                MERGE (file:File {uid: row.uid})
                SET file.rel_path = row.rel_path,
                    file.language = row.language,
                    file.repo_id  = row.repo_id,
                    file.loc      = row.loc
                """,
                rows=file_rows,
            )

            # ── Class nodes ────────────────────────────────────────────
            class_rows = []
            for f in parsed_files:
                rel = f.get("rel_path", "")
                fuid = file_uid(repo_id, rel)
                for cls in f.get("classes", []):
                    uid = sym_uid(repo_id, rel, cls["qualname"])
                    class_rows.append({
                        "uid": uid,
                        "name": cls["name"],
                        "qualname": cls["qualname"],
                        "lineno": cls.get("lineno", 0),
                        "end_lineno": cls.get("end_lineno", 0),
                        "doc": cls.get("doc", ""),
                        "doc_src": cls.get("doc_src", ""),
                        "bases": cls.get("bases", []),
                        "decorators": cls.get("decorators", []),
                        "fields": cls.get("fields", []),
                        "repo_id": repo_id,
                        "rel_path": rel,
                        "file_uid": fuid,
                    })
            if class_rows:
                await s.run(
                    """
                    UNWIND $rows AS row
                    MERGE (c:Class:Symbol {uid: row.uid})
                    SET c.name       = row.name,
                        c.qualname   = row.qualname,
                        c.lineno     = row.lineno,
                        c.end_lineno = row.end_lineno,
                        c.doc        = row.doc,
                        c.doc_src    = row.doc_src,
                        c.bases      = row.bases,
                        c.decorators = row.decorators,
                        c.fields     = row.fields,
                        c.repo_id    = row.repo_id,
                        c.rel_path   = row.rel_path
                    WITH c, row
                    MATCH (f:File {uid: row.file_uid})
                    MERGE (f)-[:DEFINES]->(c)
                    """,
                    rows=class_rows,
                )

            # ── Function nodes ─────────────────────────────────────────
            func_rows = []
            for f in parsed_files:
                rel = f.get("rel_path", "")
                fuid = file_uid(repo_id, rel)
                for fn in f.get("functions", []):
                    uid = sym_uid(repo_id, rel, fn["qualname"])
                    parent_class_uid = (
                        sym_uid(repo_id, rel, fn["parent_class"])
                        if fn.get("parent_class") else None
                    )
                    func_rows.append({
                        "uid": uid,
                        "name": fn["name"],
                        "qualname": fn["qualname"],
                        "sig": fn.get("sig", ""),
                        "doc": fn.get("doc", ""),
                        "doc_src": fn.get("doc_src", ""),
                        "lineno": fn.get("lineno", 0),
                        "end_lineno": fn.get("end_lineno", 0),
                        "loc": fn.get("loc", 0),
                        "is_async": fn.get("is_async", False),
                        "is_method": fn.get("is_method", False),
                        "is_test": fn.get("is_test", False),
                        "is_entrypoint": fn.get("is_entrypoint", False),
                        "decorators": fn.get("decorators", []),
                        "raises": fn.get("raises", []),
                        "repo_id": repo_id,
                        "rel_path": rel,
                        "file_uid": fuid,
                        "parent_class_uid": parent_class_uid,
                        "rank": 0.0,
                        "fan_in": 0,
                        "fan_out": len(fn.get("calls", [])),
                    })

            if func_rows:
                await s.run(
                    """
                    UNWIND $rows AS row
                    MERGE (fn:Function:Symbol {uid: row.uid})
                    SET fn.name         = row.name,
                        fn.qualname     = row.qualname,
                        fn.sig          = row.sig,
                        fn.doc          = row.doc,
                        fn.doc_src      = row.doc_src,
                        fn.lineno       = row.lineno,
                        fn.end_lineno   = row.end_lineno,
                        fn.loc          = row.loc,
                        fn.is_async     = row.is_async,
                        fn.is_method    = row.is_method,
                        fn.is_test      = row.is_test,
                        fn.is_entrypoint = row.is_entrypoint,
                        fn.decorators   = row.decorators,
                        fn.raises       = row.raises,
                        fn.repo_id      = row.repo_id,
                        fn.rel_path     = row.rel_path,
                        fn.rank         = row.rank,
                        fn.fan_in       = row.fan_in,
                        fn.fan_out      = row.fan_out
                    WITH fn, row
                    MATCH (f:File {uid: row.file_uid})
                    MERGE (f)-[:DEFINES]->(fn)
                    """,
                    rows=func_rows,
                )

                # Link methods to their class
                method_rows = [r for r in func_rows if r["parent_class_uid"]]
                if method_rows:
                    await s.run(
                        """
                        UNWIND $rows AS row
                        MATCH (fn:Function {uid: row.uid})
                        MATCH (cls:Class {uid: row.parent_class_uid})
                        MERGE (cls)-[:HAS_METHOD]->(fn)
                        """,
                        rows=method_rows,
                    )

            # ── CALLS edges with confidence ────────────────────────────
            calls_rows = []
            for f in parsed_files:
                rel = f.get("rel_path", "")
                file_imports = set(f.get("imports", []))
                for fn in f.get("functions", []):
                    caller_uid = sym_uid(repo_id, rel, fn["qualname"])
                    for called_name in fn.get("calls", []):
                        candidates = name_to_symbols.get(called_name, [])
                        if not candidates:
                            continue
                        # Resolve confidence
                        if len(candidates) == 1:
                            callee = candidates[0]
                            # Check if it's imported or local
                            mod_parts = callee["rel_path"].replace("/", ".").replace(".py", "")
                            if mod_parts in file_imports or callee["rel_path"] == rel:
                                conf = 0.95
                                via = "import"
                            else:
                                conf = 0.6
                                via = "unique"
                        elif len(candidates) <= 4:
                            conf = 0.5 / len(candidates)
                            via = "ambig"
                        else:
                            continue  # too ambiguous to be useful
                        for callee in candidates[:4]:
                            calls_rows.append({
                                "caller_uid": caller_uid,
                                "callee_uid": callee["uid"],
                                "conf": conf,
                                "via": via,
                            })

            if calls_rows:
                await s.run(
                    """
                    UNWIND $rows AS row
                    MATCH (caller:Function {uid: row.caller_uid})
                    MATCH (callee:Function {uid: row.callee_uid})
                    WHERE caller <> callee
                    MERGE (caller)-[r:CALLS]->(callee)
                    SET r.conf = row.conf, r.via = row.via
                    """,
                    rows=calls_rows,
                )

            # ── Import edges ───────────────────────────────────────────
            import_rows = []
            for f in parsed_files:
                fuid = file_uid(repo_id, f.get("rel_path", ""))
                for imp in f.get("imports", []):
                    import_rows.append({"fuid": fuid, "imp": imp, "repo_id": repo_id})

            if import_rows:
                await s.run(
                    """
                    UNWIND $rows AS row
                    MERGE (m:Module {uid: row.imp + '|' + row.repo_id, repo_id: row.repo_id})
                    SET m.name = row.imp
                    WITH m, row
                    MATCH (f:File {uid: row.fuid})
                    MERGE (f)-[:IMPORTS]->(m)
                    """,
                    rows=import_rows,
                )

        logger.info("graph_built", repo_id=repo_id, files=len(parsed_files),
                    calls_edges=len(calls_rows))

    # ── Retrieval queries ─────────────────────────────────────────────────

    async def symbol_card(self, repo_id: str, function_name: str) -> Dict[str, Any]:
        """Full symbol card with callers, callees, tests — for 'what does X do'."""
        async with self._driver.session() as s:
            result = await s.run(
                """
                MATCH (fn:Function {repo_id: $rid, name: $name})
                WITH fn LIMIT 1
                OPTIONAL MATCH (file:File)-[:DEFINES|HAS_METHOD*1..2]->(fn)
                OPTIONAL MATCH (cls:Class)-[:HAS_METHOD]->(fn)
                CALL (fn) {
                  MATCH (fn)-[r:CALLS]->(c:Function) WHERE r.conf >= 0.5
                  RETURN collect(c{.qualname,.sig,.doc,.rel_path,.lineno, conf:r.conf})[0..12] AS callees
                }
                CALL (fn) {
                  MATCH (p:Function)-[r:CALLS]->(fn) WHERE r.conf >= 0.5
                  WITH p, r ORDER BY p.rank DESC LIMIT 12
                  RETURN collect(p{.qualname,.rel_path,.lineno,.doc,conf:r.conf}) AS callers
                }
                RETURN fn{.qualname,.sig,.doc,.doc_src,.lineno,.end_lineno,.loc,
                          .is_async,.rank,.fan_in,.fan_out,.raises,.decorators,
                          .is_entrypoint,.is_test},
                       file.rel_path AS path, cls.name AS cls_name,
                       callees, callers
                """,
                rid=repo_id, name=function_name,
            )
            data = await result.data()
        return data[0] if data else {}

    async def reverse_calls(self, repo_id: str, function_name: str, max_depth: int = 3) -> Dict[str, Any]:
        """Who calls X — up to N hops."""
        async with self._driver.session() as s:
            result = await s.run(
                """
                MATCH (t:Function {repo_id: $rid, name: $name}) WITH t LIMIT 1
                MATCH path = (c:Function)-[:CALLS*1..$depth]->(t)
                WHERE all(r IN relationships(path) WHERE r.conf >= 0.5)
                WITH c, length(path) AS depth,
                     reduce(x=1.0, r IN relationships(path) | x * r.conf) AS conf,
                     [n IN nodes(path) | n.name] AS chain
                ORDER BY depth ASC, c.rank DESC LIMIT 40
                RETURN collect({depth:depth, conf:conf, chain:chain,
                                qualname:c.qualname, sig:c.sig, doc:c.doc,
                                at:c.rel_path + ':' + toString(c.lineno),
                                is_entrypoint:c.is_entrypoint}) AS callers,
                       t{.qualname,.sig,.doc,.rel_path,.lineno} AS target
                """,
                rid=repo_id, name=function_name, depth=max_depth,
            )
            data = await result.data()
        return data[0] if data else {}

    async def get_graph_data(self, repo_id: str) -> Dict[str, Any]:
        """For D3 visualization."""
        async with self._driver.session() as s:
            nodes_result = await s.run(
                """
                MATCH (n {repo_id: $rid})
                RETURN n.name AS name, n.rel_path AS rel_path,
                       labels(n)[0] AS type, id(n) AS id,
                       n.file_path AS file_path, n.lineno AS lineno,
                       n.uid AS uid
                LIMIT 500
                """,
                rid=repo_id,
            )
            edges_result = await s.run(
                """
                MATCH (a {repo_id: $rid})-[r]->(b {repo_id: $rid})
                RETURN id(a) AS source, id(b) AS target, type(r) AS rel
                LIMIT 1000
                """,
                rid=repo_id,
            )
            nodes = await nodes_result.data()
            edges = await edges_result.data()
        return {"nodes": nodes, "edges": edges}

    async def get_node_context(self, repo_id: str, node_id: int) -> Dict[str, Any]:
        async with self._driver.session() as s:
            result = await s.run(
                "MATCH (n) WHERE id(n) = $nid OPTIONAL MATCH (n)-[r]-(m) RETURN n, collect({rel: type(r), node: m}) AS neighbors",
                nid=node_id,
            )
            data = await result.data()
        return data[0] if data else {}

    async def resolve_uids_to_cards(self, repo_id: str, uids: List[str]) -> List[Dict]:
        """Given UIDs from Qdrant, fetch full symbol cards from Neo4j."""
        if not uids:
            return []
        async with self._driver.session() as s:
            result = await s.run(
                """
                UNWIND $uids AS uid
                MATCH (s:Symbol {uid: uid, repo_id: $rid})
                OPTIONAL MATCH (s)-[r:CALLS]->(c:Symbol) WHERE r.conf >= 0.6
                WITH s, collect(c{.qualname,.doc})[0..6] AS callees
                OPTIONAL MATCH (p:Symbol)-[r2:CALLS]->(s) WHERE r2.conf >= 0.6
                WITH s, callees, collect(p{.qualname})[0..6] AS callers
                RETURN s{.uid,.qualname,.sig,.doc,.rel_path,.lineno,.is_async,
                         .is_entrypoint,.raises,.rank},
                       callees, callers
                """,
                uids=uids, rid=repo_id,
            )
            return await result.data()

    async def repo_map(self, repo_id: str) -> str:
        """T0 serialization: compact file-level map of entire repo (~17 tokens/file)."""
        async with self._driver.session() as s:
            result = await s.run(
                """
                MATCH (f:File {repo_id: $rid})
                OPTIONAL MATCH (f)-[:DEFINES]->(s:Symbol)
                WITH f, collect(s.name)[0..15] AS syms
                ORDER BY f.rel_path
                RETURN f.rel_path AS path, f.language AS lang, f.loc AS loc, syms
                """,
                rid=repo_id,
            )
            rows = await result.data()

        lines = [f"# Repo Map ({len(rows)} files)"]
        for row in rows:
            sym_str = ", ".join(row["syms"]) if row["syms"] else ""
            lines.append(f"{row['path']} {row['lang']} {row['loc']}L [{sym_str}]")
        return "\n".join(lines)


# ── SGL serializer ────────────────────────────────────────────────────────

SGL_LEGEND = """LEGEND  Fn=file · C=class · f=func · af=async func
@N=lineno · ~N=cx · >=calls · <=called-by · !=raises
ENTRY=entrypoint · TEST · "…"=doc summary"""


def serialize_cards_to_sgl(cards: List[Dict], include_legend: bool = True) -> str:
    """Convert symbol cards from Neo4j into dense SGL format."""
    lines = []
    if include_legend:
        lines.append(SGL_LEGEND)
        lines.append("")

    by_file: Dict[str, List] = {}
    for card in cards:
        s = card.get("s", card)
        rel = s.get("rel_path", "?")
        by_file.setdefault(rel, []).append(card)

    file_ids: Dict[str, str] = {p: f"F{i+1}" for i, p in enumerate(sorted(by_file))}
    for path, fid in file_ids.items():
        lines.append(f"{fid} {path}")

    lines.append("")
    for path, fid in file_ids.items():
        for card in by_file[path]:
            s = card.get("s", card)
            q = s.get("qualname", s.get("name", "?"))
            sig = s.get("sig", "")
            doc = s.get("doc", "")
            lineno = s.get("lineno", "")
            is_async = s.get("is_async", False)
            is_entry = s.get("is_entrypoint", False)
            raises = s.get("raises", [])
            callees = [c.get("qualname", "") for c in (card.get("callees") or [])]
            callers = [c.get("qualname", "") for c in (card.get("callers") or [])]

            kind = "af" if is_async else "f"
            flags = " ENTRY" if is_entry else ""
            doc_str = f' "{doc}"' if doc else ""
            lineno_str = f" @{lineno}" if lineno else ""
            calls_str = " >" + " ".join(callees[:5]) if callees else ""
            callers_str = " <" + " ".join(callers[:3]) if callers else ""
            raises_str = " !" + " !".join(raises[:2]) if raises else ""
            sig_str = f" {sig}" if sig else ""

            lines.append(f" {kind} {q}{sig_str}{lineno_str}{flags}{doc_str}{calls_str}{callers_str}{raises_str}")

    return "\n".join(lines)


graph_builder = GraphBuilder()
