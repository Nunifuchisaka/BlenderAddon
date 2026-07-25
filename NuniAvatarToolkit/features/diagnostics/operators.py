import bpy

from ...core.report import set_report_lines
from . import utils


class OBJECT_OT_amt_diagnostics_run(bpy.types.Operator):
    bl_idname = "object.amt_diagnostics_run"
    bl_label = "診断を実行"
    bl_description = "アバターコレクション内のメッシュ/アーマチュアを解析し、統計情報と書き出し前チェック結果を表示します"
    bl_options = {'REGISTER'}

    @classmethod
    def poll(cls, context):
        return context.scene.amt_diagnostics.avatar_collection is not None

    def execute(self, context):
        props = context.scene.amt_diagnostics
        collection = props.avatar_collection
        depsgraph = context.evaluated_depsgraph_get()

        mesh_objs = utils.get_avatar_mesh_objects(collection)
        armature_objs = utils.get_avatar_armature_objects(collection)

        if not mesh_objs:
            set_report_lines(props.report_lines, [('WARNING', "コレクション内にメッシュオブジェクトが見つかりません")])
            return {'CANCELLED'}

        lines = []

        tris = utils.count_triangles(mesh_objs, depsgraph)
        lines.append(('INFO', f"ポリゴン数(三角形換算): {tris} 【目安: {utils.rank_for(tris, utils.TRIANGLE_THRESHOLDS)}】"))

        mats = utils.count_material_slots(mesh_objs)
        lines.append(('INFO', f"マテリアル数: {mats} 【目安: {utils.rank_for(mats, utils.MATERIAL_THRESHOLDS)}】"))

        bones = utils.count_bones(armature_objs)
        bone_rank = utils.rank_for(bones, utils.BONE_THRESHOLDS) if armature_objs else "N/A"
        lines.append(('INFO', f"ボーン数: {bones} 【目安: {bone_rank}】"))

        shape_keys = utils.count_shape_keys(mesh_objs)
        lines.append(('INFO', f"シェイプキー数(Basis除く): {shape_keys}"))

        lines.append(('WARNING', "※上記の目安はVRChatの基準を参考にした概算値です。最新の正確な基準は公式ドキュメントで確認してください"))
        lines.append(('INFO', "--- 書き出し前チェック ---"))

        any_issue = False
        for obj in mesh_objs:
            non_finite = utils.find_non_finite_vertices(obj)
            if non_finite > 0:
                any_issue = True
                lines.append(('ERROR', f"[{obj.name}] 不正な座標(NaN/Inf)の頂点が {non_finite} 個あります"))

            negative, non_uniform = utils.has_non_uniform_or_negative_scale(obj)
            if negative:
                any_issue = True
                lines.append(('WARNING', f"[{obj.name}] スケールにマイナス値が含まれています"))
            if non_uniform:
                any_issue = True
                lines.append(('WARNING', f"[{obj.name}] スケールが不均一です(X/Y/Zが異なります)"))

            if utils.has_unapplied_rotation(obj):
                any_issue = True
                lines.append(('WARNING', f"[{obj.name}] 回転が適用されていません"))

            non_manifold = utils.count_non_manifold(obj)
            if non_manifold > 0:
                lines.append(('INFO', f"[{obj.name}] 非多様体(ノンマニフォールド)エッジが {non_manifold} 個あります"))

        for armature_obj in armature_objs:
            zero_weight = utils.find_zero_weight_bones(armature_obj, mesh_objs)
            if zero_weight:
                lines.append((
                    'INFO',
                    f"[{armature_obj.name}] どのメッシュからもウェイトが乗っていないボーン: {len(zero_weight)} 個 "
                    "(自動削除は行いません。PhysBone等の参照に注意して手動で確認してください)",
                ))

        if not any_issue:
            lines.append(('INFO', "重大な問題は検出されませんでした"))

        set_report_lines(props.report_lines, lines)
        self.report({'INFO'}, "診断が完了しました")
        return {'FINISHED'}


_classes = (OBJECT_OT_amt_diagnostics_run,)


def register():
    for cls in _classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
