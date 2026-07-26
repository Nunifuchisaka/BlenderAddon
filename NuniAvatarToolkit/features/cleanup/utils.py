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


def _iter_nodes_recursive(node_tree, visited=None):
  """Yield nodes from node_tree and nested node groups without looping forever."""
  if node_tree is None:
    return
  if visited is None:
    visited = set()
  tree_id = id(node_tree)
  if tree_id in visited:
    return
  visited.add(tree_id)
  for node in node_tree.nodes:
    yield node
    if node.type == 'GROUP':
      yield from _iter_nodes_recursive(getattr(node, 'node_tree', None), visited)


def _referenced_material_attribute_names(obj):
  """Return UV/color/generic attribute names referenced by material node trees."""
  referenced = set()
  for mat in obj.data.materials:
    if mat is None or not mat.use_nodes or mat.node_tree is None:
      continue
    for node in _iter_nodes_recursive(mat.node_tree):
      referenced.update(_attribute_names_from_node(node))
  return referenced


def _attribute_names_from_node(node):
  """Return explicit attribute names stored on a shader or geometry node."""
  names = set()
  for attr in ('uv_map', 'layer_name', 'attribute_name'):
    name = getattr(node, attr, "")
    if name:
      names.add(name)
  for socket in getattr(node, 'inputs', ()):
    value = getattr(socket, 'default_value', None)
    if isinstance(value, str) and value:
      names.add(value)
  return names


def _referenced_modifier_attribute_names(obj):
  """Best-effort collection of named attributes referenced by modifiers.

  Blender stores classic modifier settings as RNA string properties and Geometry
  Nodes socket values as modifier ID properties. Treating every matching string as
  a reference is intentionally conservative because this powers destructive cleanup.
  """
  referenced = set()
  for mod in obj.modifiers:
    for node in _iter_nodes_recursive(getattr(mod, 'node_group', None)):
      referenced.update(_attribute_names_from_node(node))
    bl_rna = getattr(mod, 'bl_rna', None)
    for prop in getattr(bl_rna, 'properties', ()):
      if getattr(prop, 'type', None) != 'STRING' or prop.identifier == 'name':
        continue
      try:
        value = getattr(mod, prop.identifier)
      except (AttributeError, TypeError):
        continue
      if value:
        referenced.add(value)
    for _key, value in getattr(mod, 'items', lambda: ())():
      if isinstance(value, str) and value:
        referenced.add(value)
  return referenced


def _referenced_attribute_names(obj):
  return _referenced_material_attribute_names(obj) | _referenced_modifier_attribute_names(obj)


def find_unused_uv_maps(obj):
  uv_layers = obj.data.uv_layers
  if len(uv_layers) <= 1:
    return []
  referenced = _referenced_attribute_names(obj)
  if uv_layers.active:
    referenced.add(uv_layers.active.name)
  referenced.update(uv.name for uv in uv_layers if getattr(uv, 'active_render', False))
  return [uv.name for uv in uv_layers if uv.name not in referenced]


def find_unused_color_attributes(obj):
  attrs = obj.data.color_attributes
  if len(attrs) == 0:
    return []
  referenced = _referenced_attribute_names(obj)
  active_color = getattr(attrs, 'active_color', None)
  if active_color is not None:
    referenced.add(active_color.name)
  render_color_index = getattr(attrs, 'render_color_index', -1)
  if 0 <= render_color_index < len(attrs):
    referenced.add(attrs[render_color_index].name)
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
