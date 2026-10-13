"""Pure analysis logic for the diagnostics feature. No bpy.types here.

The rank thresholds below follow VRChat's publicly documented Avatar Performance Ranking
System for PC and for Quest (Mobile/Android). VRChat has revised these numbers before and
may again - they are shown to the user labeled as reference-only, never as authoritative,
and this module must not be treated as the source of truth for actual VRChat behavior.
"""

import re

import bmesh
import numpy as np

DEFAULT_COLLECTION_NAME_PATTERN = re.compile(r"Collection(\.\d+)?")

# (label, inclusive upper limit) per rank; anything above the last limit is "Very Poor".
PC_THRESHOLDS = {
    'triangles': (("Excellent", 32000), ("Good", 70000), ("Medium", 70000), ("Poor", 70000)),
    'material_slots': (("Excellent", 4), ("Good", 8), ("Medium", 16), ("Poor", 32)),
    'bones': (("Excellent", 75), ("Good", 150), ("Medium", 256), ("Poor", 400)),
}
QUEST_THRESHOLDS = {
    'triangles': (("Excellent", 7500), ("Good", 10000), ("Medium", 15000), ("Poor", 20000)),
    'material_slots': (("Excellent", 1), ("Good", 1), ("Medium", 2), ("Poor", 4)),
    'bones': (("Excellent", 75), ("Good", 90), ("Medium", 150), ("Poor", 150)),
}


def rank_for(value, thresholds):
    for label, limit in thresholds:
        if value <= limit:
            return label
    return "Very Poor"


def platform_ranks(value, category):
    """Reference rank text for both platforms, e.g. "PC: Excellent / Quest: Good"."""
    pc = rank_for(value, PC_THRESHOLDS[category])
    quest = rank_for(value, QUEST_THRESHOLDS[category])
    return f"PC: {pc} / Quest: {quest}"


def get_avatar_mesh_objects(collection):
    if collection is None:
        return []
    return [o for o in collection.all_objects if o.type == 'MESH']


def get_avatar_armature_objects(collection):
    if collection is None:
        return []
    return [o for o in collection.all_objects if o.type == 'ARMATURE']


def count_triangles(mesh_objects, depsgraph):
    total = 0
    for obj in mesh_objects:
        obj_eval = obj.evaluated_get(depsgraph)
        try:
            mesh_eval = obj_eval.to_mesh()
            mesh_eval.calc_loop_triangles()
            total += len(mesh_eval.loop_triangles)
        finally:
            obj_eval.to_mesh_clear()
    return total


def count_material_slots(mesh_objects, depsgraph=None):
    """Total material slots over all meshes; VRChat counts a material used in 20 slots as 20."""
    return sum(
        len((obj.evaluated_get(depsgraph) if depsgraph is not None else obj).material_slots)
        for obj in mesh_objects
    )


def count_bones(armature_objects):
    return sum(len(a.data.bones) for a in armature_objects)


def count_shape_keys(mesh_objects):
    total = 0
    for obj in mesh_objects:
        if obj.data.shape_keys:
            total += max(0, len(obj.data.shape_keys.key_blocks) - 1)
    return total


def _count_non_finite(collection, n):
    co = np.empty(n * 3, dtype=np.float64)
    collection.foreach_get('co', co)
    return int(np.count_nonzero(~np.isfinite(co.reshape(n, 3)).all(axis=1)))


def find_non_finite_vertices(obj):
    n = len(obj.data.vertices)
    if n == 0:
        return 0
    return _count_non_finite(obj.data.vertices, n)


def find_non_finite_shape_keys(obj):
    """[(shape_key_name, vertex_count), ...] for all keys holding NaN/Inf coordinates.

    Basis can differ from the raw mesh after imports or other add-ons edit the key data.
    """
    shape_keys = obj.data.shape_keys
    n = len(obj.data.vertices)
    if not shape_keys or n == 0:
        return []
    results = []
    for key_block in shape_keys.key_blocks:
        count = _count_non_finite(key_block.data, len(key_block.data))
        if count:
            results.append((key_block.name, count))
    return results


def has_non_uniform_or_negative_scale(obj):
    delta = getattr(obj, 'delta_scale', (1.0, 1.0, 1.0))
    sx, sy, sz = (s * d for s, d in zip(obj.scale, delta))
    negative = sx < 0 or sy < 0 or sz < 0
    non_uniform = not (abs(sx - sy) < 1e-6 and abs(sy - sz) < 1e-6)
    return negative, non_uniform


def _quaternion_is_rotated(quaternion):
    w, x, y, z = quaternion
    return abs(abs(w) - 1.0) > 1e-6 or any(abs(v) > 1e-6 for v in (x, y, z))


def has_unapplied_rotation(obj):
    # Delta rotation follows rotation_mode: quaternion mode uses the delta quaternion, Euler modes the
    # delta Euler. Axis-angle delta is not exposed to Python, so only the main channel is checked there.
    if obj.rotation_mode == 'QUATERNION':
        delta = getattr(obj, 'delta_rotation_quaternion', (1.0, 0.0, 0.0, 0.0))
        return _quaternion_is_rotated(obj.rotation_quaternion) or _quaternion_is_rotated(delta)
    if obj.rotation_mode == 'AXIS_ANGLE':
        return abs(obj.rotation_axis_angle[0]) > 1e-6
    delta_euler = getattr(obj, 'delta_rotation_euler', (0.0, 0.0, 0.0))
    return any(abs(v) > 1e-6 for v in obj.rotation_euler) or any(abs(v) > 1e-6 for v in delta_euler)


def count_non_manifold(obj):
    bm = bmesh.new()
    try:
        bm.from_mesh(obj.data)
        return sum(1 for e in bm.edges if not e.is_manifold)
    finally:
        bm.free()


def walk_collection_tree(collection, prune=None, _path_prefix=""):
    """Yield (child_collection, path) for every descendant collection, depth first.

    ``path`` is a display string such as "衣装/シャツ" joined from collection names,
    relative to ``collection`` (the root itself is never yielded). When ``prune`` is
    given, a node it returns True for is still yielded but its descendants are skipped.
    """
    if collection is None:
        return
    for child in collection.children:
        path = _path_prefix + child.name
        yield child, path
        if prune is not None and prune(child, path):
            continue
        yield from walk_collection_tree(child, prune, path + "/")


def find_uncategorized_mesh_objects(collection):
    """Meshes linked straight to the root while sub collections exist.

    Armatures are excluded on purpose: a single armature shared by body and outfits is
    normally placed at the top level, so flagging it would be a false positive.
    """
    if collection is None or not collection.children:
        return []
    return [o for o in collection.objects if o.type == 'MESH']


def find_layer_collection(layer_collection, target):
    if layer_collection is None or target is None:
        return None
    if layer_collection.collection == target:
        return layer_collection
    for child in layer_collection.children:
        found = find_layer_collection(child, target)
        if found is not None:
            return found
    return None


def find_excluded_or_hidden_branches(collection, layer_collection_root):
    """Topmost excluded / render-hidden collections that still hold objects.

    Include the target root and restrictions inherited from its ancestors. A shared
    collection remains available when at least one of its paths within the target is
    available. Descendants of a reported branch are pruned to avoid duplicate warnings.
    """
    if collection is None:
        return []

    layer_states = {}

    def visit(layer, excluded=False, hidden=False, within_target=False):
        excluded = excluded or layer.exclude
        hidden = hidden or layer.collection.hide_render
        within_target = within_target or layer.collection == collection
        if within_target:
            layer_states.setdefault(layer.collection, []).append((excluded, hidden))
        for child in layer.children:
            visit(child, excluded, hidden, within_target)

    if layer_collection_root is not None:
        visit(layer_collection_root)

    def reason_of(child):
        states = layer_states.get(child, [])
        if states and all(excluded for excluded, _hidden in states):
            return "除外"
        if child.hide_render:
            return "非表示"
        if states and all(excluded or hidden for excluded, hidden in states):
            return "非表示"
        return None

    root_reason = reason_of(collection)
    if root_reason is not None:
        return [(collection.name, collection, root_reason)] if collection.all_objects else []

    results = []
    for child, path in walk_collection_tree(collection, prune=lambda c, p: reason_of(c) is not None):
        reason = reason_of(child)
        # 中身が空のものは空コレクションのチェック側で拾うため、ここでは報告しない。
        if reason is None or len(child.all_objects) == 0:
            continue
        results.append((path, child, reason))
    return results


def find_duplicate_membership(collection):
    """Objects directly linked to two or more descendant collections: {object: [path, ...]}."""
    membership = {}
    seen = set()
    for child, path in walk_collection_tree(collection):
        # 同一コレクションが複数の親へリンクされている構成での二重計上を避ける。
        if child in seen:
            continue
        seen.add(child)
        for obj in child.objects:
            membership.setdefault(obj, []).append(path)
    return {obj: paths for obj, paths in membership.items() if len(paths) >= 2}


def find_default_named_collections(collection):
    return [
        (path, child)
        for child, path in walk_collection_tree(collection)
        if DEFAULT_COLLECTION_NAME_PATTERN.fullmatch(child.name)
    ]


def find_empty_collections(collection):
    return [
        (path, child)
        for child, path in walk_collection_tree(collection)
        if len(child.all_objects) == 0
    ]


def find_zero_weight_bones(armature_obj, mesh_objects):
    """Report-only, never auto-deleted: bones referenced by physics/constraint components
    outside the mesh data (e.g. VRChat PhysBone chains) look identical to truly-unused bones
    from mesh weights alone, so silent removal here risks breaking rigging undetectably."""
    bone_names = {b.name for b in armature_obj.data.bones}
    weighted = set()
    for obj in mesh_objects:
        if not any(m.type == 'ARMATURE' and m.object == armature_obj for m in obj.modifiers):
            continue
        group_has_weight = {}
        for v in obj.data.vertices:
            for g in v.groups:
                if g.weight > 0.0:
                    group_has_weight[g.group] = True
        for vg in obj.vertex_groups:
            if vg.name in bone_names and group_has_weight.get(vg.index):
                weighted.add(vg.name)
    return sorted(bone_names - weighted)
