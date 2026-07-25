"""Pure pre-flight analysis for the merge feature. No bpy.types here."""


def analyze_join_candidates(selected_objects, active_object):
    """Returns a list of (level, text) issues to show the user before joining meshes into active_object."""
    mesh_objs = [o for o in selected_objects if o.type == 'MESH']

    if len(mesh_objs) < 2:
        return [('WARNING', "結合するには2つ以上のメッシュオブジェクトを選択してください")]
    if active_object not in mesh_objs:
        return [('WARNING', "結合先(アクティブオブジェクト)がメッシュオブジェクトではありません")]

    other_objs = [o for o in mesh_objs if o is not active_object]
    issues = []

    shape_key_objs = [o.name for o in other_objs if o.data.shape_keys and len(o.data.shape_keys.key_blocks) > 1]
    if shape_key_objs:
        issues.append((
            'ERROR',
            "シェイプキーを含むオブジェクトが結合対象です(結合先以外のシェイプキーは失われます): "
            + ", ".join(shape_key_objs),
        ))

    def armature_targets(obj):
        return {m.object for m in obj.modifiers if m.type == 'ARMATURE' and m.object}

    active_armatures = armature_targets(active_object)
    mismatched_armature = [o.name for o in other_objs if armature_targets(o) != active_armatures]
    if mismatched_armature:
        issues.append((
            'WARNING',
            "結合先とアーマチュアモディファイアの参照先が異なるオブジェクトがあります: " + ", ".join(mismatched_armature),
        ))

    active_uv_names = {uv.name for uv in active_object.data.uv_layers}
    uv_mismatch = [o.name for o in other_objs if {uv.name for uv in o.data.uv_layers} != active_uv_names]
    if uv_mismatch:
        issues.append((
            'WARNING',
            "結合先とUVマップの名前構成が異なるオブジェクトがあります(意図しないUVのずれに注意): " + ", ".join(uv_mismatch),
        ))

    issues.append(('INFO', f"結合対象: {len(other_objs)} 個のオブジェクト → 結合先: {active_object.name}"))
    return issues
