"""Helpers for preparing a mesh for rigid bone weighting before it is joined."""


def validate_weight_setup(target_object, armature_object, bone_name, allow_edit_mode=False):
    if target_object is None:
        raise ValueError("対象メッシュを指定してください")
    if target_object.type != 'MESH':
        raise ValueError("対象にはメッシュオブジェクトを指定してください")
    if armature_object is None:
        raise ValueError("Armatureを指定してください")
    if armature_object.type != 'ARMATURE':
        raise ValueError("追従先にはArmatureを指定してください")
    if not bone_name:
        raise ValueError("ボーンを指定してください")
    if bone_name not in armature_object.data.bones:
        raise ValueError(f"ボーン「{bone_name}」が見つかりません")
    if target_object.library is not None or target_object.override_library is not None:
        raise ValueError("対象メッシュはリンクされているためウェイトを変更できません")
    if target_object.parent_type == 'BONE':
        raise ValueError(
            "対象メッシュはBone Parentされています。二重追従を防ぐため、先に親子関係を解除してください"
        )
    if not allow_edit_mode and getattr(target_object, 'mode', 'OBJECT') == 'EDIT':
        raise ValueError("対象メッシュが編集モードのため、オブジェクトモードに戻してから実行してください")
    if len(target_object.data.vertices) == 0:
        raise ValueError("対象メッシュに頂点がありません")


def _find_or_create_armature_modifier(target_object, armature_object):
    armature_modifiers = [
        modifier for modifier in target_object.modifiers
        if modifier.type == 'ARMATURE'
    ]
    for modifier in armature_modifiers:
        if modifier.object == armature_object:
            return modifier, False

    unassigned_modifier = next(
        (modifier for modifier in armature_modifiers if modifier.object is None), None,
    )
    if unassigned_modifier is not None:
        unassigned_modifier.object = armature_object
        return unassigned_modifier, False

    conflicting_modifier = next(
        (modifier for modifier in armature_modifiers if modifier.object is not None), None,
    )
    if conflicting_modifier is not None:
        raise ValueError(
            "対象メッシュに別のArmatureモディファイアが設定されています。"
            "結合先と同じArmatureへ変更してから実行してください"
        )

    modifier = target_object.modifiers.new("Armature", 'ARMATURE')
    modifier.object = armature_object
    modifier.use_bone_envelopes = False
    modifier.use_vertex_groups = True
    return modifier, True


def assign_rigid_bone_weight(target_object, armature_object, bone_name):
    """Assign every vertex to one bone at weight 1.0 for later mesh joining.

    Existing weights for bones in the selected Armature are cleared first, while
    unrelated vertex groups (for example, modifier masks) are preserved.
    """
    validate_weight_setup(target_object, armature_object, bone_name)
    modifier, modifier_created = _find_or_create_armature_modifier(
        target_object, armature_object,
    )

    vertex_indices = [vertex.index for vertex in target_object.data.vertices]
    armature_bone_names = {bone.name for bone in armature_object.data.bones}
    for group in target_object.vertex_groups:
        if group.name in armature_bone_names:
            group.remove(vertex_indices)

    group = target_object.vertex_groups.get(bone_name)
    if group is None:
        group = target_object.vertex_groups.new(name=bone_name)
    group.add(vertex_indices, 1.0, 'REPLACE')

    return {
        'modifier': modifier,
        'modifier_created': modifier_created,
        'vertex_count': len(vertex_indices),
    }
