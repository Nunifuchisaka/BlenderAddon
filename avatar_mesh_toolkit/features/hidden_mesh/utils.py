"""Pure occlusion-detection logic for the hidden-mesh-removal feature. No bpy.types here."""

import math
from functools import lru_cache

import numpy as np
from mathutils import Vector

PERFORMANCE_WARNING_VERTEX_SAMPLES = 300_000
RAY_MAX_DISTANCE_FACTOR = 10.0
SELF_HIT_MAX_WALKS = 4

# Hemisphere directions are clamped away from the equator (dot(dir, normal) >= DIRECTION_Z_MIN)
# since near-tangent rays carry little visibility information and are the main source of
# false "hidden" positives on curved surfaces.
DIRECTION_Z_MIN = 0.15


@lru_cache(maxsize=None)
def generate_hemisphere_directions(sample_count):
    """Fibonacci-hemisphere unit vectors in local +Z space, ordered normal-first for early-out."""
    golden_angle = math.pi * (3.0 - math.sqrt(5.0))
    directions = []
    for i in range(sample_count):
        z = DIRECTION_Z_MIN + (1.0 - DIRECTION_Z_MIN) * ((i + 0.5) / sample_count)
        radius = math.sqrt(max(0.0, 1.0 - z * z))
        theta = golden_angle * i
        directions.append(Vector((math.cos(theta) * radius, math.sin(theta) * radius, z)))
    directions.sort(key=lambda v: -v.z)
    return tuple(directions)


def get_clothing_objects(collection, exclude_obj):
    if collection is None:
        return []
    return [
        obj for obj in collection.all_objects
        if obj.type == 'MESH' and obj is not exclude_obj and obj.data and len(obj.data.vertices) > 0
    ]


def get_protected_vertex_mask(body_obj, group_name):
    n = len(body_obj.data.vertices)
    mask = np.zeros(n, dtype=bool)
    if not group_name:
        return mask
    group = body_obj.vertex_groups.get(group_name)
    if group is None:
        return mask
    group_index = group.index
    for i, vert in enumerate(body_obj.data.vertices):
        for g in vert.groups:
            if g.group == group_index and g.weight > 0.0:
                mask[i] = True
                break
    return mask


def _point_in_expanded_aabb(pos, mn, mx, margin):
    return (
        mn[0] - margin <= pos.x <= mx[0] + margin and
        mn[1] - margin <= pos.y <= mx[1] + margin and
        mn[2] - margin <= pos.z <= mx[2] + margin
    )


def _direction_blocked(origin, direction, max_distance, clothing_bvh, self_bvh, self_min_distance):
    if clothing_bvh is not None:
        hit = clothing_bvh.ray_cast(origin, direction, max_distance)
        if hit[0] is not None:
            return True

    if self_bvh is not None:
        # A ray starting on the body's own surface will graze immediately-adjacent
        # triangles at near-zero distance; only accept a self-hit as real occlusion
        # once it clears self_min_distance, walking past spurious near hits instead
        # of discarding the whole ray (which would wrongly treat e.g. the far side
        # of a genuinely enclosed cavity as blocked by nothing).
        cur_origin = origin
        remaining = max_distance
        for _ in range(SELF_HIT_MAX_WALKS):
            hit = self_bvh.ray_cast(cur_origin, direction, remaining)
            if hit[0] is None:
                break
            loc, _normal, _idx, dist = hit
            if dist >= self_min_distance:
                return True
            nudge = self_min_distance * 0.1
            cur_origin = loc + direction * nudge
            remaining -= (dist + nudge)
            if remaining <= 0:
                break

    return False


def iter_hidden_vertex_flags(positions, normals, flags, clothing_bvh, clothing_bounds,
                              self_bvh, protected_mask, sample_count, epsilon,
                              max_distance, self_min_distance):
    """Generator: writes flags[i] in place, yields once per vertex processed.

    Lets the caller (a modal operator) drive this one/several vertices per timer
    tick for a responsive UI, without needing to know anything about ray casting.
    """
    directions = generate_hemisphere_directions(sample_count)
    clothing_min, clothing_max = clothing_bounds
    has_clothing_bounds = clothing_min is not None
    margin = epsilon * 4.0

    for i in range(len(positions)):
        if protected_mask[i]:
            flags[i] = False
            yield
            continue

        pos = Vector(positions[i])
        normal = Vector(normals[i])

        skip_clothing = has_clothing_bounds and not _point_in_expanded_aabb(pos, clothing_min, clothing_max, margin)
        if skip_clothing and self_bvh is None:
            flags[i] = False
            yield
            continue

        effective_clothing_bvh = None if skip_clothing else clothing_bvh

        rot = normal.to_track_quat('Z', 'Y').to_matrix()
        origin = pos + normal * epsilon

        hidden = True
        for local_dir in directions:
            world_dir = rot @ local_dir
            if not _direction_blocked(origin, world_dir, max_distance, effective_clothing_bvh, self_bvh, self_min_distance):
                hidden = False
                break

        flags[i] = hidden
        yield


def compute_hidden_face_mask(mesh, hidden_flags, mode):
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
        mask[f] = bool(hidden_flags[verts].all()) if mode == 'ALL' else bool(hidden_flags[verts].any())

    return mask
