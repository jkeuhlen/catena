"""Precompute a force-directed layout so the browser ships positions, not physics.

We run a Fruchterman-Reingold layout (networkx ``spring_layout``) at build time
and bake ``x``/``y`` into every node. The site then renders static coordinates
with a tiny canvas drawer — no graph library or runtime simulation needed.
"""

from __future__ import annotations

import networkx as nx

# Scripture and author edges should clump their endpoints more loosely than the
# document-to-document citation backbone, which we want taut and central.
_EDGE_WEIGHT = {"cites": 1.0, "authored_by": 0.4, "cites_scripture": 0.3}


def compute_layout(graph: dict, *, seed: int = 7, scale: float = 1000.0) -> dict:
    g = nx.Graph()
    for n in graph["nodes"]:
        g.add_node(n["id"])
    for e in graph["edges"]:
        w = _EDGE_WEIGHT.get(e["type"], 1.0) * (1 + 0.15 * (e["weight"] - 1))
        g.add_edge(e["source"], e["target"], weight=w)

    n = g.number_of_nodes()
    k = None if n <= 1 else 1.4 / (n ** 0.5)  # ideal edge length; spreads big graphs
    pos = nx.spring_layout(g, weight="weight", k=k, iterations=300, seed=seed)

    # normalize into a centered square of side ~2*scale
    xs = [p[0] for p in pos.values()]
    ys = [p[1] for p in pos.values()]
    cx = (min(xs) + max(xs)) / 2 if xs else 0
    cy = (min(ys) + max(ys)) / 2 if ys else 0
    span = max(max(xs) - min(xs), max(ys) - min(ys), 1e-6) if xs else 1
    factor = (2 * scale) / span

    for node in graph["nodes"]:
        x, y = pos[node["id"]]
        node["x"] = round((x - cx) * factor, 2)
        node["y"] = round((y - cy) * factor, 2)
    return graph
