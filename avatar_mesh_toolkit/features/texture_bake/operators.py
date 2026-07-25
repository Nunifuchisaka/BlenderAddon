import bpy

from ...core import uv_regions
from ...core.context_utils import reset_to_object_mode_with_active
from ...core.report import set_report_lines
from . import properties, utils


class OBJECT_OT_amt_texture_bake_refresh_rects(bpy.types.Operator):
    bl_idname = "object.amt_texture_bake_refresh_rects"
    bl_label = "解放領域を再読み込み"
    bl_description = "対象ボディメッシュに記録されている解放UV領域の一覧を読み込み直します"
    bl_options = {'REGISTER'}

    @classmethod
    def poll(cls, context):
        props = context.scene.amt_texture_bake
        return props.target_object is not None and props.target_object.type == 'MESH'

    def execute(self, context):
        props = context.scene.amt_texture_bake
        properties.refresh_available_rects(props)
        self.report({'INFO'}, f"{len(props.available_rects)} 件の解放領域を読み込みました")
        return {'FINISHED'}


class OBJECT_OT_amt_texture_bake_run(bpy.types.Operator):
    bl_idname = "object.amt_texture_bake_run"
    bl_label = "ベイクを実行"
    bl_description = "選択した解放UV領域に、ベイク元メッシュの外観を焼き込みます"
    bl_options = {'REGISTER', 'UNDO'}

    _PASS_CONFIG = (
        ('bake_diffuse', 'DIFFUSE', 'target_image_diffuse', "Diffuse"),
        ('bake_normal', 'NORMAL', 'target_image_normal', "Normal"),
        ('bake_roughness', 'ROUGHNESS', 'target_image_roughness', "Roughness"),
        ('bake_emit', 'EMIT', 'target_image_emit', "Emit"),
    )

    @classmethod
    def poll(cls, context):
        props = context.scene.amt_texture_bake
        if props.target_object is None or props.target_object.type != 'MESH':
            return False
        if props.source_object is None or props.source_object.type != 'MESH':
            return False
        if not (0 <= props.selected_rect_index < len(props.available_rects)):
            return False
        return any(getattr(props, flag) for flag, *_ in cls._PASS_CONFIG)

    def invoke(self, context, event):
        props = context.scene.amt_texture_bake
        if not props.use_new_image_copy:
            return context.window_manager.invoke_props_dialog(self, width=420)
        return self.execute(context)

    def draw(self, context):
        col = self.layout.column(align=True)
        col.label(text="元の画像を直接書き換えます。", icon='ERROR')
        col.label(text="ファイルへの保存は別途、画像エディタから行ってください。")
        col.label(text="作業前にファイルを保存することを推奨します。")

    def execute(self, context):
        props = context.scene.amt_texture_bake
        rect_item = props.available_rects[props.selected_rect_index]
        dst_rect = (rect_item.min_u, rect_item.min_v, rect_item.max_u, rect_item.max_v)

        active_passes = [
            (flag, bake_type, image_attr, label)
            for flag, bake_type, image_attr, label in self._PASS_CONFIG
            if getattr(props, flag)
        ]

        prev_selected = list(context.selected_objects)
        prev_active = context.view_layer.objects.active

        reset_to_object_mode_with_active(context, props.source_object)
        try:
            proxy_obj, proxy_material, original_uv_layer_name = utils.duplicate_source_for_bake(
                context, props.source_object, props.source_material_index,
            )
        except ValueError as exc:
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}

        lines = []
        succeeded_all = True
        try:
            src_bbox = utils.compute_uv_bbox(proxy_obj.data, original_uv_layer_name)
            remap_layer = proxy_obj.data.uv_layers.new(name="AMT_BakeTarget")
            utils.remap_uv_layer(proxy_obj.data, remap_layer.name, src_bbox, dst_rect, props.fit_mode)
            utils.ensure_uv_map_node_for_shading(proxy_material, original_uv_layer_name)

            for flag, bake_type, image_attr, label in active_passes:
                source_image = getattr(props, image_attr)
                if source_image is None:
                    lines.append(('WARNING', f"{label}: ベイク先画像が指定されていないためスキップしました"))
                    succeeded_all = False
                    continue

                target_image = source_image
                if props.use_new_image_copy:
                    target_image = source_image.copy()
                    target_image.name = f"{source_image.name}_AMT_{bake_type.lower()}"

                utils.add_bake_target_node(proxy_material, target_image)
                try:
                    utils.run_self_bake(
                        context, proxy_obj, remap_layer.name, bake_type,
                        margin_px=props.margin_px, samples=props.samples,
                    )
                except RuntimeError as exc:
                    lines.append(('ERROR', f"{label}: {exc}"))
                    succeeded_all = False
                    continue

                if not target_image.packed_file:
                    target_image.pack()

                if props.use_new_image_copy:
                    lines.append(('INFO', f"{label}: 新規画像 '{target_image.name}' にベイクしました"))
                else:
                    lines.append(('INFO', f"{label}: '{target_image.name}' に直接ベイクしました"))
        finally:
            utils.cleanup_proxy(proxy_obj)
            for obj in context.selected_objects:
                obj.select_set(False)
            for obj in prev_selected:
                obj.select_set(True)
            context.view_layer.objects.active = prev_active

        if not lines:
            lines.append(('WARNING', "実行するベイクパスがありませんでした"))

        if succeeded_all and active_passes and props.consume_rect_after_bake:
            uv_regions.remove_freed_rect(props.target_object.data, props.selected_rect_index)
            properties.refresh_available_rects(props)
            lines.append(('INFO', "解放領域の記録を更新しました"))

        set_report_lines(props.report_lines, lines)
        self.report({'INFO'}, "ベイクが完了しました")
        return {'FINISHED'}


_classes = (OBJECT_OT_amt_texture_bake_refresh_rects, OBJECT_OT_amt_texture_bake_run)


def register():
    for cls in _classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
