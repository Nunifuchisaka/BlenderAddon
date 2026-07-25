import bpy

from ...core import uv_regions
from ...core.report import AMT_ReportLine


def _mesh_object_poll(self, obj):
    return obj.type == 'MESH'


def refresh_available_rects(props):
    """Rebuilds props.available_rects from the freed-UV-rect records stored on
    props.target_object's mesh. Called both by the target_object update callback and by the
    "refresh" operator (e.g. after running hidden-mesh deletion again on the same object)."""
    props.available_rects.clear()
    props.selected_rect_index = 0
    if props.target_object is None or props.target_object.type != 'MESH':
        return
    for rect in uv_regions.get_freed_rects(props.target_object.data):
        item = props.available_rects.add()
        item.material_index = int(rect.get('material_index', -1))
        mat = None
        if 0 <= item.material_index < len(props.target_object.material_slots):
            mat = props.target_object.material_slots[item.material_index].material
        item.material_name = mat.name if mat else "(マテリアルなし)"
        item.uv_layer = str(rect.get('uv_layer', ""))
        item.min_u = float(rect.get('min_u', 0.0))
        item.min_v = float(rect.get('min_v', 0.0))
        item.max_u = float(rect.get('max_u', 0.0))
        item.max_v = float(rect.get('max_v', 0.0))
        item.face_count = int(rect.get('face_count', 0))
        item.source_object = str(rect.get('source_object', ""))


def _on_target_object_update(self, context):
    refresh_available_rects(self)


class AMT_FreedUVRectItem(bpy.types.PropertyGroup):
    material_index: bpy.props.IntProperty()
    material_name: bpy.props.StringProperty()
    uv_layer: bpy.props.StringProperty()
    min_u: bpy.props.FloatProperty()
    min_v: bpy.props.FloatProperty()
    max_u: bpy.props.FloatProperty()
    max_v: bpy.props.FloatProperty()
    face_count: bpy.props.IntProperty()
    source_object: bpy.props.StringProperty()


class AMT_UL_freed_uv_rects(bpy.types.UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        row = layout.row(align=True)
        row.label(text=item.material_name, icon='MATERIAL')
        width = item.max_u - item.min_u
        height = item.max_v - item.min_v
        row.label(text=f"{width:.2f} x {height:.2f} UV / {item.face_count}面")


class AMT_TextureBakeProperties(bpy.types.PropertyGroup):
    target_object: bpy.props.PointerProperty(
        type=bpy.types.Object,
        name="対象ボディメッシュ",
        description="隠れメッシュ削除で解放されたUV領域を持つメッシュを指定してください",
        poll=_mesh_object_poll,
        update=_on_target_object_update,
    )
    available_rects: bpy.props.CollectionProperty(type=AMT_FreedUVRectItem)
    selected_rect_index: bpy.props.IntProperty()

    source_object: bpy.props.PointerProperty(
        type=bpy.types.Object,
        name="ベイク元メッシュ",
        description=(
            "外観をベイクして再利用したいメッシュを指定してください"
            "(服に限らず、シーン内の任意のメッシュオブジェクトを選択できます)"
        ),
        poll=_mesh_object_poll,
    )
    source_material_index: bpy.props.IntProperty(
        name="ベイク元マテリアルスロット",
        description="ベイク元メッシュの中で、どのマテリアルスロットの外観を焼き込むかを指定します",
        default=0, min=0,
    )

    bake_diffuse: bpy.props.BoolProperty(name="Diffuse(拡散色)", default=True)
    bake_normal: bpy.props.BoolProperty(name="Normal(法線)", default=False)
    bake_roughness: bpy.props.BoolProperty(name="Roughness(粗さ)", default=False)
    bake_emit: bpy.props.BoolProperty(name="Emit(発光)", default=False)

    target_image_diffuse: bpy.props.PointerProperty(type=bpy.types.Image, name="Diffuseベイク先画像")
    target_image_normal: bpy.props.PointerProperty(type=bpy.types.Image, name="Normalベイク先画像")
    target_image_roughness: bpy.props.PointerProperty(type=bpy.types.Image, name="Roughnessベイク先画像")
    target_image_emit: bpy.props.PointerProperty(type=bpy.types.Image, name="Emitベイク先画像")

    fit_mode: bpy.props.EnumProperty(
        name="フィット方式",
        description="ベイク元メッシュのUV全体を解放矩形に合わせる方法を指定します",
        items=[
            ('UNIFORM', "アスペクト比を維持", "縦横比を保ったまま矩形内に収めます(余白が生じる場合があります)"),
            ('STRETCH', "矩形に合わせて伸縮", "矩形いっぱいに引き伸ばします(縦横比が変わり歪む場合があります)"),
        ],
        default='UNIFORM',
    )
    margin_px: bpy.props.IntProperty(name="マージン(px)", default=16, min=0, max=64)
    samples: bpy.props.IntProperty(name="サンプル数", default=32, min=1, max=512)
    use_new_image_copy: bpy.props.BoolProperty(
        name="新規コピー画像にベイク",
        description="元の画像を直接書き換えず、複製した新しい画像にベイクします(推奨)。オフにすると元の画像を直接上書きします",
        default=True,
    )
    consume_rect_after_bake: bpy.props.BoolProperty(
        name="ベイク後に解放領域を消費済みにする",
        description="有効にしたベイクが全て成功した場合、選択した解放領域を記録から削除します",
        default=True,
    )

    report_lines: bpy.props.CollectionProperty(type=AMT_ReportLine)
    report_active_index: bpy.props.IntProperty()


_classes = (AMT_FreedUVRectItem, AMT_UL_freed_uv_rects, AMT_TextureBakeProperties)


def register():
    for cls in _classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.amt_texture_bake = bpy.props.PointerProperty(type=AMT_TextureBakeProperties)


def unregister():
    del bpy.types.Scene.amt_texture_bake
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
