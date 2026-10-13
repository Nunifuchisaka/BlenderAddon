import bpy
import numpy as np

from ...core.context_utils import (
    capture_selection_state, object_usability_error, reset_to_object_mode_with_active, restore_selection_state,
)
from ...core.mesh_eval import build_bvh_from_objects, transform_points
from ...core.report import set_report_lines
from . import utils


def _find_shape_key(obj, name):
    shape_keys = obj.data.shape_keys
    if shape_keys is None:
        return None
    return shape_keys.key_blocks.get(name)


_BASIS_KEY_NAME = "Basis"


def _get_or_create_shape_key(obj, name):
    """Return the shape key to write into, creating it (and a Basis key) when missing.

    An existing key is reused as-is so its slider range, vertex group, and any keys that
    use it as relative_key survive a re-run; only its coordinates are overwritten later.
    """
    if obj.data.shape_keys is None:
        obj.shape_key_add(name=_BASIS_KEY_NAME, from_mix=False)
    existing = obj.data.shape_keys.key_blocks.get(name)
    if existing is not None:
        return existing
    return obj.shape_key_add(name=name, from_mix=False)


def _write_fit_shape_key(obj, name, fitted_local):
    """Commit the already computed result, rolling back even a partially created key."""
    shape_keys = obj.data.shape_keys
    previous_names = set(shape_keys.key_blocks.keys()) if shape_keys is not None else set()
    existing = _find_shape_key(obj, name)
    previous_coordinates = None
    previous_value = existing.value if existing is not None else None
    if existing is not None:
        previous_coordinates = np.empty(len(existing.data) * 3, dtype=np.float32)
        existing.data.foreach_get('co', previous_coordinates)
    previous_active = obj.active_shape_key_index
    previous_show_only = obj.show_only_shape_key
    try:
        key_block = _get_or_create_shape_key(obj, name)
        key_block.data.foreach_set('co', np.ascontiguousarray(fitted_local, dtype=np.float32).ravel())
        key_block.value = 1.0
        obj.active_shape_key_index = obj.data.shape_keys.key_blocks.find(key_block.name)
        obj.show_only_shape_key = False
        obj.data.update()
    except Exception:
        if existing is not None:
            existing.data.foreach_set('co', previous_coordinates)
            existing.value = previous_value
        if obj.data.shape_keys is not None:
            for key_block in reversed(list(obj.data.shape_keys.key_blocks)):
                if key_block.name not in previous_names:
                    obj.shape_key_remove(key_block)
        obj.active_shape_key_index = previous_active
        obj.show_only_shape_key = previous_show_only
        obj.data.update()
        raise


class OBJECT_OT_amt_cloth_fit(bpy.types.Operator):
    bl_idname = "object.amt_cloth_fit"
    bl_label = "フィットしてシェイプキーを作成"
    bl_description = (
        "指定した頂点グループの範囲のうち、ボディメッシュに埋まっている頂点だけを"
        "体表面まで押し出し、その結果をシェイプキーとして服メッシュへ追加します"
    )
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        props = context.scene.amt_cloth_fit
        return props.body_object is not None and props.clothing_object is not None

    def invoke(self, context, event):
        props = context.scene.amt_cloth_fit
        clothing_object = props.clothing_object
        shape_key_name = props.shape_key_name.strip()
        if (
            clothing_object is not None and clothing_object.type == 'MESH'
            and shape_key_name and _find_shape_key(clothing_object, shape_key_name) is not None
        ):
            return context.window_manager.invoke_props_dialog(self, width=420)
        return self.execute(context)

    def draw(self, context):
        props = context.scene.amt_cloth_fit
        col = self.layout.column(align=True)
        col.label(text=f"シェイプキー「{props.shape_key_name.strip()}」は上書きされます。", icon='ERROR')
        col.label(text="以前のフィット結果は失われます。")

    def execute(self, context):
        props = context.scene.amt_cloth_fit
        body_object = props.body_object
        clothing_object = props.clothing_object
        shape_key_name = props.shape_key_name.strip()

        try:
            # Read edit-mode geometry only after the context has been synchronized below.
            utils.validate_fit_setup(body_object, clothing_object, props.vertex_group, require_vertices=False)
        except ValueError as exc:
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}

        if not shape_key_name:
            self.report({'ERROR'}, "シェイプキー名を入力してください")
            return {'CANCELLED'}

        error = object_usability_error(context, body_object, "ボディメッシュ")
        error = error or object_usability_error(
            context, clothing_object, "服メッシュ", require_editable=True, require_visible=True, require_single_user=True,
        )
        if error:
            self.report({'ERROR'}, error)
            return {'CANCELLED'}

        existing_key = _find_shape_key(clothing_object, shape_key_name)
        # Without shape keys a Basis key is created first, so that name would also hit the reference key.
        would_be_reference = (
            existing_key == clothing_object.data.shape_keys.reference_key if existing_key is not None
            else clothing_object.data.shape_keys is None and shape_key_name == _BASIS_KEY_NAME
        )
        if would_be_reference:
            self.report({'ERROR'}, f"「{shape_key_name}」はベースのシェイプキーのため上書きできません")
            return {'CANCELLED'}
        if existing_key is not None and existing_key.relative_key == existing_key:
            self.report(
                {'ERROR'},
                f"シェイプキー「{shape_key_name}」が自身を相対キーに指定しているため変形が反映されません。"
                "相対キーをベースなど別のキーに設定してから実行してください",
            )
            return {'CANCELLED'}
        if existing_key is not None and existing_key.mute:
            self.report(
                {'ERROR'},
                f"シェイプキー「{shape_key_name}」はミュートされているため変形が反映されません。"
                "ミュートを解除するか、別のシェイプキー名で実行してください",
            )
            return {'CANCELLED'}
        if existing_key is not None and not existing_key.slider_min <= 1.0 <= existing_key.slider_max:
            self.report(
                {'ERROR'},
                f"シェイプキー「{shape_key_name}」のスライダー範囲"
                f"({existing_key.slider_min:g} ～ {existing_key.slider_max:g})には値1.0が含まれていません。"
                "範囲を変更するか、別のシェイプキー名で実行してください",
            )
            return {'CANCELLED'}

        previous_state = capture_selection_state(context)
        switched_armatures = []
        finished = False
        try:
            reset_to_object_mode_with_active(context, clothing_object)
            utils.validate_fit_setup(body_object, clothing_object, props.vertex_group)
            weights = utils.get_vertex_group_weights(clothing_object, props.vertex_group)
            target_count = int(np.count_nonzero(weights > 0.0))
            if target_count == 0:
                raise ValueError(f"頂点グループ「{props.vertex_group}」に頂点が登録されていません")

            switched_armatures = utils.force_rest_pose((body_object, clothing_object))
            if switched_armatures:
                context.view_layer.update()

            depsgraph = context.evaluated_depsgraph_get()
            bvh, _aabb_min, _aabb_max = build_bvh_from_objects(depsgraph, [body_object])
            if bvh is None:
                raise ValueError("ボディメッシュに面がありません")

            matrix_world = clothing_object.matrix_world.copy()
            if not np.isfinite(np.array(matrix_world, dtype=np.float64)).all():
                raise ValueError("服メッシュの変換に無効な数値があります。位置・回転・スケールを確認してください")
            try:
                inverse_world = matrix_world.inverted()
            except ValueError as exc:
                raise ValueError("服メッシュのスケールが0のためフィットできません。親オブジェクトのスケールも確認してください") from exc

            # Start from the base mesh, never from a previous fit stored in a reused key.
            vertex_count = len(clothing_object.data.vertices)
            local_co = np.empty(vertex_count * 3, dtype=np.float64)
            clothing_object.data.vertices.foreach_get('co', local_co)
            local_co = local_co.reshape(vertex_count, 3)

            world_co = transform_points(local_co, matrix_world)

            fitted_world, moved_mask, max_move = utils.compute_fitted_positions(
                world_co, weights, bvh, props.offset, props.max_search_distance,
            )

            fitted_local = transform_points(fitted_world, inverse_world)
            # A reused key may be relative to another key; Blender applies (key - relative_key),
            # so offset by that key to keep the same deformation as a Basis-relative key.
            shape_keys = clothing_object.data.shape_keys
            existing_key = _find_shape_key(clothing_object, shape_key_name)
            relative_key = existing_key.relative_key if existing_key is not None else None
            if (
                relative_key is not None
                and relative_key != shape_keys.reference_key and relative_key != existing_key
            ):
                relative_co = np.empty(vertex_count * 3, dtype=np.float64)
                relative_key.data.foreach_get('co', relative_co)
                fitted_local = fitted_local + (relative_co.reshape(vertex_count, 3) - local_co)
            # Shape keys are mutated only after evaluation and the full fit computation succeed.
            _write_fit_shape_key(clothing_object, shape_key_name, fitted_local)
            finished = True
        except Exception as exc:
            self.report({'ERROR'}, f"服メッシュのフィットに失敗しました: {exc}")
            return {'CANCELLED'}
        finally:
            if switched_armatures:
                utils.restore_pose_positions(switched_armatures)
                context.view_layer.update()
            if not finished:
                restore_selection_state(context, previous_state)

        moved_count = int(np.count_nonzero(moved_mask))
        lines = [
            ('INFO', f"対象頂点: {target_count} 個(頂点グループ「{props.vertex_group}」)"),
            ('INFO', f"押し出した頂点: {moved_count} 個 / 最大移動量: {max_move:.4f} m"),
            ('INFO', f"シェイプキー「{shape_key_name}」を値1.0で追加しました"),
        ]
        if moved_count == 0:
            lines.append(('WARNING', "体に埋まっている頂点が見つかりませんでした。対象範囲や最大探索距離を確認してください"))
        if switched_armatures:
            lines.append(('INFO', "計算中はArmatureをレストポーズとして扱いました"))
        set_report_lines(props.report_lines, lines)

        self.report({'INFO'}, f"シェイプキー「{shape_key_name}」を作成しました({moved_count} 頂点を押し出し)")
        return {'FINISHED'}


_classes = (OBJECT_OT_amt_cloth_fit,)


def register():
    for cls in _classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
