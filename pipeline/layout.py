"""Precompute a force-directed layout so the browser ships positions, not physics.

We run a Fruchterman-Reingold layout (networkx ``spring_layout``) at build time
and bake ``x``/``y`` into every node. The site then renders static coordinates
with a tiny canvas drawer — no graph library or runtime simulation needed.

The Explore view's silhouette is shaped into a Greek cross centered on the most
recent encyclical (Magnifica Humanitas). Spring forces still decide *where*
nodes sit relative to one another; a polar cookie-cutter then maps every node's
radius to the cross outline at its angle, so the constellation reads as a cross
without losing the structural information the layout encodes.
"""

from __future__ import annotations

import math

import networkx as nx

# Scripture and author edges should clump their endpoints more loosely than the
# document-to-document citation backbone, which we want taut and central.
_EDGE_WEIGHT = {"cites": 1.0, "authored_by": 0.4, "cites_scripture": 0.3}

# The most recent encyclical: anchored at the cross's center.
_CENTER_ID = "doc:20260515-magnifica-humanitas"

# Greek-cross proportions. Half-width 0.28 vs. arm length 1.0 gives a clearly
# read-as-cross silhouette with arms thick enough to hold dense clusters.
_CROSS_HALF_WIDTH_RATIO = 0.28


def _cross_radius(theta: float, arm_len: float, half_w: float) -> float:
    """Distance from origin to the Greek-cross boundary along angle ``theta``.

    Cross = union of horizontal rect [-L,L]×[-w,w] and vertical rect
    [-w,w]×[-L,L]. For a ray from the origin, the exit radius is the *max*
    over the two rects (whichever lets the ray travel further is the one the
    point actually lives in).
    """
    eps = 1e-9
    c, s = abs(math.cos(theta)), abs(math.sin(theta))
    # horizontal rect: exits at x=±L or y=±w, whichever comes first
    r_horiz = min(arm_len / max(c, eps), half_w / max(s, eps))
    # vertical rect: exits at x=±w or y=±L, whichever comes first
    r_vert = min(half_w / max(c, eps), arm_len / max(s, eps))
    return max(r_horiz, r_vert)


def compute_layout(graph: dict, *, seed: int = 7, scale: float = 1000.0) -> dict:
    g = nx.Graph()
    for n in graph["nodes"]:
        g.add_node(n["id"])
    for e in graph["edges"]:
        w = _EDGE_WEIGHT.get(e["type"], 1.0) * (1 + 0.15 * (e["weight"] - 1))
        g.add_edge(e["source"], e["target"], weight=w)

    n = g.number_of_nodes()
    k = None if n <= 1 else 1.4 / (n ** 0.5)  # ideal edge length; spreads big graphs

    # Anchor the center node at the origin so the cross is built around it.
    init_pos = None
    fixed = None
    if _CENTER_ID in g.nodes:
        init_pos = {_CENTER_ID: (0.0, 0.0)}
        fixed = [_CENTER_ID]

    pos = nx.spring_layout(
        g, weight="weight", k=k, iterations=300, seed=seed,
        pos=init_pos, fixed=fixed,
    )

    if _CENTER_ID in pos:
        cx, cy = pos[_CENTER_ID]
    elif pos:
        xs = [p[0] for p in pos.values()]
        ys = [p[1] for p in pos.values()]
        cx = (min(xs) + max(xs)) / 2
        cy = (min(ys) + max(ys)) / 2
    else:
        cx = cy = 0.0

    # Cookie-cut into the cross outline. The spring layout's natural angular
    # distribution piles up on one side (the rest of the graph drifts away from
    # the fixed anchor), which would leave one arm dense and the others empty.
    # We preserve each node's *angular rank* but equalize the spacing — local
    # cluster cohesion is kept, and all four arms fill evenly.
    arm_len = scale
    half_w = scale * _CROSS_HALF_WIDTH_RATIO

    items = []   # (node, raw_angle, raw_radius)
    for node in graph["nodes"]:
        x, y = pos[node["id"]]
        dx, dy = x - cx, y - cy
        items.append((node, math.atan2(dy, dx), math.hypot(dx, dy)))

    movable = [t for t in items if t[2] >= 1e-9 and t[0]["id"] != _CENTER_ID]
    movable.sort(key=lambda t: t[1])
    n_mov = len(movable)

    # Pass 1: equalize angle (uniform angular ticks in original angular order).
    # Bucket each node into one of four arms (right/top/left/bottom).
    arms: dict[int, list[tuple]] = {0: [], 1: [], 2: [], 3: []}
    placed: list[tuple] = []   # (node, theta, raw_radius, arm)
    for i, (node, _, r) in enumerate(movable):
        theta = -math.pi + 2 * math.pi * (i + 0.5) / n_mov
        # arm: 0=right, 1=top, 2=left, 3=bottom (canvas y grows downward, but
        # the cross is symmetric so the labeling is purely internal).
        if -math.pi / 4 < theta <= math.pi / 4:
            arm = 0
        elif math.pi / 4 < theta <= 3 * math.pi / 4:
            arm = 1
        elif theta > 3 * math.pi / 4 or theta <= -3 * math.pi / 4:
            arm = 2
        else:
            arm = 3
        placed.append((node, theta, r, arm))
        arms[arm].append((node, r))

    # Pass 2: equalize radius *per arm*. Rank each arm's nodes by their natural
    # (spring) radius and assign uniform radial fractions in [0, 1], so every
    # arm fills from base to tip regardless of how the spring layout chose to
    # distribute distances.
    radial_frac: dict[str, float] = {}
    for arm_nodes in arms.values():
        arm_nodes.sort(key=lambda nr: nr[1])
        m = len(arm_nodes)
        for j, (node, _) in enumerate(arm_nodes):
            radial_frac[node["id"]] = (j + 0.5) / m if m else 0.0

    for node, theta, _, _ in placed:
        frac = radial_frac[node["id"]]
        r_target = _cross_radius(theta, arm_len, half_w) * frac
        node["x"] = round(math.cos(theta) * r_target, 2)
        node["y"] = round(math.sin(theta) * r_target, 2)

    # Center + degenerate (zero-radius) nodes land at the origin.
    for node, _, r in items:
        if r < 1e-9 or node["id"] == _CENTER_ID:
            node["x"] = 0.0
            node["y"] = 0.0
    return graph
