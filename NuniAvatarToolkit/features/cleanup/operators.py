import bmesh
import bpy

from ...core.context_utils import (
    capture_selection_state, object_usability_error, reset_to_object_mode_with_active,
    restore_selection_state,
)
from ...core.report import set_report_lines
from . import utils


def _animation_owners():
    """Include embedded shader/compositor trees as well as standalone Blender IDs."""
    seen = set()
    for prop in bpy.data.bl_rna.properties:
        if prop.type != 'COLLECTION':
            continue
        for datablock in getattr(bpy.data, prop.identifier):
            for owner in (datablock, getattr(datablock, 'node_tree', None)):
                if owner is not None and owner not in seen:
                    seen.add(owner)
                    yield owner


def _material_slot_error(names):
    return ("マテリアル番号を使用するモディファイアがあるためスロットを削除できません: "
            + "、".join(names)
            + "。先にモディファイアを適用するか「未使用のマテリアルスロット」をオフにしてください")


def _analyze(props, obj):
    result = {}
    if props.remove_empty_vertex_groups:
        result['vertex_groups'] = utils.find_empty_vertex_groups(obj)
    if props.remove_noop_shape_keys:
        driver_keys = utils.get_driver_referenced_shape_key_names(obj, _animation_owners())
        result['shape_keys'] = utils.find_noop_shape_keys(obj, props.shape_key_noop_threshold, driver_keys)
    if props.remove_unused_uv_maps:
        result['uv_maps'] = utils.find_unused_uv_maps(obj)
    if props.remove_unused_vertex_colors:
        result['color_attributes'] = utils.find_unused_color_attributes(obj)
    if props.remove_unused_material_slots:
        result['unused_material_slot_count'] = utils.count_unused_material_slots(obj)
        if result['unused_material_slot_count']:
            result['material_slot_blockers'] = utils.material_slot_remapping_blockers(obj)
    if props.remove_loose_geometry:
        result['loose_verts'], result['loose_edges'] = utils.count_loose_geometry(obj)
    return result


def _report_lines_from_result(result):
    lines = []
    if 'vertex_groups' in result:
        lines.append(('INFO', f"空の頂点グループ: {len(result['vertex_groups'])} 個"))
    if 'shape_keys' in result:
        lines.append(('INFO', f"無効なシェイプキー: {len(result['shape_keys'])} 個"))
    if 'uv_maps' in result:
        lines.append(('INFO', f"未使用のUVマップ: {len(result['uv_maps'])} 個"))
    if 'color_attributes' in result:
        lines.append(('INFO', f"未使用の頂点カラー: {len(result['color_attributes'])} 個"))
    if 'unused_material_slot_count' in result:
        if result.get('material_slot_blockers'):
            lines.append(('WARNING', _material_slot_error(result['material_slot_blockers'])))
        else:
            lines.append(('INFO', f"未使用のマテリアルスロット: {result['unused_material_slot_count']} 個"))
    if 'loose_verts' in result:
        lines.append(('INFO', f"浮遊頂点: {result['loose_verts']} 個 / 浮遊エッジ: {result['loose_edges']} 個"))
    if not lines:
        lines.append(('WARNING', "チェック項目がひとつも有効になっていません"))
    return lines


class OBJECT_OT_amt_cleanup_scan(bpy.types.Operator):
    bl_idname = "object.amt_cleanup_scan"
    bl_label = "スキャン"
    bl_description = "対象メッシュを解析し、削除候補となる不要データを一覧表示します(削除は行いません)"
    bl_options = {'REGISTER'}

    @classmethod
    def poll(cls, context):
        props = context.scene.amt_cleanup
        return props.target_object is not None and props.target_object.type == 'MESH'

    def execute(self, context):
        props = context.scene.amt_cleanup
        obj = props.target_object
        error = object_usability_error(context, obj, "対象メッシュ")
        if error:
            self.report({'ERROR'}, error)
            return {'CANCELLED'}
        # Copy current edit data (including edited shape keys) without leaving Edit Mode.
        if obj.data.is_editmode:
            obj.update_from_editmode()
        result = _analyze(props, obj)
        set_report_lines(props.report_lines, _report_lines_from_result(result))
        self.report({'INFO'}, "スキャンが完了しました")
        return {'FINISHED'}


class OBJECT_OT_amt_cleanup_execute(bpy.types.Operator):
    bl_idname = "object.amt_cleanup_execute"
    bl_label = "削除を実行"
    bl_description = "現在チェックが入っている項目の不要データを実際に削除します"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        props = context.scene.amt_cleanup
        return props.target_object is not None and props.target_object.type == 'MESH'

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self, width=420)

    def draw(self, context):
        col = self.layout.column(align=True)
        col.label(text="チェックが入っている項目の不要データを削除します。", icon='ERROR')
        col.label(text="作業前にファイルを保存することを推奨します。")

    def execute(self, context):
        props = context.scene.amt_cleanup
        obj = props.target_object
        error = object_usability_error(
            context, obj, "対象メッシュ", require_editable=True,
            require_visible=props.remove_loose_geometry, require_single_user=True,
        )
        if error:
            self.report({'ERROR'}, error)
            return {'CANCELLED'}

        previous_state = capture_selection_state(context)
        removed_summary = []
        try:
            # Leaving Edit Mode must precede analysis: Mesh/Key data can otherwise be stale.
            reset_to_object_mode_with_active(context, obj)
            result = _analyze(props, obj)
            if result.get('material_slot_blockers'):
                self.report({'ERROR'}, _material_slot_error(result['material_slot_blockers']))
                return {'CANCELLED'}
            if result.get('unused_material_slot_count') and not bpy.ops.object.material_slot_remove_unused.poll():
                self.report({'ERROR'}, "マテリアルスロットを編集できません。対象メッシュの選択・表示状態を確認してください")
                return {'CANCELLED'}
            # Establish editability before deleting any attributes or keys.
            if props.remove_loose_geometry:
                bpy.ops.object.mode_set(mode='EDIT')
                bpy.ops.object.mode_set(mode='OBJECT')

            for name in result.get('vertex_groups', []):
                vg = obj.vertex_groups.get(name)
                if vg:
                    obj.vertex_groups.remove(vg)
            if 'vertex_groups' in result:
                removed_summary.append(f"頂点グループ {len(result['vertex_groups'])} 個")

            for name in result.get('shape_keys', []):
                if obj.data.shape_keys:
                    kb = obj.data.shape_keys.key_blocks.get(name)
                    if kb:
                        obj.shape_key_remove(kb)
            if 'shape_keys' in result:
                removed_summary.append(f"シェイプキー {len(result['shape_keys'])} 個")

            for name in result.get('uv_maps', []):
                uv = obj.data.uv_layers.get(name)
                if uv:
                    obj.data.uv_layers.remove(uv)
            if 'uv_maps' in result:
                removed_summary.append(f"UVマップ {len(result['uv_maps'])} 個")

            for name in result.get('color_attributes', []):
                attr = obj.data.color_attributes.get(name)
                if attr:
                    obj.data.color_attributes.remove(attr)
            if 'color_attributes' in result:
                removed_summary.append(f"頂点カラー {len(result['color_attributes'])} 個")

            if result.get('unused_material_slot_count'):
                bpy.ops.object.material_slot_remove_unused()
                removed_summary.append("未使用マテリアルスロット")

            report_lines = [('INFO', "削除が完了しました。再スキャンして結果を確認してください")]
            if props.remove_loose_geometry:
                # Edit-mode bmesh keeps shape keys and other layers in sync when written back.
                bpy.ops.object.mode_set(mode='EDIT')
                try:
                    bm = bmesh.from_edit_mesh(obj.data)
                    removed_verts, removed_edges = utils.delete_loose_geometry(bm)
                    bmesh.update_edit_mesh(obj.data)
                finally:
                    bpy.ops.object.mode_set(mode='OBJECT')
                loose_text = f"浮遊頂点 {removed_verts} 個・浮遊エッジ {removed_edges} 個"
                removed_summary.append(loose_text)
                report_lines.append(('INFO', f"{loose_text}を削除しました"))
            set_report_lines(props.report_lines, report_lines)
        finally:
            restore_selection_state(context, previous_state)

        if removed_summary:
            self.report({'INFO'}, "削除しました: " + "、".join(removed_summary))
        else:
            self.report({'WARNING'}, "削除対象の項目が有効になっていません")
        return {'FINISHED'}


_classes = (OBJECT_OT_amt_cleanup_scan, OBJECT_OT_amt_cleanup_execute)


def register():
    for cls in _classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
