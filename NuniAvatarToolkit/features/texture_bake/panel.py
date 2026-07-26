import bpy

from ...core.ui import TOOLKIT_CATEGORY


class VIEW3D_PT_amt_texture_bake(bpy.types.Panel):
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = TOOLKIT_CATEGORY
    bl_label = "テクスチャベイク(UV領域再利用)"
    bl_order = 1
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        layout = self.layout
        props = context.scene.amt_texture_bake

        layout.prop(props, "target_object")

        if props.target_object is None:
            return

        row = layout.row(align=True)
        if len(props.available_rects) == 0:
            row.label(text="記録された解放UV領域がありません", icon='INFO')
        else:
            row.template_list(
                "AMT_UL_freed_uv_rects", "",
                props, "available_rects",
                props, "selected_rect_index",
                rows=3,
            )
        row.operator("object.amt_texture_bake_refresh_rects", text="", icon='FILE_REFRESH')
        if len(props.available_rects) > 0:
            layout.operator("object.amt_texture_bake_preview_uv", text="UVプレビューを開く", icon='UV')

        layout.separator()
        col = layout.column(align=True)
        col.prop(props, "source_object")
        col.prop(props, "source_material_index")

        layout.separator()
        col = layout.column(align=True)
        col.label(text="ベイクするパス:")
        row = col.row(align=True)
        row.prop(props, "bake_diffuse", toggle=True)
        row.prop(props, "bake_normal", toggle=True)
        row.prop(props, "bake_roughness", toggle=True)
        row.prop(props, "bake_emit", toggle=True)

        col.label(text="ベイク先画像は対象メッシュのマテリアルから取得します", icon='INFO')

        layout.separator()
        col = layout.column(align=True)
        col.prop(props, "fit_mode")
        col.label(text="統合元UVの調整:")
        row = col.row(align=True)
        row.prop(props, "source_uv_offset_u")
        row.prop(props, "source_uv_offset_v")
        col.prop(props, "source_uv_scale")
        col.label(text="調整値は表示中のUVプレビューへすぐ反映されます", icon='INFO')
        col.prop(props, "margin_px")
        col.prop(props, "samples")

        layout.separator()
        col = layout.column(align=True)
        col.label(text="ベイク前に元画像のバックアップを自動作成します", icon='FILE_BACKUP')
        col.prop(props, "consume_rect_after_bake")

        layout.separator()
        layout.operator("object.amt_texture_bake_run", icon='RENDER_STILL')

        if len(props.report_lines) > 0:
            layout.separator()
            layout.template_list(
                "AMT_UL_report_lines", "",
                props, "report_lines",
                props, "report_active_index",
                rows=4,
            )


_classes = (VIEW3D_PT_amt_texture_bake,)


def register():
    for cls in _classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
