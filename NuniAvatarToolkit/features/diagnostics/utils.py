"""Pure analysis logic for the diagnostics feature. No bpy.types here.

The rank thresholds below are approximate reference values based on VRChat's publicly
documented Avatar Performance Ranking System. VRChat has revised these numbers before and
may again - they are shown to the user labeled as reference-only, never as authoritative,
and this module must not be treated as the source of truth for actual VRChat behavior.
"""

import bmesh
import numpy as np

TRIANGLE_THRESHOLDS = (
    ("Excellent", 7500),
    ("Good", 20000),
    ("Medium", 32000),
    ("Poor", 70000),
)
MATERIAL_THRESHOLDS = (
    ("Excellent", 1),
    ("Good", 2),
    ("Medium", 4),
    ("Poor", 8),
)
BONE_THRESHOLDS = (
    ("Excellent", 75),
    ("Good", 150),
    ("Medium", 256),
    ("Poor", 400),
)


def rank_for(value, thresholds):
    for label, limit in thresholds:
        if value <= limit:
            return label
    return "Very Poor"


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


def count_material_slots(mesh_objects):
    materials = set()
    for obj in mesh_objects:
        for slot in obj.material_slots:
            if slot.material:
                materials.add(slot.material)
    return len(materials)


def count_bones(armature_objects):
    return sum(len(a.data.bones) for a in armature_objects)


def count_shape_keys(mesh_objects):
    total = 0
    for obj in mesh_objects:
        if obj.data.shape_keys:
            total += max(0, len(obj.data.shape_keys.key_blocks) - 1)
    return total


def find_non_finite_vertices(obj):
    n = len(obj.data.vertices)
    if n == 0:
        return 0
    co = np.empty(n * 3, dtype=np.float64)
    obj.data.vertices.foreach_get('co', co)
    return int(np.count_nonzero(~np.isfinite(co.reshape(n, 3)).all(axis=1)))


def has_non_uniform_or_negative_scale(obj):
    sx, sy, sz = obj.scale
    negative = sx < 0 or sy < 0 or sz < 0
    non_uniform = not (abs(sx - sy) < 1e-6 and abs(sy - sz) < 1e-6)
    return negative, non_uniform


def has_unapplied_rotation(obj):
    return any(abs(v) > 1e-6 for v in obj.rotation_euler)


def count_non_manifold(obj):
    bm = bmesh.new()
    try:
        bm.from_mesh(obj.data)
        return sum(1 for e in bm.edges if not e.is_manifold)
    finally:
        bm.free()


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
