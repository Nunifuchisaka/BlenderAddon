"""Shared depsgraph/BVH helpers used by multiple NuniAvatarToolkit features.

Contains no bpy.types classes and needs no register()/unregister() -
it is imported by feature modules, not registered itself.
"""

import numpy as np
from mathutils.bvhtree import BVHTree

# Modifier types that keep the base mesh's vertex count and order: Blender's own "Deform"
# category plus caches, physics and data-only modifiers that never add, remove or reorder
# vertices. Anything else (Subdivision, Mirror, Boolean, Geometry Nodes, ...) may change the
# count or silently reorder vertices, so it is disabled transiently whenever coordinates must
# stay 1:1 with the base mesh (required for edit-mode selection). Unknown identifiers are
# harmless here because membership is a plain string test.
DEFORM_MODIFIER_TYPES = frozenset({
    'ARMATURE', 'CAST', 'CURVE', 'DISPLACE', 'HOOK', 'LAPLACIANDEFORM',
    'LATTICE', 'MESH_DEFORM', 'SHRINKWRAP', 'SIMPLE_DEFORM', 'SMOOTH',
    'CORRECTIVE_SMOOTH', 'LAPLACIANSMOOTH', 'SURFACE_DEFORM', 'WARP', 'WAVE',
    'MESH_CACHE', 'MESH_SEQUENCE_CACHE', 'CLOTH', 'SOFT_BODY', 'COLLISION', 'DYNAMIC_PAINT',
    'DATA_TRANSFER', 'NORMAL_EDIT', 'WEIGHTED_NORMAL', 'UV_PROJECT', 'UV_WARP',
    'VERTEX_WEIGHT_EDIT', 'VERTEX_WEIGHT_MIX', 'VERTEX_WEIGHT_PROXIMITY',
})


def _non_deform_modifiers(obj):
    return [mod for mod in obj.modifiers if mod.type not in DEFORM_MODIFIER_TYPES and mod.show_viewport]


def disable_non_deform_modifiers(obj):
    """Temporarily hide non-deform modifiers. Returns [(modifier, prev_state), ...].

    If hiding one fails (e.g. the object is linked), the ones already hidden are restored
    before the exception propagates, so the object is never left half-modified.
    """
    disabled = []
    try:
        for mod in _non_deform_modifiers(obj):
            mod.show_viewport = False
            disabled.append((mod, True))
    except Exception:
        restore_modifiers(disabled)
        raise
    return disabled


def restore_modifiers(disabled):
    for mod, prev_state in disabled:
        try:
            mod.show_viewport = prev_state
        except Exception:
            pass


def transform_points(points, matrix):
    """Apply a 4x4 affine matrix to an (N,3) float64 array of points."""
    m = np.array(matrix, dtype=np.float64)
    return points @ m[:3, :3].T + m[:3, 3]


def get_protected_vertex_mask(obj, group_name):
    """Per-vertex bool mask of vertices carrying weight in group_name (all False when unset/missing)."""
    mask = np.zeros(len(obj.data.vertices), dtype=bool)
    if not group_name:
        return mask
    group = obj.vertex_groups.get(group_name)
    if group is None:
        return mask
    group_index = group.index
    for i, vert in enumerate(obj.data.vertices):
        for g in vert.groups:
            if g.group == group_index and g.weight > 0.0:
                mask[i] = True
                break
    return mask


def extract_world_positions_normals(mesh, matrix_world):
    n = len(mesh.vertices)
    co = np.empty(n * 3, dtype=np.float64)
    mesh.vertices.foreach_get('co', co)
    co = co.reshape(n, 3)

    nrm = np.empty(n * 3, dtype=np.float64)
    mesh.vertices.foreach_get('normal', nrm)
    nrm = nrm.reshape(n, 3)

    world_co = transform_points(co, matrix_world)

    normal_mat = np.array(matrix_world.inverted_safe().transposed().to_3x3(), dtype=np.float64)
    world_nrm = nrm @ normal_mat.T
    lengths = np.linalg.norm(world_nrm, axis=1, keepdims=True)
    lengths[lengths < 1e-12] = 1.0
    world_nrm = world_nrm / lengths

    return world_co, world_nrm


def _get_matching_evaluated(obj, depsgraph, original_count):
    eval_obj = obj.evaluated_get(depsgraph)
    try:
        mesh_eval = eval_obj.to_mesh()
        if len(mesh_eval.vertices) != original_count:
            return None
        return extract_world_positions_normals(mesh_eval, eval_obj.matrix_world)
    finally:
        eval_obj.to_mesh_clear()


def snapshot_deform_only(depsgraph, obj):
    """World-space (position, normal) per base-mesh vertex, index-aligned with obj.data.vertices.

    With only count/order-preserving modifiers enabled, the evaluated (posed) mesh is used
    directly. Otherwise those other modifiers are transiently disabled first, because an equal
    vertex count alone does not prove the order matches (Geometry Nodes can reorder). Falls back
    to rest-pose base coordinates when the modifiers cannot be toggled (linked object) or the
    count still differs.
    Returns (positions: (V,3) float64 ndarray, normals: (V,3) float64 ndarray, used_evaluated: bool).
    """
    original_count = len(obj.data.vertices)

    if not _non_deform_modifiers(obj):
        result = _get_matching_evaluated(obj, depsgraph, original_count)
        if result is not None:
            return result[0], result[1], True
    elif obj.library is None:
        try:
            disabled = disable_non_deform_modifiers(obj)
        except Exception:
            disabled = None
        if disabled is not None:
            try:
                depsgraph.update()
                result = _get_matching_evaluated(obj, depsgraph, original_count)
                if result is not None:
                    return result[0], result[1], True
            finally:
                restore_modifiers(disabled)
                depsgraph.update()

    positions, normals = extract_world_positions_normals(obj.data, obj.matrix_world)
    return positions, normals, False


def build_bvh_from_objects(depsgraph, objects):
    """Merge the full (all-modifiers) evaluated triangles of every object into one world-space BVHTree.

    Returns (BVHTree | None, aabb_min | None, aabb_max | None).
    """
    if not objects:
        return None, None, None

    verts = []
    tris = []
    offset = 0
    aabb_min = None
    aabb_max = None

    for obj in objects:
        obj_eval = obj.evaluated_get(depsgraph)
        try:
            mesh_eval = obj_eval.to_mesh()
            mesh_eval.calc_loop_triangles()
            n = len(mesh_eval.vertices)
            if n == 0 or len(mesh_eval.loop_triangles) == 0:
                continue

            co = np.empty(n * 3, dtype=np.float64)
            mesh_eval.vertices.foreach_get('co', co)
            co = co.reshape(n, 3)
            world_co = transform_points(co, obj_eval.matrix_world)

            t = len(mesh_eval.loop_triangles)
            tri_idx = np.empty(t * 3, dtype=np.int64)
            mesh_eval.loop_triangles.foreach_get('vertices', tri_idx)
            tri_idx = tri_idx.reshape(t, 3) + offset

            verts.extend(world_co.tolist())
            tris.extend(tuple(tri) for tri in tri_idx.tolist())
            offset += n

            obj_min = world_co.min(axis=0)
            obj_max = world_co.max(axis=0)
            aabb_min = obj_min if aabb_min is None else np.minimum(aabb_min, obj_min)
            aabb_max = obj_max if aabb_max is None else np.maximum(aabb_max, obj_max)
        finally:
            obj_eval.to_mesh_clear()

    if not verts or not tris:
        return None, None, None

    bvh = BVHTree.FromPolygons(verts, tris, all_triangles=True)
    return bvh, aabb_min, aabb_max


def compute_bbox_diagonal(positions):
    mn = positions.min(axis=0)
    mx = positions.max(axis=0)
    diag = float(np.linalg.norm(mx - mn))
    return diag if diag > 1e-9 else 1.0


def compute_face_mask_from_vertex_flags(mesh, vertex_flags, mode):
    """Lift a per-vertex boolean mask to a per-face one.

    mode 'ALL' flags a face only when every one of its vertices is flagged;
    'ANY' flags it as soon as a single vertex is.
    """
    face_count = len(mesh.polygons)
    mask = np.zeros(face_count, dtype=bool)
    if face_count == 0:
        return mask

    loop_totals = np.empty(face_count, dtype=np.int32)
    mesh.polygons.foreach_get('loop_total', loop_totals)
    loop_starts = np.empty(face_count, dtype=np.int32)
    mesh.polygons.foreach_get('loop_start', loop_starts)
    vertex_indices = np.empty(len(mesh.loops), dtype=np.int32)
    mesh.loops.foreach_get('vertex_index', vertex_indices)

    for f in range(face_count):
        start = loop_starts[f]
        total = loop_totals[f]
        verts = vertex_indices[start:start + total]
        mask[f] = bool(vertex_flags[verts].all()) if mode == 'ALL' else bool(vertex_flags[verts].any())

    return mask
