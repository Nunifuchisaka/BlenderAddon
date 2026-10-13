"""Blender background regression test for the review of poke_through / merge / diagnostics /
texture_relink / armature_align and core.

Run: blender --background --factory-startup --python tests/blender_review_rest_smoke.py
"""

import math
import sys
import tempfile
import traceback
from pathlib import Path

import bmesh
import bpy


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

import NuniAvatarToolkit
from NuniAvatarToolkit.core import mesh_eval


def reset_scene():
  if bpy.context.mode != 'OBJECT':
    bpy.ops.object.mode_set(mode='OBJECT')
  for obj in list(bpy.data.objects):
    bpy.data.objects.remove(obj, do_unlink=True)
  for scene in list(bpy.data.scenes):
    if scene != bpy.context.scene:
      bpy.data.scenes.remove(scene)


def make_sphere(name, radius, location=(0.0, 0.0, 0.0), segments=16, rings=8, collection=None):
  mesh = bpy.data.meshes.new(f"{name}Mesh")
  bm = bmesh.new()
  bmesh.ops.create_uvsphere(bm, u_segments=segments, v_segments=rings, radius=radius)
  bm.to_mesh(mesh)
  bm.free()
  obj = bpy.data.objects.new(name, mesh)
  obj.location = location
  (collection or bpy.context.scene.collection).objects.link(obj)
  return obj


def make_active(*objects):
  for other in bpy.context.selected_objects:
    other.select_set(False)
  for obj in objects:
    obj.select_set(True)
  bpy.context.view_layer.objects.active = objects[0]


def link_from_library(name, build):
  """Write the object built by build() to a temporary .blend and link it back into the scene."""
  path = str(Path(tempfile.mkdtemp()) / "library.blend")
  obj = build()
  bpy.data.libraries.write(path, {obj}, fake_user=True)
  mesh = obj.data
  bpy.data.objects.remove(obj, do_unlink=True)
  bpy.data.meshes.remove(mesh)
  with bpy.data.libraries.load(path, link=True) as (_source, target):
    target.objects = [name]
  linked = target.objects[0]
  bpy.context.scene.collection.objects.link(linked)
  return linked


def assert_cancelled(expected_message, operator, *args):
  try:
    result = operator(*args)
  except RuntimeError as exc:
    assert expected_message in str(exc) and "Traceback" not in str(exc), str(exc)
    return
  raise AssertionError(f"expected cancellation, got {result}")


def base_world_positions(obj):
  return [tuple(round(c, 5) for c in obj.matrix_world @ v.co) for v in obj.data.vertices]


# --- core/mesh_eval ---------------------------------------------------------------------------

def test_mesh_eval_ignores_vertex_reordering_modifiers():
  reset_scene()
  body = make_sphere("Body", 1.0)
  tree = bpy.data.node_groups.new("Reorder", 'GeometryNodeTree')
  tree.interface.new_socket(name="Geometry", in_out='INPUT', socket_type='NodeSocketGeometry')
  tree.interface.new_socket(name="Geometry", in_out='OUTPUT', socket_type='NodeSocketGeometry')
  group_in = tree.nodes.new('NodeGroupInput')
  group_out = tree.nodes.new('NodeGroupOutput')
  sort = tree.nodes.new('GeometryNodeSortElements')
  position = tree.nodes.new('GeometryNodeInputPosition')
  separate = tree.nodes.new('ShaderNodeSeparateXYZ')
  tree.links.new(group_in.outputs[0], sort.inputs['Geometry'])
  tree.links.new(position.outputs[0], separate.inputs[0])
  tree.links.new(separate.outputs['X'], sort.inputs['Sort Weight'])
  tree.links.new(sort.outputs['Geometry'], group_out.inputs[0])
  body.modifiers.new("Reorder", 'NODES').node_group = tree
  bpy.context.view_layer.update()

  positions, _normals, _used = mesh_eval.snapshot_deform_only(bpy.context.evaluated_depsgraph_get(), body)
  actual = [tuple(round(float(c), 5) for c in p) for p in positions]
  assert actual == base_world_positions(body)
  assert body.modifiers["Reorder"].show_viewport


def test_mesh_eval_keeps_mesh_cache_enabled():
  reset_scene()
  body = make_sphere("Body", 1.0)
  body.modifiers.new("Cache", 'MESH_CACHE')
  body.modifiers.new("Subsurf", 'SUBSURF')
  disabled = mesh_eval.disable_non_deform_modifiers(body)
  try:
    assert [mod.name for mod, _ in disabled] == ["Subsurf"], [mod.name for mod, _ in disabled]
    assert body.modifiers["Cache"].show_viewport
  finally:
    mesh_eval.restore_modifiers(disabled)
  assert body.modifiers["Subsurf"].show_viewport


def test_mesh_eval_linked_object_falls_back_safely():
  reset_scene()

  def build():
    obj = make_sphere("LinkedBody", 1.0)
    obj.modifiers.new("Subsurf", 'SUBSURF')
    return obj

  linked = link_from_library("LinkedBody", build)
  bpy.context.view_layer.update()
  positions, _normals, used = mesh_eval.snapshot_deform_only(bpy.context.evaluated_depsgraph_get(), linked)
  assert not used
  assert len(positions) == len(linked.data.vertices)
  assert linked.modifiers["Subsurf"].show_viewport


# --- poke_through -----------------------------------------------------------------------------

def _setup_poke(body, clothing):
  props = bpy.context.scene.amt_poke_through
  props.clothing_objects.clear()
  props.body_object = body
  props.clothing_objects.add().object = clothing
  props.exclude_vertex_group = ""
  return props


def test_poke_through_restores_context_when_nothing_is_selected():
  reset_scene()
  body = make_sphere("Body", 1.0)
  clothing = make_sphere("Clothing", 1.2)
  empty_mesh = bpy.data.meshes.new("EmptyMesh")
  empty_mesh.from_pydata([(0, 0, 0)], [], [])
  empty_clothing = bpy.data.objects.new("EmptyClothing", empty_mesh)
  bpy.context.scene.collection.objects.link(empty_clothing)
  other = make_sphere("Other", 0.3, location=(5.0, 0.0, 0.0))

  make_active(other)
  bpy.ops.object.mode_set(mode='EDIT')
  _setup_poke(body, empty_clothing)
  assert_cancelled("服メッシュに面がありません", bpy.ops.object.amt_check_poke_through)
  assert bpy.context.mode == 'EDIT_MESH' and bpy.context.view_layer.objects.active == other

  _setup_poke(body, clothing)
  assert bpy.ops.object.amt_check_poke_through() == {'FINISHED'}
  assert bpy.context.mode == 'EDIT_MESH' and bpy.context.view_layer.objects.active == other
  assert not body.select_get()


def test_poke_through_rejects_body_outside_view_layer():
  reset_scene()
  other_scene = bpy.data.scenes.new("OtherScene")
  body = make_sphere("Body", 1.0, collection=other_scene.collection)
  clothing = make_sphere("Clothing", 1.2)
  _setup_poke(body, clothing)
  assert_cancelled("ビューレイヤーにありません", bpy.ops.object.amt_check_poke_through)


# --- merge ------------------------------------------------------------------------------------

def _material(name):
  return bpy.data.materials.get(name) or bpy.data.materials.new(name)


def test_merge_join_rejects_linked_meshes():
  reset_scene()
  linked = link_from_library("LinkedPart", lambda: make_sphere("LinkedPart", 0.5))
  local = make_sphere("Local", 1.0)
  make_active(local, linked)
  assert_cancelled("リンク", bpy.ops.object.amt_merge_join, 'EXEC_DEFAULT')
  assert "LinkedPart" in bpy.context.scene.objects


def test_merge_slots_removes_only_duplicates():
  reset_scene()
  obj = make_sphere("Body", 1.0)
  mat_a, mat_b = _material("A"), _material("B")
  obj.data.materials.append(mat_a)
  obj.data.materials.append(mat_a)
  obj.data.materials.append(mat_b)
  for i, poly in enumerate(obj.data.polygons):
    poly.material_index = i % 2
  make_active(obj)
  assert bpy.ops.object.amt_merge_material_slots('EXEC_DEFAULT') == {'FINISHED'}
  assert [slot.material.name for slot in obj.material_slots] == ["A", "B"]
  assert all(poly.material_index == 0 for poly in obj.data.polygons)


def test_merge_slots_rejects_shared_mesh():
  reset_scene()
  obj = make_sphere("Body", 1.0)
  obj.data.materials.append(_material("A"))
  obj.data.materials.append(_material("A"))
  twin = bpy.data.objects.new("Twin", obj.data)
  bpy.context.scene.collection.objects.link(twin)
  make_active(obj)
  assert_cancelled("共有", bpy.ops.object.amt_merge_material_slots, 'EXEC_DEFAULT')
  assert len(obj.material_slots) == 2


def test_merge_slots_noop_keeps_context():
  reset_scene()
  obj = make_sphere("Body", 1.0)
  other = make_sphere("Other", 0.5, location=(3.0, 0.0, 0.0))
  obj.data.materials.append(_material("A"))
  make_active(obj, other)
  bpy.ops.object.mode_set(mode='EDIT')
  assert bpy.ops.object.amt_merge_material_slots('EXEC_DEFAULT') == {'CANCELLED'}
  assert bpy.context.mode == 'EDIT_MESH'
  assert other.select_get() and obj.select_get()


# --- diagnostics ------------------------------------------------------------------------------

def _run_diagnostics(collection):
  props = bpy.context.scene.amt_diagnostics
  props.avatar_collection = collection
  bpy.ops.object.amt_diagnostics_run()
  return [line.text for line in props.report_lines]


def test_diagnostics_reports_platform_ranks_and_slots():
  reset_scene()
  collection = bpy.data.collections.new("Avatar")
  bpy.context.scene.collection.children.link(collection)
  obj = make_sphere("Body", 1.0, collection=collection)
  for _ in range(3):
    obj.data.materials.append(_material("A"))
  texts = _run_diagnostics(collection)
  assert any(t.startswith("ポリゴン数(三角形換算)") and "PC: Excellent / Quest: Excellent" in t for t in texts), texts
  assert any(t.startswith("マテリアルスロット数: 3 ") and "PC: Excellent / Quest: Poor" in t for t in texts), texts


def test_diagnostics_reads_edit_mode_changes_and_shape_keys():
  reset_scene()
  collection = bpy.data.collections.new("Avatar")
  bpy.context.scene.collection.children.link(collection)
  obj = make_sphere("Body", 1.0, collection=collection)
  obj.shape_key_add(name="Basis", from_mix=False)
  broken = obj.shape_key_add(name="Broken", from_mix=False)
  broken.data[0].co.x = math.nan
  obj.delta_scale = (1.0, 2.0, 1.0)
  make_active(obj)
  bpy.ops.object.mode_set(mode='EDIT')
  bm = bmesh.from_edit_mesh(obj.data)
  bm.verts.ensure_lookup_table()
  bm.verts[1].co.x = math.inf
  bmesh.update_edit_mesh(obj.data)

  texts = _run_diagnostics(collection)
  assert any("不正な座標(NaN/Inf)の頂点が 1 個" in t and "シェイプキー" not in t for t in texts), texts
  assert any("シェイプキー「Broken」" in t for t in texts), texts
  assert any("スケールが不均一" in t for t in texts), texts


def test_diagnostics_rejects_collection_from_other_scene():
  reset_scene()
  other_scene = bpy.data.scenes.new("OtherScene")
  collection = bpy.data.collections.new("Elsewhere")
  other_scene.collection.children.link(collection)
  make_sphere("Body", 1.0, collection=collection)
  props = bpy.context.scene.amt_diagnostics
  props.avatar_collection = collection
  assert_cancelled("現在のシーンにありません", bpy.ops.object.amt_diagnostics_run)


# --- armature_align ---------------------------------------------------------------------------

def test_armature_align_rolls_back_when_constrained():
  reset_scene()
  bpy.ops.object.armature_add(location=(0.0, 0.0, 0.0))
  reference = bpy.context.active_object
  reference.data.bones[0].name = "Hips"
  bpy.ops.object.armature_add(location=(2.0, 0.0, 0.0))
  target = bpy.context.active_object
  target.data.bones[0].name = "Hips"
  anchor = bpy.data.objects.new("Anchor", None)
  bpy.context.scene.collection.objects.link(anchor)
  anchor.location = (2.0, 0.0, 0.0)
  target.constraints.new('COPY_LOCATION').target = anchor
  bpy.context.view_layer.update()
  original_location = tuple(target.location)

  props = bpy.context.scene.amt_armature_align
  props.reference_object = reference
  props.reference_bone = "Hips"
  props.target_object = target
  props.target_bone = "Hips"
  assert_cancelled("元に戻しました", bpy.ops.object.amt_align_armature)
  assert tuple(target.location) == original_location, tuple(target.location)


TESTS = (
  test_mesh_eval_ignores_vertex_reordering_modifiers,
  test_mesh_eval_keeps_mesh_cache_enabled,
  test_mesh_eval_linked_object_falls_back_safely,
  test_poke_through_restores_context_when_nothing_is_selected,
  test_poke_through_rejects_body_outside_view_layer,
  test_merge_join_rejects_linked_meshes,
  test_merge_slots_removes_only_duplicates,
  test_merge_slots_rejects_shared_mesh,
  test_merge_slots_noop_keeps_context,
  test_diagnostics_reports_platform_ranks_and_slots,
  test_diagnostics_reads_edit_mode_changes_and_shape_keys,
  test_diagnostics_rejects_collection_from_other_scene,
  test_armature_align_rolls_back_when_constrained,
)


def main():
  bpy.ops.wm.read_factory_settings(use_empty=True)
  NuniAvatarToolkit.register()
  failures = []
  try:
    for test in TESTS:
      try:
        test()
        print(f"PASS {test.__name__}")
      except Exception:
        failures.append(test.__name__)
        print(f"FAIL {test.__name__}")
        traceback.print_exc()
  finally:
    if bpy.context.mode != 'OBJECT':
      bpy.ops.object.mode_set(mode='OBJECT')
    NuniAvatarToolkit.unregister()
  if failures:
    print("BLENDER_REVIEW_REST_FAILED: " + ", ".join(failures))
    sys.exit(1)
  print("BLENDER_REVIEW_REST_SMOKE_OK")


main()
