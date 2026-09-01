import bpy
import numpy as np

from ...core.context_utils import reset_to_object_mode_with_active, select_faces_in_edit_mode
from ...core.mesh_eval import build_bvh_from_objects, compute_face_mask_from_vertex_flags, snapshot_deform_only
from ...core.report import set_report_lines
from . import utils


class OBJECT_OT_amt_add_poke_through_clothing(bpy.types.Operator):
    bl_idname = "object.amt_add_poke_through_clothing"
    bl_label = "服メッシュを追加"
    bl_description = "貫通を調べる対象の服メッシュの選択欄を追加します"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        props = context.scene.amt_poke_through
        props.clothing_objects.add()
        props.clothing_objects_index = len(props.clothing_objects) - 1
        return {'FINISHED'}


class OBJECT_OT_amt_remove_poke_through_clothing(bpy.types.Operator):
    bl_idname = "object.amt_remove_poke_through_clothing"
    bl_label = "服メッシュを削除"
    bl_description = "選択中の服メッシュ欄を一覧から削除します"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return len(context.scene.amt_poke_through.clothing_objects) > 0

    def execute(self, context):
        props = context.scene.amt_poke_through
        index = min(props.clothing_objects_index, len(props.clothing_objects) - 1)
        props.clothing_objects.remove(index)
        props.clothing_objects_index = min(index, max(0, len(props.clothing_objects) - 1))
        return {'FINISHED'}


class OBJECT_OT_amt_check_poke_through(bpy.types.Operator):
    bl_idname = "object.amt_check_poke_through"
    bl_label = "貫通をチェック"
    bl_description = (
        "服の表面より外側に出ているボディメッシュの面を検出し、編集モードで選択状態にします"
        "(削除・変形は行いません)"
    )
    bl_options = {'REGISTER'}

    @classmethod
    def poll(cls, context):
        props = context.scene.amt_poke_through
        if props.body_object is None or props.body_object.type != 'MESH':
            return False
        return any(item.object is not None for item in props.clothing_objects)

    def execute(self, context):
        props = context.scene.amt_poke_through
        body_object = props.body_object
        clothing_objects = [item.object for item in props.clothing_objects if item.object is not None]

        try:
            utils.validate_check_setup(body_object, clothing_objects)
        except ValueError as exc:
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}

        reset_to_object_mode_with_active(context, body_object)

        wm = context.window_manager
        wm.progress_begin(0, 1)
        try:
            depsgraph = context.evaluated_depsgraph_get()
            bvh, _aabb_min, _aabb_max = build_bvh_from_objects(depsgraph, clothing_objects)
            if bvh is None:
                self.report({'ERROR'}, "服メッシュに面がありません")
                return {'CANCELLED'}

            # The clothing only needs a surface to measure against, so it uses the fully
            # evaluated mesh above. The body instead is sampled per base-mesh vertex, so
            # the resulting flags stay 1:1 with obj.data and can drive a face selection.
            positions, _normals, used_evaluated = snapshot_deform_only(depsgraph, body_object)

            protected_mask = utils.get_protected_vertex_mask(body_object, props.exclude_vertex_group)
            flags, depths = utils.compute_protruding_vertex_flags(
                positions, bvh, protected_mask,
                props.protrusion_threshold, props.max_search_distance,
            )
        finally:
            wm.progress_end()

        mesh = body_object.data
        face_mask = compute_face_mask_from_vertex_flags(mesh, flags, props.face_select_mode)
        face_indices = np.flatnonzero(face_mask).tolist()

        vertex_count = int(flags.sum())
        lines = []
        if not used_evaluated:
            lines.append(('WARNING', "一部のモディファイア構成のため、変形前(レスト)座標で判定しました"))

        if not face_indices:
            lines.append(('INFO', "貫通は検出されませんでした"))
            if vertex_count:
                lines.append(('INFO', f"服の外に出ている頂点は {vertex_count} 個ありますが、判定モードの条件を満たす面はありません"))
            set_report_lines(props.report_lines, lines)
            self.report({'INFO'}, "貫通は検出されませんでした")
            return {'FINISHED'}

        select_faces_in_edit_mode(context, body_object, face_indices)

        max_depth = float(depths.max())
        lines.extend([
            ('WARNING', f"貫通面: {len(face_indices)} / {len(mesh.polygons)} 面を選択しました"),
            ('INFO', f"服の外に出ている頂点: {vertex_count} 個 / 最大突き出し量: {max_depth:.4f} m"),
            ('INFO', "服メッシュフィットで服を膨らませるか、隠れメッシュ削除で体側を削って対処してください"),
        ])
        set_report_lines(props.report_lines, lines)

        self.report({'INFO'}, f"{len(face_indices)} 面を貫通として選択しました(最大突き出し量 {max_depth:.4f} m)")
        return {'FINISHED'}


_classes = (
    OBJECT_OT_amt_add_poke_through_clothing,
    OBJECT_OT_amt_remove_poke_through_clothing,
    OBJECT_OT_amt_check_poke_through,
)


def register():
    for cls in _classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
