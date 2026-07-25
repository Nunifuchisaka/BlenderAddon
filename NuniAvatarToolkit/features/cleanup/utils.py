"""Pure scan logic for the cleanup feature. No bpy.types here."""

import bmesh
import numpy as np


def get_referenced_vertex_group_names(obj):
    """Vertex group names referenced by a modifier's vertex_group field(s) or a shape key's
    vertex_group, even if currently zero-weighted - removing these could silently break the
    modifier/shape-key setup, so they are never treated as "empty" regardless of weight."""
    referenced = set()
    for mod in obj.modifiers:
        for attr in ('vertex_group', 'vertex_group_a', 'vertex_group_b'):
            name = getattr(mod, attr, "")
            if name:
                referenced.add(name)
    if obj.data.shape_keys:
        for kb in obj.data.shape_keys.key_blocks:
            if kb.vertex_group:
                referenced.add(kb.vertex_group)
    return referenced


def find_empty_vertex_groups(obj):
    referenced = get_referenced_vertex_group_names(obj)
    used_indices = set()
    for v in obj.data.vertices:
        for g in v.groups:
            if g.weight > 0.0:
                used_indices.add(g.group)
    return [vg.name for vg in obj.vertex_groups if vg.index not in used_indices and vg.name not in referenced]


def find_noop_shape_keys(obj, threshold):
    """Shape keys (excluding Basis) whose max per-vertex offset from Basis is below threshold."""
    sk = obj.data.shape_keys
    if not sk or len(sk.key_blocks) < 2:
        return []
    n = len(obj.data.vertices)
    if n == 0:
        return []

    basis_co = np.empty(n * 3, dtype=np.float64)
    sk.key_blocks[0].data.foreach_get('co', basis_co)
    basis_co = basis_co.reshape(n, 3)

    noop = []
    for kb in sk.key_blocks[1:]:
        co = np.empty(n * 3, dtype=np.float64)
        kb.data.foreach_get('co', co)
        co = co.reshape(n, 3)
        max_delta = float(np.max(np.linalg.norm(co - basis_co, axis=1)))
        if max_delta < threshold:
            noop.append(kb.name)
    return noop


def _referenced_node_names(obj, node_type, name_attr):
    referenced = set()
    for mat in obj.data.materials:
        if mat is None or not mat.use_nodes or mat.node_tree is None:
            continue
        for node in mat.node_tree.nodes:
            if node.type == node_type:
                name = getattr(node, name_attr, "")
                if name:
                    referenced.add(name)
    return referenced


def find_unused_uv_maps(obj):
    uv_layers = obj.data.uv_layers
    if len(uv_layers) <= 1:
        return []
    referenced = _referenced_node_names(obj, 'UVMAP', 'uv_map')
    if uv_layers.active:
        referenced.add(uv_layers.active.name)
    return [uv.name for uv in uv_layers if uv.name not in referenced]


def find_unused_color_attributes(obj):
    attrs = obj.data.color_attributes
    if len(attrs) == 0:
        return []
    referenced = _referenced_node_names(obj, 'VERTEX_COLOR', 'layer_name')
    return [c.name for c in attrs if c.name not in referenced]


def count_unused_material_slots(obj):
    used = {poly.material_index for poly in obj.data.polygons}
    return sum(1 for i in range(len(obj.material_slots)) if i not in used)


def count_loose_geometry(obj):
    bm = bmesh.new()
    try:
        bm.from_mesh(obj.data)
        loose_verts = sum(1 for v in bm.verts if not v.link_faces)
        loose_edges = sum(1 for e in bm.edges if not e.link_faces)
        return loose_verts, loose_edges
    finally:
        bm.free()
