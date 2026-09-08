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
            # Create file nodes
            for f in parsed_files:
                await s.run(
                    """
                    MERGE (file:File {path: $path, repo_id: $rid})
                    SET file.rel_path = $rel, file.language = $lang
                    """,
                    path=f["path"], rid=repo_id,
                    rel=f.get("rel_path", ""), lang=f.get("language", "unknown"),
                )
                # Create function nodes and link to file
                for fn in f.get("functions", []):
                    await s.run(
                        """
                        MERGE (func:Function {name: $name, file_path: $fp, repo_id: $rid})
                        SET func.lineno = $lineno
                        WITH func
                        MATCH (file:File {path: $fp, repo_id: $rid})
                        MERGE (file)-[:DEFINES]->(func)
                        """,
                        name=fn["name"], fp=f["path"], rid=repo_id,
                        lineno=fn.get("lineno", 0),
                    )
                # Create class nodes
                for cls in f.get("classes", []):
                    await s.run(
                        """
                        MERGE (c:Class {name: $name, file_path: $fp, repo_id: $rid})
                        SET c.lineno = $lineno
                        WITH c
                        MATCH (file:File {path: $fp, repo_id: $rid})
                        MERGE (file)-[:DEFINES]->(c)
                        """,
                        name=cls["name"], fp=f["path"], rid=repo_id,
                        lineno=cls.get("lineno", 0),
                    )
                # Import edges (file → file approximation)
                for imp in f.get("imports", []):
                    await s.run(
                        """
                        MERGE (imp:Module {name: $imp, repo_id: $rid})
                        WITH imp
                        MATCH (file:File {path: $fp, repo_id: $rid})
                        MERGE (file)-[:IMPORTS]->(imp)
                        """,
                        imp=imp, fp=f["path"], rid=repo_id,
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
            nodes = [dict(r) for r in await nodes_result.data()]
            edges = [dict(r) for r in await edges_result.data()]
        return {"nodes": nodes, "edges": edges}

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


graph_builder = GraphBuilder()
