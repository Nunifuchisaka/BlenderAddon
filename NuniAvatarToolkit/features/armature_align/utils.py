"""Pure logic for features/armature_align. No bpy.types classes are defined here,
but the functions directly use bpy.types.Object/Armature data, so this module
cannot be imported outside Blender runtime.
"""

import math

import bpy
from mathutils import Matrix


_TRANSFORM_CHANNELS = (
    'rotation_mode', 'location', 'rotation_euler', 'rotation_quaternion',
    'rotation_axis_angle', 'scale', 'delta_location', 'delta_rotation_euler',
    'delta_rotation_quaternion', 'delta_scale',
)


def capture_transform_channels(obj):
    """Capture raw channels, rather than decomposing the evaluated constrained matrix."""
    return {
        name: value if isinstance(value, str) else tuple(value)
        for name in _TRANSFORM_CHANNELS
        for value in (getattr(obj, name),)
    }


def restore_transform_channels(obj, channels):
    for name, value in channels.items():
        setattr(obj, name, value)


def _close_values(before, after, tolerance=1e-6):
    return all(
        math.isfinite(a) and math.isfinite(b)
        and abs(a - b) <= tolerance * max(1.0, abs(a), abs(b))
        for a, b in zip(before, after)
    )


def preserves_rotation_scale(obj, channels, world_linear):
    """Check raw rotation/scale/deltas and the evaluated linear transform, including shear."""
    for name, value in channels.items():
        if name == 'location':
            continue
        current = getattr(obj, name)
        if isinstance(value, str):
            if current != value:
                return False
        elif not _close_values(value, current):
            return False
    current_linear = obj.matrix_world.to_3x3()
    return all(
        _close_values(before_row, after_row, tolerance=1e-5)
        for before_row, after_row in zip(world_linear, current_linear)
    )


def find_hips_bone(armature_data):
    """Search armature_data.bones for a bone name containing "hips" (case-insensitive).
    An exact match (case-insensitive equality to "hips") is preferred over a substring
    match, so "Hips" is chosen over "Hips_end" when both exist.
    Returns "" if no matching bone is found."""
    exact_match = ""
    partial_match = ""
    for bone in armature_data.bones:
        lower_name = bone.name.lower()
        if lower_name == "hips":
            exact_match = bone.name
            break
        if "hips" in lower_name and not partial_match:
            partial_match = bone.name
    return exact_match or partial_match


def get_bone_rest_world_head(obj, bone_name):
    """Return the world-space rest-pose head position of bone_name on obj (an Armature object).
    obj.data.bones[bone_name].head_local is in armature-object-local space at rest pose;
    multiplying by obj.matrix_world yields world coordinates even when obj.location is (0, 0, 0).
    Raises ValueError if bone_name does not exist on obj."""
    if obj is None or obj.type != 'ARMATURE':
        raise ValueError("位置合わせにはArmatureを指定してください")
    if obj.mode == 'EDIT' or obj.data.is_editmode:
        raise ValueError(
            f"Armature「{obj.name}」が編集モードです。オブジェクトモードに戻してから実行してください"
        )
    if bone_name not in obj.data.bones:
        raise ValueError(f"ボーン「{bone_name}」が見つかりません")
    bone = obj.data.bones[bone_name]
    head = obj.matrix_world @ bone.head_local
    if not all(math.isfinite(value) for value in head):
        raise ValueError(f"Armature「{obj.name}」のボーン位置が不正です")
    return head


def compute_alignment_delta(reference_object, reference_bone, target_object, target_bone):
    """Return the world-space translation vector that would move target_bone's rest head
    onto reference_bone's rest head."""
    reference_head = get_bone_rest_world_head(reference_object, reference_bone)
    target_head = get_bone_rest_world_head(target_object, target_bone)
    return reference_head - target_head


def find_orphan_armature_meshes(target_object, objects=None):
    """Return names of mesh objects (the given ones, default all of bpy.data) that have an Armature
    modifier referencing target_object, but are not descendants of target_object. These meshes will
    not follow target_object when it is moved, since only the armature object itself is translated."""
    orphans = []
    for obj in (bpy.data.objects if objects is None else objects):
        if obj.type != 'MESH':
            continue
        references_target = any(
            mod.type == 'ARMATURE' and mod.object == target_object
            for mod in obj.modifiers
        )
        if not references_target:
            continue
        ancestor = obj.parent
        is_descendant = False
        while ancestor is not None:
            if ancestor == target_object:
                is_descendant = True
                break
            ancestor = ancestor.parent
        if not is_descendant:
            orphans.append(obj.name)
    return orphans


def apply_alignment(target_object, delta):
    """Change only location, converting the world delta through the effective parent.

    Assigning matrix_world would bake constraint rotation/scale into raw channels.
    Constraints that alter this translation are handled by the operator's postcondition.
    """
    parent = target_object.parent
    if parent is None:
        parent_linear = Matrix.Identity(3)
    else:
        parent_matrix = parent.matrix_world.copy()
        if target_object.parent_type == 'BONE':
            pose_bone = parent.pose.bones.get(target_object.parent_bone)
            if pose_bone is None:
                raise ValueError("親ボーンが見つからないため位置合わせできません")
            parent_matrix @= pose_bone.matrix
            if pose_bone.bone.use_relative_parent:
                parent_matrix @= pose_bone.bone.matrix_local.inverted()
        elif target_object.parent_type != 'OBJECT':
            raise ValueError("この親子関係では安全に位置合わせできません。親子関係を確認してください")
        parent_linear = (parent_matrix @ target_object.matrix_parent_inverse).to_3x3()
    try:
        local_delta = parent_linear.inverted() @ delta
    except ValueError as exc:
        raise ValueError("親のスケールが0のため位置合わせできません") from exc
    if not all(math.isfinite(value) for value in local_delta):
        raise ValueError("親の変換が不正なため位置合わせできません")
    target_object.location += local_delta
