"""Blender background smoke test for integrated rigid bone weighting."""

import math
import sys
from pathlib import Path

import bpy


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

import NuniAvatarToolkit


def evaluated_vertex_positions(obj, vertex_indices):
  depsgraph = bpy.context.evaluated_depsgraph_get()
  evaluated = obj.evaluated_get(depsgraph)
  return [evaluated.matrix_world @ evaluated.data.vertices[index].co for index in vertex_indices]


bpy.ops.wm.read_factory_settings(use_empty=True)
NuniAvatarToolkit.register()

bpy.ops.object.armature_add(enter_editmode=False, location=(0.0, 0.0, 0.0))
armature = bpy.context.active_object
armature.name = "BoneWeightArmature"
armature.data.bones[0].name = "FollowBone"

bpy.ops.mesh.primitive_cube_add(location=(1.0, 2.0, 3.0))
target = bpy.context.active_object
target.name = "Accessory"

bpy.ops.mesh.primitive_cube_add(location=(5.0, 0.0, 0.0))
join_target = bpy.context.active_object
join_target.name = "AvatarMesh"
join_target.modifiers.new("Armature", 'ARMATURE').object = armature

props = bpy.context.scene.amt_bone_follow
props.target_object = target
props.armature_object = armature
props.bone_name = "FollowBone"
result = bpy.ops.object.amt_assign_rigid_bone_weight()

assert result == {'FINISHED'}
assert target.parent_type != 'BONE'
assert len(props.report_lines) == 3
armature_modifier = next(modifier for modifier in target.modifiers if modifier.type == 'ARMATURE')
assert armature_modifier.object == armature
group = target.vertex_groups["FollowBone"]
for vertex in target.data.vertices:
  membership = next(item for item in vertex.groups if item.group == group.index)
  assert abs(membership.weight - 1.0) < 1e-6

bpy.ops.object.select_all(action='DESELECT')
target.select_set(True)
join_target.select_set(True)
bpy.context.view_layer.objects.active = join_target
bpy.ops.object.join()

mesh_objects = [obj for obj in bpy.context.scene.objects if obj.type == 'MESH']
assert len(mesh_objects) == 1
assert mesh_objects[0] == join_target
group = join_target.vertex_groups["FollowBone"]
weighted_indices = [
  vertex.index for vertex in join_target.data.vertices
  if any(item.group == group.index and abs(item.weight - 1.0) < 1e-6 for item in vertex.groups)
]
assert len(weighted_indices) == 8

positions_before_pose = evaluated_vertex_positions(join_target, weighted_indices)
pose_bone = armature.pose.bones["FollowBone"]
pose_bone.rotation_mode = 'XYZ'
pose_bone.rotation_euler.z = math.radians(30.0)
bpy.context.view_layer.update()
positions_after_pose = evaluated_vertex_positions(join_target, weighted_indices)

assert any(
  (after - before).length > 1e-4
  for before, after in zip(positions_before_pose, positions_after_pose)
)

NuniAvatarToolkit.unregister()
print("Integrated rigid bone weighting smoke test passed")
