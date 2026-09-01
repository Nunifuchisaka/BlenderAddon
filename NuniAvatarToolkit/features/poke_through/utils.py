"""Pure poke-through detection logic. No bpy.types here."""

import numpy as np
from mathutils import Vector


def validate_check_setup(body_object, clothing_objects):
    if body_object is None or body_object.type != 'MESH':
        raise ValueError("ボディメッシュを指定してください")
    if len(body_object.data.vertices) == 0:
        raise ValueError("ボディメッシュに頂点がありません")
    if not clothing_objects:
        raise ValueError("服メッシュを1つ以上指定してください")
    for obj in clothing_objects:
        if obj.type != 'MESH':
            raise ValueError(f"「{obj.name}」はメッシュではありません")
        if obj == body_object:
            raise ValueError("ボディメッシュと同じオブジェクトが服メッシュに指定されています")


def get_protected_vertex_mask(obj, group_name):
    """Per-vertex bool mask of vertices carrying weight in group_name."""
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


def compute_protruding_vertex_flags(positions, bvh, protected_mask, threshold, max_distance):
    """Body vertices poking out through the clothing surface.

    For each vertex the nearest point on the merged clothing surface is looked up.
    A vertex with no clothing within max_distance is simply not covered by any
    garment (hands, head, feet) and is skipped - that distance limit is what keeps
    legitimately bare skin out of the result. Otherwise the sign of
    (vertex - nearest) . nearest_normal says which side of the cloth the vertex is
    on; a positive value beyond threshold means it sits outside, i.e. it pokes through.

    Returns (flags: (V,) bool, depths: (V,) float64) where depths holds the
    protrusion distance of flagged vertices and 0.0 elsewhere.
    """
    count = len(positions)
    flags = np.zeros(count, dtype=bool)
    depths = np.zeros(count, dtype=np.float64)

    for i in range(count):
        if protected_mask[i]:
            continue
        origin = Vector(positions[i])
        location, normal, _face_index, _distance = bvh.find_nearest(origin, max_distance)
        if location is None:
            continue
        depth = (origin - location).dot(normal)
        if depth > threshold:
            flags[i] = True
            depths[i] = depth

    return flags, depths
