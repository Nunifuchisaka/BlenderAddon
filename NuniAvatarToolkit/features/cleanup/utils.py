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


def _shape_key_coordinates(key_block, vertex_count):
    co = np.empty(vertex_count * 3, dtype=np.float64)
    key_block.data.foreach_get('co', co)
    return co.reshape(vertex_count, 3)


def get_driver_referenced_shape_key_names(obj, animation_owners):
    """Keys used as driver controls, including paths through a Mesh or an Object.

    The caller supplies Blender IDs so this module stays independently loadable.
    Named paths come from Blender itself to handle quotes/backslashes in key names.
    """
    sk = obj.data.shape_keys
    if sk is None:
        return set()
    key_blocks = list(sk.key_blocks)
    paths = {
        kb.name: (kb.path_from_id(), f"key_blocks[{index}]")
        for index, kb in enumerate(key_blocks)
    }
    referenced = set()
    for owner in animation_owners:
        animation_data = getattr(owner, 'animation_data', None)
        for curve in getattr(animation_data, 'drivers', ()):
            for variable in curve.driver.variables:
                for target in variable.targets:
                    target_id = target.id
                    if target_id is None:
                        continue
                    if target_id == sk:
                        prefix = ''
                    elif target_id == obj.data:
                        prefix = 'shape_keys.'
                    elif getattr(getattr(target_id, 'data', None), 'shape_keys', None) == sk:
                        prefix = 'data.shape_keys.'
                    else:
                        continue
                    path = target.data_path
                    for name, key_paths in paths.items():
                        for key_path in key_paths:
                            full_path = prefix + key_path
                            if path == full_path or path.startswith(full_path + '.') or path.startswith(full_path + '['):
                                referenced.add(name)
                                if key_path == key_paths[1]:
                                    # Numeric driver paths also depend on every preceding index.
                                    index = key_blocks.index(sk.key_blocks[name])
                                    referenced.update(kb.name for kb in key_blocks[:index + 1])
    return referenced


def find_noop_shape_keys(obj, threshold, referenced_names=()):
    """Shape keys whose max per-vertex offset from their own relative_key is below threshold.

    The reference (Basis) key, keys that other keys use as relative_key (removing them would
    rebase the dependants), incoming driver controls, and absolute (non-relative)
    shape keys are never reported.
    """
    sk = obj.data.shape_keys
    if not sk or len(sk.key_blocks) < 2 or not sk.use_relative:
        return []
    n = len(obj.data.vertices)
    if n == 0:
        return []

    key_blocks = list(sk.key_blocks)
    reference = key_blocks[0]
    used_as_relative = {
        kb.relative_key.name for kb in key_blocks
        if kb.relative_key is not None and kb.relative_key.name != kb.name
    }

    protected = used_as_relative | set(referenced_names)
    noop = []
    for kb in key_blocks[1:]:
        if kb.name in protected:
            continue
        base = kb.relative_key if kb.relative_key is not None else reference
        if base.name == kb.name:
            continue
        delta = _shape_key_coordinates(kb, n) - _shape_key_coordinates(base, n)
        if float(np.max(np.linalg.norm(delta, axis=1))) < threshold:
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
    slots = getattr(obj, 'material_slots', None)
    materials = (slot.material for slot in slots) if slots is not None else obj.data.materials
    for mat in materials:
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


def _id_property_values(mod):
    # Only some modifier types (e.g. Geometry Nodes) support ID properties; the rest raise TypeError.
    try:
        return [value for _key, value in mod.items()]
    except (AttributeError, TypeError):
        return []


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
        for value in _id_property_values(mod):
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


def material_slot_remapping_blockers(obj):
    """Modifiers whose material assignments cannot safely follow a base-mesh slot map.

    Relative offsets and procedural indices can change even when a removed slot has
    no original faces. Disabled modifiers also matter when the user enables them later.
    """
    unsafe_types = {'SOLIDIFY', 'BEVEL', 'WIREFRAME', 'NODES', 'BOOLEAN', 'PARTICLE_SYSTEM',
                    'MESH_SEQUENCE_CACHE', 'OCEAN'}
    return [mod.name for mod in obj.modifiers if mod.type in unsafe_types]


def delete_loose_geometry(bm):
    """Remove edges and vertices that belong to no face, regardless of selection/hide state.

    Returns (removed_vertex_count, removed_edge_count).
    """
    loose_edges = [e for e in bm.edges if not e.link_faces]
    loose_verts = [v for v in bm.verts if not v.link_faces]
    for edge in loose_edges:
        bm.edges.remove(edge)
    for vert in loose_verts:
        bm.verts.remove(vert)
    return len(loose_verts), len(loose_edges)


def count_loose_geometry(obj):
    bm = bmesh.new()
    try:
        bm.from_mesh(obj.data)
        loose_verts = sum(1 for v in bm.verts if not v.link_faces)
        loose_edges = sum(1 for e in bm.edges if not e.link_faces)
        return loose_verts, loose_edges
    finally:
        bm.free()
