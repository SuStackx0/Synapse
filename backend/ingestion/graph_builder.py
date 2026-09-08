from neo4j import AsyncGraphDatabase
from core.config import settings
from typing import List, Dict, Any
import structlog

logger = structlog.get_logger()


class GraphBuilder:
    def __init__(self):
        self._driver = None

    async def connect(self):
        self._driver = AsyncGraphDatabase.driver(
            settings.neo4j_uri,
            auth=(settings.neo4j_user, settings.neo4j_password),
        )

    async def close(self):
        if self._driver:
            await self._driver.close()

    async def clear_repo(self, repo_id: str):
        async with self._driver.session() as s:
            await s.run("MATCH (n {repo_id: $rid}) DETACH DELETE n", rid=repo_id)

    async def build_graph(self, repo_id: str, parsed_files: List[Dict[str, Any]]):
        await self.clear_repo(repo_id)
        async with self._driver.session() as s:
            for f in parsed_files:
                file_path = f["path"]
                await s.run(
                    """
                    MERGE (file:File {path: $path, repo_id: $rid})
                    SET file.rel_path = $rel, file.language = $lang
                    """,
                    path=file_path, rid=repo_id,
                    rel=f.get("rel_path", ""), lang=f.get("language", "unknown"),
                )
                for fn in f.get("functions", []):
                    await s.run(
                        """
                        MERGE (func:Function {name: $name, file_path: $fp, repo_id: $rid})
                        SET func.lineno = $lineno, func.args = $args
                        WITH func
                        MATCH (file:File {path: $fp, repo_id: $rid})
                        MERGE (file)-[:DEFINES]->(func)
                        """,
                        name=fn["name"], fp=file_path, rid=repo_id,
                        lineno=fn.get("lineno", 0),
                        args=fn.get("args", []),
                    )
                for cls in f.get("classes", []):
                    await s.run(
                        """
                        MERGE (c:Class {name: $name, file_path: $fp, repo_id: $rid})
                        SET c.lineno = $lineno, c.methods = $methods
                        WITH c
                        MATCH (file:File {path: $fp, repo_id: $rid})
                        MERGE (file)-[:DEFINES]->(c)
                        """,
                        name=cls["name"], fp=file_path, rid=repo_id,
                        lineno=cls.get("lineno", 0),
                        methods=cls.get("methods", []),
                    )
                for imp in f.get("imports", []):
                    await s.run(
                        """
                        MERGE (imp:Module {name: $imp, repo_id: $rid})
                        WITH imp
                        MATCH (file:File {path: $fp, repo_id: $rid})
                        MERGE (file)-[:IMPORTS]->(imp)
                        """,
                        imp=imp, fp=file_path, rid=repo_id,
                    )

            # Build CALLS edges between Function nodes (cross-file)
            # For each file's call sites, link caller functions to matching callee functions
            for f in parsed_files:
                file_path = f["path"]
                for fn in f.get("functions", []):
                    for called_name in f.get("calls", []):
                        await s.run(
                            """
                            MATCH (caller:Function {name: $caller, file_path: $fp, repo_id: $rid})
                            MATCH (callee:Function {name: $callee, repo_id: $rid})
                            WHERE caller <> callee
                            MERGE (caller)-[:CALLS]->(callee)
                            """,
                            caller=fn["name"], fp=file_path,
                            callee=called_name, rid=repo_id,
                        )

        logger.info("graph_built", repo_id=repo_id, files=len(parsed_files))

    async def get_graph_data(self, repo_id: str) -> Dict[str, Any]:
        async with self._driver.session() as s:
            nodes_result = await s.run(
                """
                MATCH (n {repo_id: $rid})
                RETURN n.name AS name, n.rel_path AS rel_path,
                       labels(n)[0] AS type, id(n) AS id,
                       n.file_path AS file_path, n.lineno AS lineno
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

    async def get_callers_and_callees(self, repo_id: str, function_name: str) -> Dict[str, Any]:
        """Graph-augmented context: 2-hop neighbourhood of a function."""
        async with self._driver.session() as s:
            result = await s.run(
                """
                MATCH (fn:Function {name: $name, repo_id: $rid})
                OPTIONAL MATCH (fn)-[:CALLS]->(callee:Function)
                OPTIONAL MATCH (caller:Function)-[:CALLS]->(fn)
                OPTIONAL MATCH (file:File)-[:DEFINES]->(fn)
                RETURN
                  fn.name AS name,
                  fn.file_path AS file_path,
                  fn.lineno AS lineno,
                  collect(DISTINCT callee.name) AS callees,
                  collect(DISTINCT caller.name) AS callers,
                  file.rel_path AS defined_in
                LIMIT 1
                """,
                name=function_name, rid=repo_id,
            )
            data = await result.data()
        return data[0] if data else {}

    async def get_node_context(self, repo_id: str, node_id: int) -> Dict[str, Any]:
        async with self._driver.session() as s:
            result = await s.run(
                """
                MATCH (n) WHERE id(n) = $nid
                OPTIONAL MATCH (n)-[r]-(m)
                RETURN n, collect({rel: type(r), node: m}) AS neighbors
                """,
                nid=node_id,
            )
            data = await result.data()
        return data[0] if data else {}

    async def find_symbols_in_context(self, repo_id: str, text: str) -> List[str]:
        """Extract function/class names from chunk text and expand via graph."""
        async with self._driver.session() as s:
            result = await s.run(
                """
                MATCH (fn:Function {repo_id: $rid})
                WHERE $text CONTAINS fn.name AND size(fn.name) > 3
                WITH fn LIMIT 5
                MATCH (fn)-[:CALLS*0..2]->(related:Function)
                RETURN DISTINCT
                  fn.name AS source,
                  related.name AS related,
                  related.file_path AS file_path,
                  related.lineno AS lineno
                LIMIT 20
                """,
                rid=repo_id, text=text,
            )
            rows = await result.data()
        graph_context = []
        for row in rows:
            graph_context.append(
                f"[Graph] {row['source']} → calls → {row['related']} "
                f"(in {row['file_path']}:{row['lineno']})"
            )
        return graph_context


graph_builder = GraphBuilder()
