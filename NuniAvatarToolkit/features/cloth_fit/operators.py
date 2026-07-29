import bpy
import numpy as np

from ...core.context_utils import reset_to_object_mode_with_active
from ...core.mesh_eval import build_bvh_from_objects
from ...core.report import set_report_lines
from . import utils


def _find_shape_key(obj, name):
    shape_keys = obj.data.shape_keys
    if shape_keys is None:
        return None
    return shape_keys.key_blocks.get(name)


def _create_shape_key(obj, name):
    """Add (or replace) a shape key copied from the base mesh, creating a Basis key when missing."""
    if obj.data.shape_keys is None:
        obj.shape_key_add(name="Basis", from_mix=False)
    existing = obj.data.shape_keys.key_blocks.get(name)
    if existing is not None:
        obj.shape_key_remove(existing)
    return obj.shape_key_add(name=name, from_mix=False)


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
            utils.validate_fit_setup(body_object, clothing_object, props.vertex_group)
        except ValueError as exc:
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}

        if not shape_key_name:
            self.report({'ERROR'}, "シェイプキー名を入力してください")
            return {'CANCELLED'}

        existing_key = _find_shape_key(clothing_object, shape_key_name)
        if existing_key is not None and existing_key == clothing_object.data.shape_keys.reference_key:
            self.report({'ERROR'}, f"「{shape_key_name}」はベースのシェイプキーのため上書きできません")
            return {'CANCELLED'}

        weights = utils.get_vertex_group_weights(clothing_object, props.vertex_group)
        target_count = int(np.count_nonzero(weights > 0.0))
        if target_count == 0:
            self.report({'ERROR'}, f"頂点グループ「{props.vertex_group}」に頂点が登録されていません")
            return {'CANCELLED'}

        reset_to_object_mode_with_active(context, clothing_object)

        switched_armatures = utils.force_rest_pose((body_object, clothing_object))
        try:
            if switched_armatures:
                context.view_layer.update()

            depsgraph = context.evaluated_depsgraph_get()
            bvh, _aabb_min, _aabb_max = build_bvh_from_objects(depsgraph, [body_object])
            if bvh is None:
                self.report({'ERROR'}, "ボディメッシュに面がありません")
                return {'CANCELLED'}

            key_block = _create_shape_key(clothing_object, shape_key_name)
            matrix_world = clothing_object.matrix_world.copy()

            vertex_count = len(clothing_object.data.vertices)
            local_co = np.empty(vertex_count * 3, dtype=np.float64)
            key_block.data.foreach_get('co', local_co)
            local_co = local_co.reshape(vertex_count, 3)

            mw = np.array(matrix_world, dtype=np.float64)
            world_co = local_co @ mw[:3, :3].T + mw[:3, 3]

            fitted_world, moved_mask, max_move = utils.compute_fitted_positions(
                world_co, weights, bvh, props.offset, props.max_search_distance,
            )

            inv = np.array(matrix_world.inverted_safe(), dtype=np.float64)
            fitted_local = fitted_world @ inv[:3, :3].T + inv[:3, 3]
            # float32 matches the shape key's own storage, so foreach_set takes the fast buffer path.
            key_block.data.foreach_set('co', np.ascontiguousarray(fitted_local, dtype=np.float32).ravel())

            key_block.value = 1.0
            clothing_object.active_shape_key_index = (
                clothing_object.data.shape_keys.key_blocks.find(shape_key_name)
            )
            clothing_object.show_only_shape_key = False
            clothing_object.data.update()
        finally:
            if switched_armatures:
                utils.restore_pose_positions(switched_armatures)
                context.view_layer.update()

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
