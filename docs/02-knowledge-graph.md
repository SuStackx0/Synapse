# Knowledge Graph: Theory and Design

## What Is a Code Knowledge Graph?

A knowledge graph represents entities (nodes) and relationships (edges) between them. In Synapse, the entities are the structural elements of code:

| Node Label | What it represents | Example |
|---|---|---|
| `File` | A source file | `auth/middleware.py` |
| `Function` | A named function or method | `validate_token` |
| `Class` | A class definition | `AuthService` |
| `Module` | An imported dependency | `fastapi.middleware` |

Edges encode how these entities relate:

| Edge Type | Meaning |
|---|---|
| `DEFINES` | File → Function/Class |
| `IMPORTS` | File → Module |
| `CALLS` | Function → Function (approximated from AST call sites) |

## Why a Graph, Not a Table?

Relational databases model one-to-many relationships well (one author, many posts). They model many-to-many relationships with join tables. But code structure is inherently recursive and multi-hop:

*"Find all functions that are called, directly or indirectly, by the payment handler."*

In SQL:
```sql
WITH RECURSIVE call_chain AS (
  SELECT callee FROM function_calls WHERE caller = 'payment_handler'
  UNION ALL
  SELECT fc.callee FROM function_calls fc
  JOIN call_chain cc ON fc.caller = cc.callee
)
SELECT * FROM call_chain;
```

In Cypher:
```cypher
MATCH (start:Function {name: 'payment_handler'})-[:CALLS*]->(downstream)
RETURN downstream.name, downstream.file_path
```

Cypher is declarative about graph traversal in a way SQL cannot be. This matters for features like impact analysis ("if I change this function, what breaks?") and dependency chains.

## AST Parsing

AST stands for Abstract Syntax Tree. When Python parses source code, it builds a tree where each node is a language construct:

```python
def greet(name: str) -> str:
    return f"Hello, {name}"
```

Becomes:
```
Module
  └─ FunctionDef (name='greet')
       ├─ arguments → [arg(arg='name', annotation=Name('str'))]
       ├─ returns → Name('str')
       └─ body → [Return(value=JoinedStr(...))]
```

The `ast` module in Python gives us a full, precise parse. We walk this tree to extract every `FunctionDef`, `ClassDef`, `Import`, `ImportFrom`, and `Call` node. This is O(N) in file size.

For JavaScript and TypeScript, we use regex heuristics. A full AST parser (tree-sitter) would be more accurate but adds C compilation complexity to the Docker build.

**Key design decision**: we parse at index time, not query time. The graph is built once, stored in Neo4j, and queried cheaply at request time.

## The "Repo Brain" Visualization

The force-directed graph uses D3's `forceSimulation`. Four forces act on nodes:

1. **`forceManyBody`** (repulsion): nodes push each other apart (strength -120), preventing overlap
2. **`forceLink`** (attraction): edges pull connected nodes together (distance 60)
3. **`forceCenter`**: pulls all nodes toward the center of the canvas
4. **`forceCollide`**: collision detection prevents nodes from overlapping

The simulation runs until kinetic energy falls below a threshold (alpha < 0.001), then freezes. Users can drag nodes to re-position them; on drag start we set `fx` and `fy` (fixed coordinates) and bump alpha to 0.3 to let the simulation re-settle around the dragged node.

**Color encoding by node type** is not decorative — it lets engineers instantly identify structural patterns: a dense cluster of orange (Module) nodes around green (Function) nodes means heavy external dependency; isolated purple (Class) nodes may indicate abstraction without usage.

## Limitations and Tradeoffs

- **Dynamic dispatch**: `obj.method()` where `obj`'s type is not statically known cannot be resolved by AST parsing alone. We track the method name, not the class it belongs to.
- **Cross-file call resolution**: we record that file A calls function named `process`, but we don't resolve which file defines that `process` (that would require type inference).
- **Max 500 files**: hardcoded limit to keep Neo4j write time reasonable during demo. Easily configurable.
- **JS/TS accuracy**: regex parsing misses arrow functions, destructured imports, and dynamic imports.

These are known and documented constraints, not bugs.
