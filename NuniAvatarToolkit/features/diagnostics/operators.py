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

        # Evaluation uses this scene's depsgraph, so a collection from another scene would be misread.
        scene_collection = context.scene.collection
        if collection != scene_collection and collection not in scene_collection.children_recursive:
            message = f"コレクション「{collection.name}」が現在のシーンにありません。対象のシーンで実行してください"
            set_report_lines(props.report_lines, [('ERROR', message)])
            self.report({'ERROR'}, message)
            return {'CANCELLED'}

        mesh_objs = utils.get_avatar_mesh_objects(collection)
        armature_objs = utils.get_avatar_armature_objects(collection)

        if not mesh_objs:
            set_report_lines(props.report_lines, [('WARNING', "コレクション内にメッシュオブジェクトが見つかりません")])
            return {'CANCELLED'}

        # Unsaved Edit Mode changes live only in the edit mesh; flush them so obj.data is current.
        for obj in mesh_objs:
            if obj.mode == 'EDIT':
                obj.update_from_editmode()
        depsgraph = context.evaluated_depsgraph_get()

        lines = []
        any_issue = False

        tris = utils.count_triangles(mesh_objs, depsgraph)
        lines.append(('INFO', f"ポリゴン数(三角形換算): {tris:,} 【{utils.platform_ranks(tris, 'triangles')}】"))

        mats = utils.count_material_slots(mesh_objs)
        lines.append(('INFO', f"マテリアルスロット数: {mats:,} 【{utils.platform_ranks(mats, 'material_slots')}】"))

        bones = utils.count_bones(armature_objs)
        bone_rank = utils.platform_ranks(bones, 'bones') if armature_objs else "N/A"
        lines.append(('INFO', f"ボーン数: {bones:,} 【{bone_rank}】"))

        if len(armature_objs) == 0:
            any_issue = True
            lines.append(('WARNING', "アーマチュアオブジェクトが見つかりません"))
        elif len(armature_objs) >= 2:
            any_issue = True
            lines.append(('WARNING', f"アーマチュアオブジェクトが{len(armature_objs)}個あります(通常は1つを想定した機能です)"))

        shape_keys = utils.count_shape_keys(mesh_objs)
        lines.append(('INFO', f"シェイプキー数(Basis除く): {shape_keys}"))

        lines.append(('WARNING', "※上記の目安はVRChatの基準を参考にした概算値です。最新の正確な基準は公式ドキュメントで確認してください"))
        lines.append(('INFO', "--- 書き出し前チェック ---"))

        for obj in mesh_objs:
            non_finite = utils.find_non_finite_vertices(obj)
            if non_finite > 0:
                any_issue = True
                lines.append(('ERROR', f"[{obj.name}] 不正な座標(NaN/Inf)の頂点が {non_finite} 個あります"))
            for key_name, key_count in utils.find_non_finite_shape_keys(obj):
                any_issue = True
                lines.append(('ERROR', f"[{obj.name}] シェイプキー「{key_name}」に不正な座標(NaN/Inf)の頂点が {key_count} 個あります"))

            negative, non_uniform = utils.has_non_uniform_or_negative_scale(obj)
            if negative:
                any_issue = True
                lines.append(('WARNING', f"[{obj.name}] スケールにマイナス値が含まれています"))
            if non_uniform:
                any_issue = True
                lines.append(('WARNING', f"[{obj.name}] スケールが不均一です(X/Y/Zが異なります。デルタスケールを含む)"))

            if utils.has_unapplied_rotation(obj):
                any_issue = True
                lines.append(('WARNING', f"[{obj.name}] 回転が適用されていません(デルタ回転を含む)"))

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

        layer_collection_root = context.view_layer.layer_collection

        for obj in utils.find_uncategorized_mesh_objects(collection):
            any_issue = True
            lines.append((
                'WARNING',
                f"[{obj.name}] コレクション直下に直接配置されています(サブコレクションへの分類漏れの可能性があります)",
            ))

        for path, branch, reason in utils.find_excluded_or_hidden_branches(collection, layer_collection_root):
            any_issue = True
            lines.append((
                'WARNING',
                f"[{path}] {reason}のコレクションですが、中に{len(branch.all_objects)}個のオブジェクトがあります"
                "(書き出し対象から漏れる、または意図せず含まれる可能性があります)",
            ))

        for obj, paths in utils.find_duplicate_membership(collection).items():
            any_issue = True
            lines.append(('WARNING', f"[{obj.name}] 複数のコレクションに重複して所属しています: {', '.join(paths)}"))

        for path, _child in utils.find_default_named_collections(collection):
            lines.append(('INFO', f"[{path}] コレクション名が初期値のままです(分類名の付け忘れの可能性があります)"))

        for path, _child in utils.find_empty_collections(collection):
            lines.append(('INFO', f"[{path}] 空のコレクションです(中身がありません)"))

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
