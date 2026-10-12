"""Blender background regression test for issues found in the adversarial review.

Run: blender --background --factory-startup --python tests/blender_review_fixes_smoke.py
"""

import sys
import traceback
from pathlib import Path

import bmesh
import bpy


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

import NuniAvatarToolkit
from NuniAvatarToolkit.features.cleanup import utils as cleanup_utils


def reset_scene():
  if bpy.context.mode != 'OBJECT':
    bpy.ops.object.mode_set(mode='OBJECT')
  for obj in list(bpy.data.objects):
    bpy.data.objects.remove(obj, do_unlink=True)


def make_mesh(name, verts, edges=(), faces=()):
  mesh = bpy.data.meshes.new(f"{name}Mesh")
  mesh.from_pydata(list(verts), list(edges), list(faces))
  mesh.update()
  obj = bpy.data.objects.new(name, mesh)
  bpy.context.scene.collection.objects.link(obj)
  return obj


def make_sphere(name, radius, location=(0.0, 0.0, 0.0), segments=24, rings=12):
  mesh = bpy.data.meshes.new(f"{name}Mesh")
  bm = bmesh.new()
  bmesh.ops.create_uvsphere(bm, u_segments=segments, v_segments=rings, radius=radius)
  bm.to_mesh(mesh)
  bm.free()
  obj = bpy.data.objects.new(name, mesh)
  obj.location = location
  bpy.context.scene.collection.objects.link(obj)
  return obj


def make_active(obj):
  for other in bpy.context.selected_objects:
    other.select_set(False)
  bpy.context.view_layer.objects.active = obj
  obj.select_set(True)


def assert_cancelled(operator, *args):
  # An operator that reports ERROR makes bpy.ops raise RuntimeError instead of returning CANCELLED.
  try:
    result = operator(*args)
  except RuntimeError:
    return
  assert result == {'CANCELLED'}, result


def set_cleanup_flags(props, **flags):
  for name in (
    'remove_empty_vertex_groups', 'remove_noop_shape_keys', 'remove_unused_uv_maps',
    'remove_unused_vertex_colors', 'remove_unused_material_slots', 'remove_loose_geometry',
  ):
    setattr(props, name, flags.get(name, False))


def test_cleanup_with_regular_modifiers():
  reset_scene()
  bpy.ops.object.armature_add()
  armature = bpy.context.active_object
  bpy.ops.mesh.primitive_cube_add()
  obj = bpy.context.active_object
  obj.data.uv_layers.new(name="UnusedUV")
  obj.modifiers.new("Armature", 'ARMATURE').object = armature
  obj.modifiers.new("Subsurf", 'SUBSURF')

  props = bpy.context.scene.amt_cleanup
  props.target_object = obj
  set_cleanup_flags(props, remove_unused_uv_maps=True, remove_unused_vertex_colors=True)
  assert bpy.ops.object.amt_cleanup_scan() == {'FINISHED'}
  assert bpy.ops.object.amt_cleanup_execute('EXEC_DEFAULT') == {'FINISHED'}
  assert "UnusedUV" not in obj.data.uv_layers, [uv.name for uv in obj.data.uv_layers]


def test_noop_shape_keys_respect_relative_key():
  reset_scene()
  obj = make_mesh("Keys", [(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)], faces=[(0, 1, 2, 3)])
  basis = obj.shape_key_add(name="Basis", from_mix=False)
  smile = obj.shape_key_add(name="Smile", from_mix=False)
  smile.data[0].co.z = 0.1
  smile_fix = obj.shape_key_add(name="SmileFix", from_mix=False)
  smile_fix.relative_key = smile
  helper = obj.shape_key_add(name="Helper", from_mix=False)
  uses_helper = obj.shape_key_add(name="UsesHelper", from_mix=False)
  uses_helper.relative_key = helper
  uses_helper.data[1].co.z = 0.2
  obj.shape_key_add(name="Empty", from_mix=False)
  assert basis.relative_key == basis

  noop = cleanup_utils.find_noop_shape_keys(obj, 1e-5)
  assert noop == ["Empty"], noop


def test_cleanup_removes_loose_geometry():
  reset_scene()
  obj = make_mesh(
    "Loose",
    [(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0), (3, 0, 0), (3, 1, 0)],
    edges=[(4, 5)],
    faces=[(0, 1, 2, 3)],
  )
  obj.shape_key_add(name="Basis", from_mix=False)
  key = obj.shape_key_add(name="Lift", from_mix=False)
  key.data[2].co.z = 0.5
  make_active(obj)

  props = bpy.context.scene.amt_cleanup
  props.target_object = obj
  set_cleanup_flags(props, remove_loose_geometry=True)
  assert bpy.ops.object.amt_cleanup_execute('EXEC_DEFAULT') == {'FINISHED'}
  assert bpy.context.mode == 'OBJECT'
  assert len(obj.data.vertices) == 4, len(obj.data.vertices)
  assert len(obj.data.edges) == 4, len(obj.data.edges)
  lift = obj.data.shape_keys.key_blocks["Lift"]
  assert abs(max(d.co.z for d in lift.data) - 0.5) < 1e-6
  texts = [line.text for line in props.report_lines]
  assert any("浮遊頂点 2 個" in t and "浮遊エッジ 1 個" in t for t in texts), texts


def test_bone_follow_from_edit_mode():
  reset_scene()
  bpy.ops.object.armature_add()
  armature = bpy.context.active_object
  armature.data.bones[0].name = "FollowBone"
  bpy.ops.mesh.primitive_cube_add(location=(2.0, 0.0, 0.0))
  target = bpy.context.active_object
  bpy.ops.object.mode_set(mode='EDIT')

  props = bpy.context.scene.amt_bone_follow
  props.target_object = target
  props.armature_object = armature
  props.bone_name = "FollowBone"
  assert bpy.ops.object.amt_assign_rigid_bone_weight() == {'FINISHED'}
  assert target.mode == 'OBJECT'
  group = target.vertex_groups["FollowBone"]
  for vertex in target.data.vertices:
    weight = next(item.weight for item in vertex.groups if item.group == group.index)
    assert abs(weight - 1.0) < 1e-6


def test_bone_follow_cancel_keeps_edit_mode():
  reset_scene()
  bpy.ops.object.armature_add()
  armature = bpy.context.active_object
  bpy.ops.mesh.primitive_cube_add(location=(2.0, 0.0, 0.0))
  target = bpy.context.active_object
  bpy.ops.object.mode_set(mode='EDIT')

  props = bpy.context.scene.amt_bone_follow
  props.target_object = target
  props.armature_object = armature
  props.bone_name = "Missing"
  assert_cancelled(bpy.ops.object.amt_assign_rigid_bone_weight)
  assert target.mode == 'EDIT'
  assert not any(m.type == 'ARMATURE' for m in target.modifiers)


def _fit_coordinates(obj, name):
  return [tuple(round(c, 6) for c in d.co) for d in obj.data.shape_keys.key_blocks[name].data]


def test_cloth_fit_rerun_keeps_key_settings():
  reset_scene()
  body = make_sphere("Body", 1.0)
  cloth = make_sphere("Cloth", 0.97, location=(0.05, 0.0, 0.0), segments=32, rings=16)
  group = cloth.vertex_groups.new(name="Fit")
  group.add([v.index for v in cloth.data.vertices if v.co.z > -0.3], 0.8, 'REPLACE')
  bpy.context.view_layer.update()

  props = bpy.context.scene.amt_cloth_fit
  props.body_object = body
  props.clothing_object = cloth
  props.vertex_group = "Fit"
  assert bpy.ops.object.amt_cloth_fit('EXEC_DEFAULT') == {'FINISHED'}
  first = _fit_coordinates(cloth, "AMT_Fit")

  key_blocks = cloth.data.shape_keys.key_blocks
  fit = key_blocks["AMT_Fit"]
  fit.slider_min = -1.0
  fit.slider_max = 2.0
  fit.vertex_group = "Fit"
  dependent = cloth.shape_key_add(name="Dependent", from_mix=False)
  dependent.relative_key = fit

  assert bpy.ops.object.amt_cloth_fit('EXEC_DEFAULT') == {'FINISHED'}
  key_blocks = cloth.data.shape_keys.key_blocks
  fit = key_blocks["AMT_Fit"]
  assert fit.slider_min == -1.0 and fit.slider_max == 2.0, (fit.slider_min, fit.slider_max)
  assert fit.vertex_group == "Fit", fit.vertex_group
  assert key_blocks["Dependent"].relative_key == fit, key_blocks["Dependent"].relative_key.name
  assert _fit_coordinates(cloth, "AMT_Fit") == first


def _setup_cloth_fit(shape_key_name="AMT_Fit"):
  reset_scene()
  body = make_sphere("Body", 1.0)
  cloth = make_sphere("Cloth", 0.97, location=(0.05, 0.0, 0.0), segments=32, rings=16)
  group = cloth.vertex_groups.new(name="Fit")
  group.add([v.index for v in cloth.data.vertices if v.co.z > -0.3], 0.8, 'REPLACE')
  bpy.context.view_layer.update()
  props = bpy.context.scene.amt_cloth_fit
  props.body_object = body
  props.clothing_object = cloth
  props.vertex_group = "Fit"
  props.shape_key_name = shape_key_name
  return cloth


def test_cloth_fit_rejects_basis_name_without_shape_keys():
  cloth = _setup_cloth_fit("Basis")
  try:
    assert_cancelled(bpy.ops.object.amt_cloth_fit, 'EXEC_DEFAULT')
  finally:
    bpy.context.scene.amt_cloth_fit.shape_key_name = "AMT_Fit"
  assert cloth.data.shape_keys is None


def _evaluated_coordinates(obj):
  depsgraph = bpy.context.evaluated_depsgraph_get()
  evaluated = obj.evaluated_get(depsgraph)
  mesh = evaluated.to_mesh()
  try:
    return [tuple(v.co) for v in mesh.vertices]
  finally:
    evaluated.to_mesh_clear()


def test_cloth_fit_reused_key_relative_to_other_key():
  cloth = _setup_cloth_fit()
  assert bpy.ops.object.amt_cloth_fit('EXEC_DEFAULT') == {'FINISHED'}
  bpy.context.view_layer.update()
  expected = _evaluated_coordinates(cloth)

  parent = cloth.shape_key_add(name="Parent", from_mix=False)
  for point in parent.data:
    point.co.x += 0.3
  parent.value = 0.0
  key_blocks = cloth.data.shape_keys.key_blocks
  key_blocks["AMT_Fit"].relative_key = parent

  assert bpy.ops.object.amt_cloth_fit('EXEC_DEFAULT') == {'FINISHED'}
  key_blocks = cloth.data.shape_keys.key_blocks
  assert key_blocks["AMT_Fit"].relative_key == key_blocks["Parent"]
  bpy.context.view_layer.update()
  actual = _evaluated_coordinates(cloth)
  worst = max(max(abs(a - b) for a, b in zip(p, q)) for p, q in zip(actual, expected))
  assert worst < 1e-5, worst


def test_hidden_mesh_analyze_restores_context():
  reset_scene()
  body = make_sphere("Body", 1.0)
  clothing = make_sphere("Clothing", 1.3)
  other = make_sphere("Other", 0.5, location=(5.0, 0.0, 0.0))
  make_active(other)
  bpy.ops.object.mode_set(mode='EDIT')

  NuniAvatarToolkit.run_hidden_mesh(body, [clothing], action='ANALYZE', ray_samples=8)
  assert bpy.context.mode == 'EDIT_MESH', bpy.context.mode
  assert bpy.context.view_layer.objects.active == other
  assert other.select_get() and not body.select_get()

  bpy.ops.object.mode_set(mode='OBJECT')
  make_active(clothing)
  NuniAvatarToolkit.run_hidden_mesh(body, [clothing], action='ANALYZE', ray_samples=8)
  assert bpy.context.mode == 'OBJECT'
  assert bpy.context.view_layer.objects.active == clothing
  assert clothing.select_get() and not body.select_get()

  for obj in bpy.context.selected_objects:
    obj.select_set(False)
  bpy.context.view_layer.objects.active = None
  NuniAvatarToolkit.run_hidden_mesh(body, [clothing], action='ANALYZE', ray_samples=8)
  assert bpy.context.view_layer.objects.active is None
  assert not bpy.context.selected_objects


TESTS = (
  test_cleanup_with_regular_modifiers,
  test_noop_shape_keys_respect_relative_key,
  test_cleanup_removes_loose_geometry,
  test_bone_follow_from_edit_mode,
  test_bone_follow_cancel_keeps_edit_mode,
  test_cloth_fit_rerun_keeps_key_settings,
  test_cloth_fit_rejects_basis_name_without_shape_keys,
  test_cloth_fit_reused_key_relative_to_other_key,
  test_hidden_mesh_analyze_restores_context,
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
    print("BLENDER_REVIEW_FIXES_FAILED: " + ", ".join(failures))
    sys.exit(1)
  print("BLENDER_REVIEW_FIXES_SMOKE_OK")


main()
