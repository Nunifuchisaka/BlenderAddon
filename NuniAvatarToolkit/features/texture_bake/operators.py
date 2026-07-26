import bpy
import numpy as np

from ...core import uv_regions
from ...core.context_utils import reset_to_object_mode_with_active
from ...core.report import set_report_lines
from . import properties, utils


class OBJECT_OT_amt_texture_bake_refresh_rects(bpy.types.Operator):
    bl_idname = "object.amt_texture_bake_refresh_rects"
    bl_label = "解放領域を再読み込み"
    bl_description = "対象メッシュに記録されている解放UV領域の一覧を読み込み直します"
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


class OBJECT_OT_amt_texture_bake_preview_uv(bpy.types.Operator):
    bl_idname = "object.amt_texture_bake_preview_uv"
    bl_label = "UVプレビュー"
    bl_description = "UV Editingワークスペースで、対象メッシュのテクスチャと解放UV領域を確認します"
    bl_options = {'INTERNAL'}

    _IMAGE_NAME = "AMT_UVPreview"
    _SIZE = 512

    @classmethod
    def poll(cls, context):
        props = context.scene.amt_texture_bake
        return (
            props.target_object is not None
            and props.target_object.type == 'MESH'
            and len(props.available_rects) > 0
        )

    def invoke(self, context, event):
        self._create_preview_image(context.scene.amt_texture_bake)
        return self._show_uv_editing_workspace(context)

    def execute(self, context):
        self._create_preview_image(context.scene.amt_texture_bake)
        return self._show_uv_editing_workspace(context)

    def _show_uv_editing_workspace(self, context):
        """Open the preview in Blender's standard UV Editing workspace."""
        workspace = bpy.data.workspaces.get("UV Editing")
        if workspace is None:
            self.report({'ERROR'}, "'UV Editing'ワークスペースが見つかりません")
            return {'CANCELLED'}

        workspace_screen = workspace.screens[0] if workspace.screens else None
        if workspace_screen is None:
            self.report({'ERROR'}, "UV Editingワークスペースに画面がありません")
            return {'CANCELLED'}
        image_editor = next(
            (area for area in workspace_screen.areas if area.type == 'IMAGE_EDITOR'),
            None,
        )
        if image_editor is None:
            self.report({'ERROR'}, "UV Editingワークスペースに画像エディターがありません")
            return {'CANCELLED'}
        image_editor.spaces.active.image = bpy.data.images.get(self._IMAGE_NAME)
        context.window.workspace = workspace
        source_image = self._get_source_material_image(context.scene.amt_texture_bake)
        source_area = next(
            (area for area in workspace_screen.areas if area.type == 'VIEW_3D'),
            None,
        )
        if source_image is not None and source_area is not None:
            source_area.type = 'IMAGE_EDITOR'
            self._set_image_editor_image(source_area, source_image)
        self.report({'INFO'}, "UV Editingで対象画像とベイク元画像のプレビューを開きました")
        return {'FINISHED'}

    @staticmethod
    def _set_image_editor_image(area, image):
        """Set an image after Blender finishes changing the area's editor type."""
        def set_image():
            if area.type != 'IMAGE_EDITOR':
                return 0.1
            image_editor = area.spaces.active
            if image_editor.type != 'IMAGE_EDITOR':
                return 0.1
            image_editor.image = image
            return None

        bpy.app.timers.register(set_image, first_interval=0.0)

    @staticmethod
    def _create_preview_image(props):
        size = OBJECT_OT_amt_texture_bake_preview_uv._SIZE
        pixels = np.zeros((size, size, 4), dtype=np.float32)
        pixels[:, :, :3] = 0.08
        pixels[:, :, 3] = 1.0
        OBJECT_OT_amt_texture_bake_preview_uv._draw_target_texture(pixels, props)

        # 0-1 のUVタイルを、背景グリッドと解放領域の枠で表示する。
        for index in range(11):
            pos = round(index * (size - 1) / 10)
            pixels[pos:pos + 1, :, :3] = pixels[pos:pos + 1, :, :3] * 0.7 + 0.3
            pixels[:, pos:pos + 1, :3] = pixels[:, pos:pos + 1, :3] * 0.7 + 0.3

        selected_index = props.selected_rect_index
        for index, rect in enumerate(props.available_rects):
            color = (1.0, 0.36, 0.04) if index == selected_index else (0.08, 0.5, 1.0)
            OBJECT_OT_amt_texture_bake_preview_uv._draw_rect(
                pixels, rect, color, selected=index == selected_index,
            )

        OBJECT_OT_amt_texture_bake_preview_uv._draw_source_uv(pixels, props)

        image = bpy.data.images.get(OBJECT_OT_amt_texture_bake_preview_uv._IMAGE_NAME)
        if image is None or image.size[0] != size or image.size[1] != size:
            if image is not None:
                bpy.data.images.remove(image)
            image = bpy.data.images.new(
                OBJECT_OT_amt_texture_bake_preview_uv._IMAGE_NAME,
                width=size,
                height=size,
                alpha=True,
            )
        image.pixels.foreach_set(pixels.reshape(-1))
        image.update()

    @staticmethod
    def _draw_target_texture(pixels, props):
        """Use the selected bake destination as the preview background when available."""
        source_image = OBJECT_OT_amt_texture_bake_preview_uv._get_preview_source_image(props)
        if source_image is None:
            return
        temporary_image = None
        try:
            temporary_image = source_image.copy()
            temporary_image.scale(
                OBJECT_OT_amt_texture_bake_preview_uv._SIZE,
                OBJECT_OT_amt_texture_bake_preview_uv._SIZE,
            )
            texture_pixels = np.empty(
                OBJECT_OT_amt_texture_bake_preview_uv._SIZE ** 2 * 4,
                dtype=np.float32,
            )
            temporary_image.pixels.foreach_get(texture_pixels)
            pixels[:, :, :] = texture_pixels.reshape((
                OBJECT_OT_amt_texture_bake_preview_uv._SIZE,
                OBJECT_OT_amt_texture_bake_preview_uv._SIZE,
                4,
            ))
            pixels[:, :, 3] = 1.0
        except (RuntimeError, ValueError):
            # An unloaded or unsupported image must not prevent UV placement preview.
            return
        finally:
            if temporary_image is not None and temporary_image.users == 0:
                bpy.data.images.remove(temporary_image)

    @staticmethod
    def _get_preview_source_image(props):
        if not (0 <= props.selected_rect_index < len(props.available_rects)):
            return None
        rect = props.available_rects[props.selected_rect_index]
        for enabled, bake_type in (
            (props.bake_diffuse, 'DIFFUSE'),
            (props.bake_normal, 'NORMAL'),
            (props.bake_roughness, 'ROUGHNESS'),
            (props.bake_emit, 'EMIT'),
        ):
            if not enabled:
                continue
            try:
                return utils.get_target_material_image(
                    props.target_object, rect.material_index, bake_type,
                )
            except ValueError:
                continue
        return None

    @staticmethod
    def _get_source_material_image(props):
        """Return the source material texture for the second UV Editing pane."""
        if props.source_object is None or props.source_object.type != 'MESH':
            return None
        try:
            return utils.get_target_material_image(
                props.source_object, props.source_material_index, 'DIFFUSE',
            )
        except ValueError:
            return None

    @staticmethod
    def _draw_source_uv(pixels, props):
        """Overlay the source material's UV edges after the same transform used for baking."""
        source = props.source_object
        if source is None or source.type != 'MESH' or source.data.uv_layers.active is None:
            return
        if not (0 <= props.source_material_index < len(source.material_slots)):
            return
        if not (0 <= props.selected_rect_index < len(props.available_rects)):
            return

        uv_layer = source.data.uv_layers.active
        polygons = [
            polygon for polygon in source.data.polygons
            if polygon.material_index == props.source_material_index
        ]
        if not polygons:
            return
        coordinates = [uv_layer.data[loop_index].uv[:] for polygon in polygons for loop_index in polygon.loop_indices]
        min_u = min(uv[0] for uv in coordinates)
        min_v = min(uv[1] for uv in coordinates)
        max_u = max(uv[0] for uv in coordinates)
        max_v = max(uv[1] for uv in coordinates)
        rect = props.available_rects[props.selected_rect_index]
        transform = OBJECT_OT_amt_texture_bake_preview_uv._source_uv_transform(
            (min_u, min_v, max_u, max_v),
            (rect.min_u, rect.min_v, rect.max_u, rect.max_v),
            props.fit_mode,
            (props.source_uv_offset_u, props.source_uv_offset_v),
            (props.source_uv_scale, props.source_uv_scale),
        )
        for polygon in polygons:
            polygon_uvs = [transform(uv_layer.data[loop_index].uv) for loop_index in polygon.loop_indices]
            for start, end in zip(polygon_uvs, polygon_uvs[1:] + polygon_uvs[:1]):
                OBJECT_OT_amt_texture_bake_preview_uv._draw_line(
                    pixels, start, end, (1.0, 1.0, 1.0),
                )

    @staticmethod
    def _source_uv_transform(src_bbox, dst_rect, fit_mode, manual_offset, manual_scale):
        src_min_u, src_min_v, src_max_u, src_max_v = src_bbox
        dst_min_u, dst_min_v, dst_max_u, dst_max_v = dst_rect
        src_width = max(src_max_u - src_min_u, 1e-9)
        src_height = max(src_max_v - src_min_v, 1e-9)
        dst_width = max(dst_max_u - dst_min_u, 1e-9)
        dst_height = max(dst_max_v - dst_min_v, 1e-9)
        if fit_mode == 'UNIFORM':
            scale_u = scale_v = min(dst_width / src_width, dst_height / src_height)
        else:
            scale_u = dst_width / src_width
            scale_v = dst_height / src_height
        offset_u = dst_min_u + (dst_width - src_width * scale_u) * 0.5
        offset_v = dst_min_v + (dst_height - src_height * scale_v) * 0.5
        center_u = (dst_min_u + dst_max_u) * 0.5
        center_v = (dst_min_v + dst_max_v) * 0.5

        def transform(uv):
            u = (uv[0] - src_min_u) * scale_u + offset_u
            v = (uv[1] - src_min_v) * scale_v + offset_v
            return (
                (u - center_u) * manual_scale[0] + center_u + manual_offset[0],
                (v - center_v) * manual_scale[1] + center_v + manual_offset[1],
            )

        return transform

    @staticmethod
    def _draw_line(pixels, start, end, color):
        size = OBJECT_OT_amt_texture_bake_preview_uv._SIZE
        start_x = round(start[0] * (size - 1))
        start_y = round(start[1] * (size - 1))
        end_x = round(end[0] * (size - 1))
        end_y = round(end[1] * (size - 1))
        steps = max(abs(end_x - start_x), abs(end_y - start_y), 1)
        for step in range(steps + 1):
            x = round(start_x + (end_x - start_x) * step / steps)
            y = round(start_y + (end_y - start_y) * step / steps)
            if 0 <= x < size and 0 <= y < size:
                pixels[y, x, :3] = color

    @staticmethod
    def _draw_rect(pixels, rect, color, selected):
        size = OBJECT_OT_amt_texture_bake_preview_uv._SIZE
        if rect.max_u < 0.0 or rect.min_u > 1.0 or rect.max_v < 0.0 or rect.min_v > 1.0:
            return
        min_x = max(0, min(size - 1, round(rect.min_u * (size - 1))))
        max_x = max(0, min(size - 1, round(rect.max_u * (size - 1))))
        min_y = max(0, min(size - 1, round(rect.min_v * (size - 1))))
        max_y = max(0, min(size - 1, round(rect.max_v * (size - 1))))
        if min_x > max_x or min_y > max_y:
            return

        fill_alpha = 0.35 if selected else 0.18
        pixels[min_y:max_y + 1, min_x:max_x + 1, :3] = (
            pixels[min_y:max_y + 1, min_x:max_x + 1, :3] * (1.0 - fill_alpha)
            + np.asarray(color) * fill_alpha
        )
        line_width = 3 if selected else 2
        pixels[min_y:min_y + line_width, min_x:max_x + 1, :3] = color
        pixels[max_y - line_width + 1:max_y + 1, min_x:max_x + 1, :3] = color
        pixels[min_y:max_y + 1, min_x:min_x + line_width, :3] = color
        pixels[min_y:max_y + 1, max_x - line_width + 1:max_x + 1, :3] = color


class OBJECT_OT_amt_texture_bake_run(bpy.types.Operator):
    bl_idname = "object.amt_texture_bake_run"
    bl_label = "ベイクを実行"
    bl_description = "選択した解放UV領域に、ベイク元メッシュの外観を焼き込みます"
    bl_options = {'REGISTER', 'UNDO'}

    _PASS_CONFIG = (
        ('bake_diffuse', 'DIFFUSE', "Diffuse"),
        ('bake_normal', 'NORMAL', "Normal"),
        ('bake_roughness', 'ROUGHNESS', "Roughness"),
        ('bake_emit', 'EMIT', "Emit"),
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
        return self.execute(context)

    def execute(self, context):
        props = context.scene.amt_texture_bake
        rect_item = props.available_rects[props.selected_rect_index]
        dst_rect = (rect_item.min_u, rect_item.min_v, rect_item.max_u, rect_item.max_v)

        active_passes = [
            (flag, bake_type, label)
            for flag, bake_type, label in self._PASS_CONFIG
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
        backups = {}
        try:
            src_bbox = utils.compute_uv_bbox(proxy_obj.data, original_uv_layer_name)
            remap_layer = proxy_obj.data.uv_layers.new(name="AMT_BakeTarget")
            utils.remap_uv_layer(
                proxy_obj.data,
                remap_layer.name,
                src_bbox,
                dst_rect,
                props.fit_mode,
                manual_offset=(props.source_uv_offset_u, props.source_uv_offset_v),
                manual_scale=(props.source_uv_scale, props.source_uv_scale),
            )
            utils.ensure_uv_map_node_for_shading(proxy_material, original_uv_layer_name)

            for _, bake_type, label in active_passes:
                try:
                    target_image = utils.get_target_material_image(
                        props.target_object, rect_item.material_index, bake_type,
                    )
                except ValueError as exc:
                    lines.append(('ERROR', f"{label}: {exc}"))
                    succeeded_all = False
                    continue

                if target_image not in backups:
                    try:
                        backups[target_image] = utils.create_image_backup(target_image)
                    except ValueError as exc:
                        lines.append(('ERROR', str(exc)))
                        succeeded_all = False
                        continue

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
                lines.append((
                    'INFO',
                    f"{label}: '{target_image.name}' にベイクしました "
                    f"(バックアップ: '{backups[target_image].name}')",
                ))
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


_classes = (
    OBJECT_OT_amt_texture_bake_refresh_rects,
    OBJECT_OT_amt_texture_bake_preview_uv,
    OBJECT_OT_amt_texture_bake_run,
)


def register():
    for cls in _classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
