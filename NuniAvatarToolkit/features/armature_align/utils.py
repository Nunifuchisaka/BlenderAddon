"""Pure logic for features/armature_align. No bpy.types classes are defined here,
but the functions directly use bpy.types.Object/Armature data, so this module
cannot be imported outside Blender runtime.
"""

import bpy


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
    if bone_name not in obj.data.bones:
        raise ValueError(f"ボーン「{bone_name}」が見つかりません")
    bone = obj.data.bones[bone_name]
    return obj.matrix_world @ bone.head_local


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
    """Translate target_object by delta in world space. Using matrix_world (rather than
    directly adding to target_object.location) correctly accounts for any parent's
    rotation/scale, so the requested world-space delta is achieved even when target_object
    is parented to another object."""
    mw = target_object.matrix_world.copy()
    mw.translation += delta
    target_object.matrix_world = mw
