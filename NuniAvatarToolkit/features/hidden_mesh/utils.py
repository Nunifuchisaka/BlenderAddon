"""Pure occlusion-detection logic for the hidden-mesh-removal feature. No bpy.types here."""

import math
from functools import lru_cache

import numpy as np
from mathutils import Vector

PERFORMANCE_WARNING_VERTEX_SAMPLES = 300_000
RAY_MAX_DISTANCE_FACTOR = 10.0
SELF_HIT_MAX_WALKS = 4
SAFETY_MARGIN_RINGS = {
    'NONE': 0,
    'SMALL': 1,
    'MEDIUM': 2,
    'LARGE': 3,
}

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


def inset_hidden_face_mask(mesh, hidden_face_mask, safety_margin):
    """Shrink hidden faces inward by shared-edge rings.

    Each pass removes hidden faces touching a currently-visible face. This keeps
    a configurable belt of body geometry beneath clothing boundaries so pose and
    cloth deformation are less likely to expose holes.
    """
    rings = SAFETY_MARGIN_RINGS.get(safety_margin)
    if rings is None:
        raise ValueError(f"不明な安全余白です: {safety_margin}")

    result = np.asarray(hidden_face_mask, dtype=bool).copy()
    if rings == 0 or not result.any():
        return result

    edge_faces = {}
    for face_index, polygon in enumerate(mesh.polygons):
        for edge_key in polygon.edge_keys:
            edge_faces.setdefault(tuple(sorted(edge_key)), []).append(face_index)

    neighbors = [set() for _ in range(len(mesh.polygons))]
    for face_indices in edge_faces.values():
        for face_index in face_indices:
            neighbors[face_index].update(other for other in face_indices if other != face_index)

    for _ in range(rings):
        boundary = [
            face_index
            for face_index, hidden in enumerate(result)
            if hidden and any(not result[other] for other in neighbors[face_index])
        ]
        if not boundary:
            break
        result[boundary] = False

    return result
