from fastapi import APIRouter, HTTPException
from ingestion.graph_builder import graph_builder

router = APIRouter(prefix="/graph", tags=["graph"])


@router.get("/{repo_id}")
async def get_graph(repo_id: str):
    try:
        data = await graph_builder.get_graph_data(repo_id)
        return data
    except Exception as e:
        raise HTTPException(500, str(e))


@router.get("/{repo_id}/node/{node_id}")
async def get_node(repo_id: str, node_id: int):
    try:
        data = await graph_builder.get_node_context(repo_id, node_id)
        return data
    except Exception as e:
        raise HTTPException(500, str(e))
