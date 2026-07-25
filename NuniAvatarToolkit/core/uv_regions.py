"""Shared "freed UV region" schema, bridging the hidden_mesh and texture_bake features
without either importing the other. hidden_mesh's delete operator produces this data (the
UV footprint of faces it is about to destroy); texture_bake consumes it later. No bpy.types
classes here - persistence is via a plain JSON string in a mesh ID custom property, which
survives save/reload, renaming, and duplication of the mesh datablock.
"""

import json

FREED_UV_RECTS_KEY = "amt_freed_uv_rects_json"

# Islands smaller than this (normalized UV area) are treated as degenerate/zero-size and dropped.
MIN_ISLAND_UV_AREA = 1e-6


class _UnionFind:
    def __init__(self, n):
        self.parent = list(range(n))

    def find(self, x):
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[ra] = rb


def compute_freed_uv_rects(faces, uv_layer, source_object_name, epsilon=1e-5):
    """faces: bmesh BMFace list (e.g. the faces about to be deleted). uv_layer: a bmesh UV
    loop layer (bm.loops.layers.uv.active). Groups faces by material_index, then splits each
    group into UV islands via union-find over shared edges whose UV coordinates also match on
    both endpoints (mesh-adjacency alone is not enough - a UV seam must keep faces in separate
    islands even though they're mesh-connected). Returns a list of JSON-serializable dicts, one
    per (material, island) with an area big enough to be worth reusing.
    """
    material_groups = {}
    for f in faces:
        material_groups.setdefault(f.material_index, []).append(f)

    rects = []
    for material_index, group_faces in material_groups.items():
        index_of = {f: i for i, f in enumerate(group_faces)}
        uf = _UnionFind(len(group_faces))

        edge_to_entries = {}
        for f in group_faces:
            for loop in f.loops:
                edge_to_entries.setdefault(loop.edge, []).append((f, loop))

        for entries in edge_to_entries.values():
            if len(entries) != 2:
                continue
            (fa, loop_a), (fb, loop_b) = entries
            if fa is fb:
                continue
            uv_a1 = loop_a[uv_layer].uv
            uv_a2 = loop_a.link_loop_next[uv_layer].uv
            uv_b1 = loop_b[uv_layer].uv
            uv_b2 = loop_b.link_loop_next[uv_layer].uv
            match_same = (uv_a1 - uv_b1).length < epsilon and (uv_a2 - uv_b2).length < epsilon
            match_reversed = (uv_a1 - uv_b2).length < epsilon and (uv_a2 - uv_b1).length < epsilon
            if match_same or match_reversed:
                uf.union(index_of[fa], index_of[fb])

        islands = {}
        for f in group_faces:
            islands.setdefault(uf.find(index_of[f]), []).append(f)

        uv_layer_name = getattr(uv_layer, "name", "")

        for island_faces in islands.values():
            min_u = min_v = float('inf')
            max_u = max_v = float('-inf')
            for f in island_faces:
                for loop in f.loops:
                    uv = loop[uv_layer].uv
                    min_u = min(min_u, uv.x)
                    max_u = max(max_u, uv.x)
                    min_v = min(min_v, uv.y)
                    max_v = max(max_v, uv.y)

            if (max_u - min_u) * (max_v - min_v) < MIN_ISLAND_UV_AREA:
                continue

            rects.append({
                "uv_layer": uv_layer_name,
                "material_index": material_index,
                "min_u": min_u, "min_v": min_v, "max_u": max_u, "max_v": max_v,
                "face_count": len(island_faces),
                "source_object": source_object_name,
            })

    return rects


def get_freed_rects(mesh):
    raw = mesh.get(FREED_UV_RECTS_KEY)
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        return []
    return data if isinstance(data, list) else []


def add_freed_rects(mesh, new_rects):
    if not new_rects:
        return
    existing = get_freed_rects(mesh)
    existing.extend(new_rects)
    mesh[FREED_UV_RECTS_KEY] = json.dumps(existing)


def remove_freed_rect(mesh, index):
    existing = get_freed_rects(mesh)
    if 0 <= index < len(existing):
        existing.pop(index)
        mesh[FREED_UV_RECTS_KEY] = json.dumps(existing)
