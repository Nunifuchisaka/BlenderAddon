"""Pure fitting logic for pushing sunken clothing vertices out to the body surface. No bpy.types here."""

import numpy as np
from mathutils import Vector


def validate_fit_setup(body_object, clothing_object, vertex_group_name):
    if body_object is None:
        raise ValueError("ボディメッシュを指定してください")
    if body_object.type != 'MESH':
        raise ValueError("ボディメッシュにはメッシュオブジェクトを指定してください")
    if clothing_object is None:
        raise ValueError("服メッシュを指定してください")
    if clothing_object.type != 'MESH':
        raise ValueError("服メッシュにはメッシュオブジェクトを指定してください")
    if body_object == clothing_object:
        raise ValueError("ボディメッシュと服メッシュに同じオブジェクトが指定されています")
    if clothing_object.library is not None or clothing_object.override_library is not None:
        raise ValueError("服メッシュはリンクされているため変更できません")
    if len(clothing_object.data.vertices) == 0:
        raise ValueError("服メッシュに頂点がありません")
    if not vertex_group_name:
        raise ValueError("対象頂点グループを指定してください")
    if vertex_group_name not in clothing_object.vertex_groups:
        raise ValueError(f"頂点グループ「{vertex_group_name}」が服メッシュに見つかりません")


def get_vertex_group_weights(obj, group_name):
    """Per-vertex weight in group_name as a (V,) float64 array. Vertices outside the group are 0.0."""
    n = len(obj.data.vertices)
    weights = np.zeros(n, dtype=np.float64)
    group = obj.vertex_groups.get(group_name)
    if group is None:
        return weights
    group_index = group.index
    for i, vert in enumerate(obj.data.vertices):
        for g in vert.groups:
            if g.group == group_index:
                weights[i] = min(1.0, max(0.0, g.weight))
                break
    return weights


def collect_driving_armatures(objects):
    """Armature objects that deform any of objects, via an Armature modifier or object parenting."""
    found = []
    for obj in objects:
        if obj is None:
            continue
        for modifier in obj.modifiers:
            if modifier.type == 'ARMATURE' and modifier.object is not None:
                found.append(modifier.object)
        if obj.parent is not None and obj.parent.type == 'ARMATURE':
            found.append(obj.parent)

    unique = []
    for armature in found:
        if all(armature != existing for existing in unique):
            unique.append(armature)
    return unique


def force_rest_pose(objects):
    """Temporarily put every driving armature into rest position. Returns [(armature, prev_position), ...].

    Shape keys store coordinates of the base mesh, which is evaluated before any
    Armature modifier. Fitting against a posed body would therefore bake the pose
    into the shape key, so the pose is suspended for the duration of the computation.
    """
    switched = []
    for armature in collect_driving_armatures(objects):
        if armature.data.pose_position != 'REST':
            switched.append((armature, armature.data.pose_position))
            armature.data.pose_position = 'REST'
    return switched


def restore_pose_positions(switched):
    for armature, prev_position in switched:
        armature.data.pose_position = prev_position


def compute_fitted_positions(world_co, weights, bvh, offset, max_distance):
    """Push vertices that sit inside the body out to its surface, scaled by their vertex-group weight.

    Vertices already outside the body are left untouched so the garment silhouette is kept.
    Returns (fitted_world_co: (V,3) float64, moved_mask: (V,) bool, max_move: float).
    """
    fitted = world_co.copy()
    moved = np.zeros(len(world_co), dtype=bool)
    max_move = 0.0

    search_distance = max_distance if max_distance > 0.0 else None

    for index in np.nonzero(weights > 0.0)[0]:
        origin = Vector(world_co[index])
        if search_distance is None:
            location, normal, _face_index, _distance = bvh.find_nearest(origin)
        else:
            location, normal, _face_index, _distance = bvh.find_nearest(origin, search_distance)
        if location is None:
            continue
        # Positive dot means the vertex is on the outer side of the closest surface point.
        if (origin - location).dot(normal) >= 0.0:
            continue

        target = location + normal * offset
        result = origin.lerp(target, float(weights[index]))
        fitted[index] = (result.x, result.y, result.z)
        moved[index] = True
        max_move = max(max_move, (result - origin).length)

    return fitted, moved, max_move
