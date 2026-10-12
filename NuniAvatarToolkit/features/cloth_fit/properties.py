import bpy

from ...core.object_polls import mesh_object_poll
from ...core.report import AMT_ReportLine


class AMT_ClothFitProperties(bpy.types.PropertyGroup):
    body_object: bpy.props.PointerProperty(
        type=bpy.types.Object,
        name="ボディメッシュ",
        description="服を合わせる先となる体のメッシュオブジェクトを指定してください",
        poll=mesh_object_poll,
    )
    clothing_object: bpy.props.PointerProperty(
        type=bpy.types.Object,
        name="服メッシュ",
        description="体の形状に合わせて変形させる服のメッシュオブジェクトを指定してください",
        poll=mesh_object_poll,
    )
    vertex_group: bpy.props.StringProperty(
        name="対象頂点グループ",
        description=(
            "この頂点グループに含まれる頂点だけをフィットさせます。"
            "ウェイト値がそのままフィットの強さになるため、境界のウェイトを0へ向けてぼかすと段差が出ません"
        ),
        default="",
    )
    offset: bpy.props.FloatProperty(
        name="オフセット",
        description="体表面から法線方向へこの距離だけ浮かせます。服の厚み分を確保して再貫通を防ぎます",
        default=0.001, min=0.0, max=0.05, precision=4, unit='LENGTH',
    )
    max_search_distance: bpy.props.FloatProperty(
        name="最大探索距離",
        description=(
            "頂点から体表面までがこの距離以内の場合だけフィットさせます。"
            "離れた体のパーツへ誤って吸着するのを防ぎます。深く埋まった頂点が動かない場合は大きくするか、0(距離制限なし)にしてください"
        ),
        default=0.1, min=0.0, precision=4, unit='LENGTH',
    )
    shape_key_name: bpy.props.StringProperty(
        name="シェイプキー名",
        description="フィット結果を書き込むシェイプキーの名前です。同じ名前のシェイプキーがある場合は上書きします",
        default="AMT_Fit",
    )
    report_lines: bpy.props.CollectionProperty(type=AMT_ReportLine)
    report_active_index: bpy.props.IntProperty()


_classes = (AMT_ClothFitProperties,)


def register():
    for cls in _classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.amt_cloth_fit = bpy.props.PointerProperty(type=AMT_ClothFitProperties)


def unregister():
    del bpy.types.Scene.amt_cloth_fit
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
