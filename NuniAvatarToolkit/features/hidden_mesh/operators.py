import time

import bmesh
import bpy

from . import api, utils


class OBJECT_OT_amt_add_clothing_object(bpy.types.Operator):
    bl_idname = "object.amt_add_clothing_object"
    bl_label = "服メッシュを追加"
    bl_description = "遮蔽物として扱う服メッシュの選択欄を追加します"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        props = context.scene.amt_hidden_mesh
        props.clothing_objects.add()
        props.clothing_objects_index = len(props.clothing_objects) - 1
        return {'FINISHED'}


class OBJECT_OT_amt_remove_clothing_object(bpy.types.Operator):
    bl_idname = "object.amt_remove_clothing_object"
    bl_label = "服メッシュを削除"
    bl_description = "選択中の服メッシュ欄を一覧から削除します"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return len(context.scene.amt_hidden_mesh.clothing_objects) > 0

    def execute(self, context):
        props = context.scene.amt_hidden_mesh
        index = min(props.clothing_objects_index, len(props.clothing_objects) - 1)
        props.clothing_objects.remove(index)
        props.clothing_objects_index = min(index, max(0, len(props.clothing_objects) - 1))
        return {'FINISHED'}


class OBJECT_OT_amt_select_hidden_faces(bpy.types.Operator):
    bl_idname = "object.amt_select_hidden_faces"
    bl_label = "隠れた面を選択"
    bl_description = (
        "服(および任意で体自身)に完全に覆われて外部から見えない体メッシュの面を検出し、"
        "編集モードで選択状態にします(削除は行いません)"
    )
    bl_options = {'REGISTER'}

    _timer = None
    _gen = None

    @classmethod
    def poll(cls, context):
        props = context.scene.amt_hidden_mesh
        if props.body_object is None or props.body_object.type != 'MESH':
            return False
        has_clothing = any(item.object is not None for item in props.clothing_objects)
        return has_clothing or props.include_body_self_occlusion

    def invoke(self, context, event):
        scene = context.scene
        props = scene.amt_hidden_mesh
        clothing_objs = [item.object for item in props.clothing_objects if item.object is not None]
        try:
            self._session = api.AnalysisSession(
                context,
                props.body_object,
                clothing_objs,
                ray_samples=props.ray_samples,
                ray_epsilon_ratio=props.ray_epsilon_ratio,
                face_select_mode=props.face_select_mode,
                safety_margin=props.safety_margin,
                include_body_self_occlusion=props.include_body_self_occlusion,
                self_occlusion_min_distance_ratio=props.self_occlusion_min_distance_ratio,
                exclude_vertex_group=props.exclude_vertex_group,
            )
        except api.HiddenMeshError as exc:
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}

        if not self._session.used_evaluated_mesh:
            self.report({'WARNING'}, "一部のモディファイア構成のため、変形前(レスト)座標で判定しました")

        if self._session.estimated_ray_count > utils.PERFORMANCE_WARNING_VERTEX_SAMPLES:
            self.report(
                {'WARNING'},
                f"頂点数×サンプル数が多いため処理に時間がかかる可能性があります"
                f"({self._session.total} x {props.ray_samples})",
            )

        self._gen = self._session
        self._total = self._session.total
        self._index = 0
        self._time_budget = 0.03

        wm = context.window_manager
        wm.progress_begin(0, self._total)
        self._progress_active = True
        self._timer = wm.event_timer_add(0.02, window=context.window)
        wm.modal_handler_add(self)
        context.workspace.status_text_set("隠れメッシュ削除: 解析中... (ESCでキャンセル)")
        return {'RUNNING_MODAL'}

    def modal(self, context, event):
        if event.type == 'ESC':
            self._cleanup(context)
            self.report({'WARNING'}, "キャンセルしました")
            return {'CANCELLED'}

        if event.type != 'TIMER':
            return {'RUNNING_MODAL'}

        chunk_start = time.monotonic()
        try:
            while time.monotonic() - chunk_start < self._time_budget:
                next(self._gen)
                self._index += 1
        except StopIteration:
            try:
                self._finish(context)
                return {'FINISHED'}
            except Exception as exc:
                self._cleanup(context)
                self.report({'ERROR'}, f"解析結果の反映中にエラーが発生しました: {exc}")
                return {'CANCELLED'}
        except Exception as exc:
            self._cleanup(context)
            self.report({'ERROR'}, f"解析中にエラーが発生しました: {exc}")
            return {'CANCELLED'}

        context.window_manager.progress_update(self._index)
        context.workspace.status_text_set(f"隠れメッシュ削除: 解析中... {self._index}/{self._total} (ESCでキャンセル)")
        for area in context.window.screen.areas:
            if area.type == 'VIEW_3D':
                area.tag_redraw()
        return {'RUNNING_MODAL'}

    def _finish(self, context):
        analysis = self._session.finish()
        body_object = self._session.body_object
        api.select_faces(context, body_object, analysis.hidden_face_indices)

        self._cleanup(context)
        message = (
            f"{analysis.hidden_face_count} / {len(body_object.data.polygons)} 面を"
            "隠れ面として選択しました"
        )
        margin_removed = analysis.raw_hidden_face_count - analysis.hidden_face_count
        if margin_removed:
            message += f"(安全余白で{margin_removed}面を保護)"
        self.report({'INFO'}, message)

    def _cleanup(self, context):
        wm = context.window_manager
        if self._timer is not None:
            wm.event_timer_remove(self._timer)
            self._timer = None
        if getattr(self, '_progress_active', False):
            wm.progress_end()
            self._progress_active = False
        context.workspace.status_text_set(None)
        self._gen = None
        self._session = None

    def cancel(self, context):
        self._cleanup(context)


class OBJECT_OT_amt_delete_hidden_faces(bpy.types.Operator):
    bl_idname = "object.amt_delete_hidden_faces"
    bl_label = "選択した面を削除"
    bl_description = "現在エディットモードで選択されている面を削除します。事前に「隠れた面を選択」で選択内容を確認してください"
    bl_options = {'REGISTER', 'UNDO'}

    _WARNING_LINES = (
        "選択中の面を削除します。",
        "シェイプキー(表情・視線等)や、ゲーム内で切り替える",
        "別の服を装着したときにだけ見える面が含まれていないか、",
        "必ず確認してから実行してください。",
        "削除前のボディはAMT_Backupsコレクションへ自動保存されます。",
    )

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return context.mode == 'EDIT_MESH' and obj is not None and obj.type == 'MESH'

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self, width=420)

    def draw(self, context):
        col = self.layout.column(align=True)
        for i, line in enumerate(self._WARNING_LINES):
            col.label(text=line, icon='ERROR' if i == 0 else 'NONE')

    def execute(self, context):
        obj = context.active_object
        bm = bmesh.from_edit_mesh(obj.data)
        bm.faces.ensure_lookup_table()
        bm.faces.index_update()
        selected_face_indices = [face.index for face in bm.faces if face.select]
        if not selected_face_indices:
            self.report({'WARNING'}, "選択された面がありません")
            return {'CANCELLED'}

        try:
            result = api.delete_faces(context, obj, selected_face_indices)
        except (api.HiddenMeshError, RuntimeError) as exc:
            self.report({'ERROR'}, f"面を削除できませんでした: {exc}")
            return {'CANCELLED'}

        msg = (
            f"{result['deleted_face_count']} 面を削除し、"
            f"バックアップ「{result['backup_object']}」を作成しました"
        )
        if result['freed_uv_region_count']:
            msg += (
                f"({result['freed_uv_region_count']} 個のUV解放領域を記録し、"
                "テクスチャベイク機能で再利用できます)"
            )
        self.report({'INFO'}, msg)
        return {'FINISHED'}


_classes = (
    OBJECT_OT_amt_add_clothing_object,
    OBJECT_OT_amt_remove_clothing_object,
    OBJECT_OT_amt_select_hidden_faces,
    OBJECT_OT_amt_delete_hidden_faces,
)


def register():
    for cls in _classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
