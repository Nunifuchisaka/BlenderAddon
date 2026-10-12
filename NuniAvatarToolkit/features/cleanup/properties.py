import bpy

from ...core.object_polls import mesh_object_poll
from ...core.report import AMT_ReportLine


class AMT_CleanupProperties(bpy.types.PropertyGroup):
    target_object: bpy.props.PointerProperty(
        type=bpy.types.Object,
        name="対象メッシュ",
        description="不要データを削除する対象のメッシュオブジェクトを指定してください",
        poll=mesh_object_poll,
    )
    remove_empty_vertex_groups: bpy.props.BoolProperty(
        name="空の頂点グループ",
        description="どの頂点にもウェイトが乗っておらず、モディファイアやシェイプキーからも参照されていない頂点グループを削除します",
        default=True,
    )
    remove_noop_shape_keys: bpy.props.BoolProperty(
        name="無効なシェイプキー",
        description="ベース(Basis)からの頂点移動量が「無効判定のしきい値」未満のシェイプキーを削除します",
        default=True,
    )
    shape_key_noop_threshold: bpy.props.FloatProperty(
        name="無効判定のしきい値",
        description="ベースからの最大頂点移動量(メートル)がこの値未満の場合、実質的に無効なシェイプキーとみなします",
        default=1e-5, min=1e-8, max=1e-2, precision=8,
    )
    remove_unused_uv_maps: bpy.props.BoolProperty(
        name="未使用のUVマップ",
        description="マテリアルのUVマップノードから参照されておらず、アクティブUVマップでもないUVマップを削除します",
        default=True,
    )
    remove_unused_vertex_colors: bpy.props.BoolProperty(
        name="未使用の頂点カラー",
        description="マテリアルのカラーアトリビュートノードから参照されていない頂点カラーレイヤーを削除します",
        default=True,
    )
    remove_unused_material_slots: bpy.props.BoolProperty(
        name="未使用のマテリアルスロット",
        description="どの面にも割り当てられていないマテリアルスロットを削除します",
        default=True,
    )
    remove_loose_geometry: bpy.props.BoolProperty(
        name="浮遊頂点/エッジ",
        description="どの面にも属していない孤立した頂点・辺を削除します",
        default=True,
    )
    report_lines: bpy.props.CollectionProperty(type=AMT_ReportLine)
    report_active_index: bpy.props.IntProperty()


_classes = (AMT_CleanupProperties,)


def register():
    for cls in _classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.amt_cleanup = bpy.props.PointerProperty(type=AMT_CleanupProperties)


def unregister():
    del bpy.types.Scene.amt_cleanup
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
