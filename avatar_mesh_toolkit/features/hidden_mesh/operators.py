import time

import bmesh
import bpy
import numpy as np

from ...core import mesh_eval, uv_regions
from ...core.context_utils import reset_to_object_mode_with_active
from . import utils


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
        return props.clothing_collection is not None or props.include_body_self_occlusion

    def invoke(self, context, event):
        scene = context.scene
        props = scene.amt_hidden_mesh
        body_obj = props.body_object

        reset_to_object_mode_with_active(context, body_obj)

        depsgraph = context.evaluated_depsgraph_get()

        clothing_objs = utils.get_clothing_objects(props.clothing_collection, body_obj)
        if not clothing_objs and not props.include_body_self_occlusion:
            self.report({'ERROR'}, "服コレクションに有効なメッシュがありません")
            return {'CANCELLED'}

        clothing_bvh, clothing_min, clothing_max = mesh_eval.build_bvh_from_objects(depsgraph, clothing_objs)

        self_bvh = None
        if props.include_body_self_occlusion:
            self_bvh, _, _ = mesh_eval.build_bvh_from_objects(depsgraph, [body_obj])

        if clothing_bvh is None and self_bvh is None:
            self.report({'ERROR'}, "遮蔽物として使用できるメッシュがありません")
            return {'CANCELLED'}

        positions, normals, used_evaluated = mesh_eval.snapshot_deform_only(depsgraph, body_obj)
        if not used_evaluated:
            self.report({'WARNING'}, "一部のモディファイア構成のため、変形前(レスト)座標で判定しました")

        bbox_diagonal = mesh_eval.compute_bbox_diagonal(positions)
        epsilon = max(bbox_diagonal * props.ray_epsilon_ratio, 1e-6)
        max_distance = max(bbox_diagonal * utils.RAY_MAX_DISTANCE_FACTOR, 1.0)
        self_min_distance = max(bbox_diagonal * props.self_occlusion_min_distance_ratio, epsilon * 4.0)

        protected_mask = utils.get_protected_vertex_mask(body_obj, props.exclude_vertex_group)

        total = len(positions)
        estimate = total * props.ray_samples
        if estimate > utils.PERFORMANCE_WARNING_VERTEX_SAMPLES:
            self.report(
                {'WARNING'},
                f"頂点数×サンプル数が多いため処理に時間がかかる可能性があります({total} x {props.ray_samples})",
            )

        self._flags = np.zeros(total, dtype=bool)
        self._gen = utils.iter_hidden_vertex_flags(
            positions, normals, self._flags,
            clothing_bvh=clothing_bvh,
            clothing_bounds=(clothing_min, clothing_max),
            self_bvh=self_bvh,
            protected_mask=protected_mask,
            sample_count=props.ray_samples,
            epsilon=epsilon,
            max_distance=max_distance,
            self_min_distance=self_min_distance,
        )
        self._body_obj = body_obj
        self._face_mode = props.face_select_mode
        self._total = total
        self._index = 0
        self._time_budget = 0.03

        wm = context.window_manager
        wm.progress_begin(0, total)
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
            self._finish(context)
            return {'FINISHED'}

        context.window_manager.progress_update(self._index)
        context.workspace.status_text_set(f"隠れメッシュ削除: 解析中... {self._index}/{self._total} (ESCでキャンセル)")
        for area in context.window.screen.areas:
            if area.type == 'VIEW_3D':
                area.tag_redraw()
        return {'RUNNING_MODAL'}

    def _finish(self, context):
        body_obj = self._body_obj
        mesh = body_obj.data
        hidden_face_mask = utils.compute_hidden_face_mask(mesh, self._flags, self._face_mode)
        hidden_count = int(hidden_face_mask.sum())

        reset_to_object_mode_with_active(context, body_obj)
        bpy.ops.object.mode_set(mode='EDIT')
        context.tool_settings.mesh_select_mode = (False, False, True)
        bpy.ops.mesh.select_all(action='DESELECT')

        bm = bmesh.from_edit_mesh(mesh)
        bm.faces.ensure_lookup_table()
        for idx, hidden in enumerate(hidden_face_mask):
            if hidden:
                bm.faces[idx].select = True
        bmesh.update_edit_mesh(mesh)

        self._cleanup(context)
        self.report({'INFO'}, f"{hidden_count} / {len(mesh.polygons)} 面を隠れ面として選択しました")

    def _cleanup(self, context):
        wm = context.window_manager
        if self._timer is not None:
            wm.event_timer_remove(self._timer)
            self._timer = None
        wm.progress_end()
        context.workspace.status_text_set(None)
        self._gen = None

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
        "作業前にファイルを保存することを推奨します。",
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
        mesh = obj.data
        bm = bmesh.from_edit_mesh(mesh)
        selected_faces = [f for f in bm.faces if f.select]
        if not selected_faces:
            self.report({'WARNING'}, "選択された面がありません")
            return {'CANCELLED'}
        count = len(selected_faces)

        # Captured here (using the actual selection, which the user may have hand-adjusted
        # since "select hidden faces" ran) because this is the last moment the UV data of the
        # about-to-be-destroyed faces still exists; the texture_bake feature reads this later
        # to let the user reclaim the freed texture space.
        rects_captured = 0
        uv_layer = bm.loops.layers.uv.active
        if uv_layer is not None:
            new_rects = uv_regions.compute_freed_uv_rects(selected_faces, uv_layer, obj.name)
            if new_rects:
                uv_regions.add_freed_rects(mesh, new_rects)
                rects_captured = len(new_rects)

        bmesh.ops.delete(bm, geom=selected_faces, context='FACES')
        bmesh.update_edit_mesh(mesh)

        msg = f"{count} 面を削除しました"
        if rects_captured:
            msg += f"({rects_captured} 個のUV解放領域を記録し、テクスチャベイク機能で再利用できます)"
        self.report({'INFO'}, msg)
        return {'FINISHED'}


_classes = (OBJECT_OT_amt_select_hidden_faces, OBJECT_OT_amt_delete_hidden_faces)


def register():
    for cls in _classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
