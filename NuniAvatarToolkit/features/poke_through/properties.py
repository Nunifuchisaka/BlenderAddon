import bpy

from ...core.report import AMT_ReportLine


def _mesh_object_poll(self, obj):
    return obj.type == 'MESH'


class AMT_PokeThroughClothingItem(bpy.types.PropertyGroup):
    object: bpy.props.PointerProperty(
        type=bpy.types.Object,
        name="服メッシュ",
        description="体を覆っている服メッシュを指定してください",
        poll=_mesh_object_poll,
    )


class AMT_PokeThroughProperties(bpy.types.PropertyGroup):
    body_object: bpy.props.PointerProperty(
        type=bpy.types.Object,
        name="ボディメッシュ",
        description="服から突き出ていないかを調べたいアバターの体メッシュを指定してください",
        poll=_mesh_object_poll,
    )
    clothing_objects: bpy.props.CollectionProperty(
        type=AMT_PokeThroughClothingItem,
        name="服メッシュ",
        description="体を覆っている服メッシュの一覧です",
    )
    clothing_objects_index: bpy.props.IntProperty(
        name="選択中の服メッシュ",
        default=0,
        min=0,
    )
    max_search_distance: bpy.props.FloatProperty(
        name="最大探索距離",
        description=(
            "服の表面からこの距離までを「服に覆われている範囲」とみなします。"
            "これより遠くに服が無い頂点は、そもそも服で覆われていない部分(手・頭・足など)として判定から除外します。"
            "襟ぐりや袖口の肌が誤検出される場合は小さくしてください"
        ),
        default=0.01, min=0.0001, precision=4, unit='LENGTH',
    )
    protrusion_threshold: bpy.props.FloatProperty(
        name="検出しきい値",
        description=(
            "服の表面より外側へこの距離を超えて出ている頂点を貫通として扱います。"
            "面がぴったり接している状態を貫通と誤検出しないための余裕です"
        ),
        default=0.0002, min=0.0, precision=5, unit='LENGTH',
    )
    face_select_mode: bpy.props.EnumProperty(
        name="判定モード",
        description="面を貫通として扱う条件を指定します",
        items=[
            ('ANY', "いずれかの頂点が出ている面",
             "面を構成する頂点のいずれかが服の外に出ていれば選択します(推奨)。見落としが少なく、検査向きです"),
            ('ALL', "全頂点が出ている面のみ",
             "面を構成する全ての頂点が服の外に出ている場合のみ選択します。深く突き抜けている箇所だけに絞れます"),
        ],
        default='ANY',
    )
    exclude_vertex_group: bpy.props.StringProperty(
        name="除外頂点グループ",
        description=(
            "指定した頂点グループにウェイトが乗っている頂点は、判定結果に関わらず常に検出対象から除外されます。"
            "顔・手・足など、そもそも服から出ているのが正しい部位の保護に使用してください"
        ),
        default="",
    )
    report_lines: bpy.props.CollectionProperty(type=AMT_ReportLine)
    report_active_index: bpy.props.IntProperty()


_classes = (AMT_PokeThroughClothingItem, AMT_PokeThroughProperties)


def register():
    for cls in _classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.amt_poke_through = bpy.props.PointerProperty(type=AMT_PokeThroughProperties)


def unregister():
    del bpy.types.Scene.amt_poke_through
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
