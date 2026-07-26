"""Run with Blender in background mode to verify the public hidden-mesh interface."""

import sys
from pathlib import Path

import bmesh
import bpy


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

import NuniAvatarToolkit


def create_cube(name, size):
  mesh = bpy.data.meshes.new(f"{name}Mesh")
  bm = bmesh.new()
  bmesh.ops.create_cube(bm, size=size)
  bm.to_mesh(mesh)
  bm.free()
  mesh.update()

  obj = bpy.data.objects.new(name, mesh)
  bpy.context.scene.collection.objects.link(obj)
  return obj


def main():
  NuniAvatarToolkit.register()
  try:
    body = create_cube("Body", 1.0)
    clothing = create_cube("Clothing", 2.0)

    analysis = NuniAvatarToolkit.run_hidden_mesh(
      body,
      [clothing],
      action='ANALYZE',
      ray_samples=8,
      safety_margin='MEDIUM',
    )
    assert analysis['hidden_face_count'] == 6, analysis

    deleted = NuniAvatarToolkit.run_hidden_mesh(
      body,
      [clothing],
      action='DELETE',
      ray_samples=8,
      safety_margin='NONE',
    )
    assert deleted['deleted_face_count'] == 6, deleted
    bpy.ops.object.mode_set(mode='OBJECT')
    assert len(body.data.polygons) == 0

    backup = bpy.data.objects[deleted['backup_object']]
    assert backup.data is not body.data
    assert len(backup.data.polygons) == 6
    assert backup.name in bpy.data.collections['AMT_Backups'].objects
    print("BLENDER_HIDDEN_MESH_SMOKE_OK")
  finally:
    NuniAvatarToolkit.unregister()


main()
