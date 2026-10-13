"""Public Python interface for hidden-mesh analysis and removal.

AI agents and Blender scripts should normally call :func:`run`. The modal UI
uses the same analysis session internally so both entry points produce the same
face selection, safety margin, backup, and UV-region behaviour.
"""

from dataclasses import dataclass

import bmesh
import bpy
import numpy as np

from ...core import mesh_eval, uv_regions
from ...core.context_utils import (
    capture_selection_state, object_usability_error, reset_to_object_mode_with_active,
    restore_selection_state, select_faces_in_edit_mode,
)
from . import utils


class HiddenMeshError(RuntimeError):
    """Raised when hidden-mesh analysis cannot be performed safely."""


@dataclass(frozen=True)
class HiddenMeshAnalysis:
    body_name: str
    hidden_face_indices: tuple
    hidden_vertex_count: int
    raw_hidden_face_count: int
    used_evaluated_mesh: bool
    safety_margin: str

    @property
    def hidden_face_count(self):
        return len(self.hidden_face_indices)

    def to_dict(self):
        return {
            'body': self.body_name,
            'hidden_face_indices': list(self.hidden_face_indices),
            'hidden_face_count': self.hidden_face_count,
            'hidden_vertex_count': self.hidden_vertex_count,
            'raw_hidden_face_count': self.raw_hidden_face_count,
            'margin_removed_face_count': self.raw_hidden_face_count - self.hidden_face_count,
            'used_evaluated_mesh': self.used_evaluated_mesh,
            'safety_margin': self.safety_margin,
        }


def _object_pointer(obj):
    as_pointer = getattr(obj, 'as_pointer', None)
    return as_pointer() if as_pointer is not None else id(obj)


def validate_body_action(context, body_object, action):
    """Reject unsafe edit-mode actions before changing selection or creating backups."""
    if body_object is None or getattr(body_object, 'type', None) != 'MESH':
        raise HiddenMeshError("有効なボディメッシュを指定してください")
    changes_mesh = action != 'ANALYZE'
    error = object_usability_error(
        context, body_object, "ボディメッシュ",
        require_editable=changes_mesh,
        require_visible=changes_mesh,
        require_single_user=changes_mesh,
    )
    if error is not None:
        raise HiddenMeshError(error)


def _validate_mesh_inputs(context, body_object, clothing_objects, include_body_self_occlusion):
    if body_object is None or getattr(body_object, 'type', None) != 'MESH':
        raise HiddenMeshError("有効なボディメッシュを指定してください")
    if body_object.data is None or len(body_object.data.vertices) == 0:
        raise HiddenMeshError("ボディメッシュに頂点がありません")

    clothing_objects = tuple(obj for obj in clothing_objects if obj is not None)
    if not clothing_objects and not include_body_self_occlusion:
        raise HiddenMeshError("服メッシュをひとつ以上指定してください")
    if any(getattr(obj, 'type', None) != 'MESH' for obj in clothing_objects):
        raise HiddenMeshError("服にはメッシュオブジェクトだけを指定してください")
    if any(obj is body_object for obj in clothing_objects):
        raise HiddenMeshError("ボディメッシュと服メッシュには別のオブジェクトを指定してください")
    if len({_object_pointer(obj) for obj in clothing_objects}) != len(clothing_objects):
        raise HiddenMeshError("同じ服メッシュが複数指定されています")

    empty_object = next(
        (obj for obj in clothing_objects if obj.data is None or len(obj.data.vertices) == 0),
        None,
    )
    if empty_object is not None:
        raise HiddenMeshError(f"服メッシュ「{empty_object.name}」に頂点がありません")

    for obj, label in [(body_object, "ボディメッシュ")] + [
        (obj, "服メッシュ") for obj in clothing_objects
    ]:
        error = object_usability_error(context, obj, label)
        if error is not None:
            raise HiddenMeshError(error)
    return clothing_objects


class AnalysisSession:
    """Incremental analysis shared by the modal UI and synchronous public call."""

    def __init__(
        self,
        context,
        body_object,
        clothing_objects,
        *,
        ray_samples=24,
        ray_epsilon_ratio=0.0002,
        face_select_mode='ALL',
        safety_margin='MEDIUM',
        include_body_self_occlusion=False,
        self_occlusion_min_distance_ratio=0.01,
        exclude_vertex_group='',
    ):
        if face_select_mode not in {'ALL', 'ANY'}:
            raise HiddenMeshError(f"不明な判定モードです: {face_select_mode}")
        if safety_margin not in utils.SAFETY_MARGIN_RINGS:
            raise HiddenMeshError(f"不明な安全余白です: {safety_margin}")
        if ray_samples < 4 or ray_samples > 256:
            raise HiddenMeshError("サンプル数は4～256の範囲で指定してください")

        clothing_objects = _validate_mesh_inputs(
            context,
            body_object,
            clothing_objects,
            include_body_self_occlusion,
        )
        reset_to_object_mode_with_active(context, body_object)
        depsgraph = context.evaluated_depsgraph_get()
        if not body_object.evaluated_get(depsgraph).is_evaluated:
            raise HiddenMeshError(
                f"ボディメッシュ「{body_object.name}」を現在のビューポートで評価できません。"
                "オブジェクトとコレクションの表示を有効にしてください"
            )
        try:
            clothing_bvh, clothing_min, clothing_max = mesh_eval.build_bvh_from_objects(
                depsgraph,
                clothing_objects,
            )
            self_bvh = None
            if include_body_self_occlusion:
                self_bvh, _, _ = mesh_eval.build_bvh_from_objects(depsgraph, [body_object])
            positions, normals, used_evaluated = mesh_eval.snapshot_deform_only(depsgraph, body_object)
        except ValueError as exc:
            raise HiddenMeshError(str(exc)) from exc
        if clothing_bvh is None and self_bvh is None:
            raise HiddenMeshError("遮蔽物として使用できるメッシュがありません")

        bbox_diagonal = mesh_eval.compute_bbox_diagonal(positions)
        epsilon = max(bbox_diagonal * ray_epsilon_ratio, 1e-6)
        max_distance = max(bbox_diagonal * utils.RAY_MAX_DISTANCE_FACTOR, 1.0)
        self_min_distance = max(
            bbox_diagonal * self_occlusion_min_distance_ratio,
            epsilon * 4.0,
        )
        protected_mask = mesh_eval.get_protected_vertex_mask(body_object, exclude_vertex_group)

        self.body_object = body_object
        self.total = len(positions)
        self.used_evaluated_mesh = used_evaluated
        self.estimated_ray_count = self.total * ray_samples
        self._face_select_mode = face_select_mode
        self._safety_margin = safety_margin
        self._protected_mask = protected_mask
        self._flags = np.zeros(self.total, dtype=bool)
        self._generator = utils.iter_hidden_vertex_flags(
            positions,
            normals,
            self._flags,
            clothing_bvh=clothing_bvh,
            clothing_bounds=(clothing_min, clothing_max),
            self_bvh=self_bvh,
            protected_mask=protected_mask,
            sample_count=ray_samples,
            epsilon=epsilon,
            max_distance=max_distance,
            self_min_distance=self_min_distance,
        )

    def __iter__(self):
        return self

    def __next__(self):
        return next(self._generator)

    def finish(self):
        mesh = self.body_object.data
        raw_mask = mesh_eval.compute_face_mask_from_vertex_flags(mesh, self._flags, self._face_select_mode)
        # Protection is an independent veto, even when ANY accepts another hidden vertex.
        if self._protected_mask.any():
            for polygon in mesh.polygons:
                if self._protected_mask[list(polygon.vertices)].any():
                    raw_mask[polygon.index] = False
        final_mask = utils.inset_hidden_face_mask(mesh, raw_mask, self._safety_margin)
        return HiddenMeshAnalysis(
            body_name=self.body_object.name,
            hidden_face_indices=tuple(np.flatnonzero(final_mask).tolist()),
            hidden_vertex_count=int(self._flags.sum()),
            raw_hidden_face_count=int(raw_mask.sum()),
            used_evaluated_mesh=self.used_evaluated_mesh,
            safety_margin=self._safety_margin,
        )


def select_faces(context, body_object, face_indices):
    """Replace the current edit-mode selection with the specified body faces."""
    validate_body_action(context, body_object, 'SELECT')
    try:
        select_faces_in_edit_mode(context, body_object, face_indices)
    except ValueError as exc:
        raise HiddenMeshError(str(exc)) from exc


def create_body_backup(context, body_object):
    """Create a hidden, independent copy of the body before destructive editing."""
    reset_to_object_mode_with_active(context, body_object)
    backups = bpy.data.collections.get("AMT_Backups")
    if backups is None:
        backups = bpy.data.collections.new("AMT_Backups")
    if backups.name not in context.scene.collection.children:
        context.scene.collection.children.link(backups)

    backup = body_object.copy()
    backup.data = body_object.data.copy()
    backup.name = f"{body_object.name}_AMT_Backup"
    backup.data.name = f"{body_object.data.name}_AMT_Backup"
    backup['amt_backup_source'] = body_object.name
    backups.objects.link(backup)
    backup.hide_render = True
    backup.hide_set(True)
    return backup


def delete_faces(context, body_object, face_indices):
    """Back up the body, delete the requested faces, and record freed UV regions."""
    validate_body_action(context, body_object, 'DELETE')
    face_indices = tuple(sorted({int(index) for index in face_indices}))
    if not face_indices:
        raise HiddenMeshError("削除する面がありません")

    backup = create_body_backup(context, body_object)
    bpy.ops.object.mode_set(mode='EDIT')
    bm = bmesh.from_edit_mesh(body_object.data)
    bm.faces.ensure_lookup_table()
    selected_faces = [bm.faces[index] for index in face_indices if 0 <= index < len(bm.faces)]
    if not selected_faces:
        raise HiddenMeshError("削除する面がありません")

    rects_captured = 0
    uv_layer = bm.loops.layers.uv.active
    if uv_layer is not None:
        new_rects = uv_regions.compute_freed_uv_rects(selected_faces, uv_layer, body_object.name)
        if new_rects:
            uv_regions.add_freed_rects(body_object.data, new_rects)
            rects_captured = len(new_rects)

    deleted_count = len(selected_faces)
    bmesh.ops.delete(bm, geom=selected_faces, context='FACES')
    bmesh.update_edit_mesh(body_object.data)
    return {
        'deleted_face_count': deleted_count,
        'freed_uv_region_count': rects_captured,
        'backup_object': backup.name,
    }


def _resolve_mesh_object(value, label):
    if isinstance(value, str):
        value = bpy.data.objects.get(value)
    if value is None or getattr(value, 'type', None) != 'MESH':
        raise HiddenMeshError(f"{label}に有効なメッシュ名またはメッシュオブジェクトを指定してください")
    return value


def run(
    body,
    clothing=(),
    *,
    context=None,
    action='SELECT',
    ray_samples=24,
    ray_epsilon_ratio=0.0002,
    face_select_mode='ALL',
    safety_margin='MEDIUM',
    include_body_self_occlusion=False,
    self_occlusion_min_distance_ratio=0.01,
    exclude_vertex_group='',
):
    """Analyze and optionally select or delete hidden body faces.

    ``body`` and entries in ``clothing`` accept either Blender objects or names.
    ``action`` is ``ANALYZE``, ``SELECT``, or ``DELETE``. DELETE always creates an
    independent body backup in the ``AMT_Backups`` collection first.
    The returned dictionary is JSON-serializable for agent integrations.
    """
    context = context or bpy.context
    body_object = _resolve_mesh_object(body, "body")
    if isinstance(clothing, (str, bpy.types.Object)):
        clothing = [clothing]
    clothing_objects = [_resolve_mesh_object(value, "clothing") for value in clothing]

    normalized_action = action.upper()
    if normalized_action not in {'ANALYZE', 'SELECT', 'DELETE'}:
        raise HiddenMeshError(f"不明なactionです: {action}")

    # ANALYZE and rejected actions hand the user's active object, selection and mode back.
    previous_state = capture_selection_state(context)
    completed = False
    try:
        validate_body_action(context, body_object, normalized_action)
        session = AnalysisSession(
            context,
            body_object,
            clothing_objects,
            ray_samples=ray_samples,
            ray_epsilon_ratio=ray_epsilon_ratio,
            face_select_mode=face_select_mode,
            safety_margin=safety_margin,
            include_body_self_occlusion=include_body_self_occlusion,
            self_occlusion_min_distance_ratio=self_occlusion_min_distance_ratio,
            exclude_vertex_group=exclude_vertex_group,
        )
        for _ in session:
            pass
        analysis = session.finish()
        result = analysis.to_dict()
        result['action'] = normalized_action

        if normalized_action == 'SELECT':
            select_faces(context, body_object, analysis.hidden_face_indices)
        elif normalized_action == 'DELETE':
            result.update(delete_faces(context, body_object, analysis.hidden_face_indices))
        completed = True
        return result
    except ValueError as exc:
        raise HiddenMeshError(str(exc)) from exc
    finally:
        if normalized_action == 'ANALYZE' or not completed:
            restore_selection_state(context, previous_state)
