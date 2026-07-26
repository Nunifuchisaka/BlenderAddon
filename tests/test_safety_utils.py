import importlib.util
import sys
import tempfile
import types
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def load_module(name, relative_path, stubs):
  previous = {}
  for module_name, module in stubs.items():
    previous[module_name] = sys.modules.get(module_name)
    sys.modules[module_name] = module
  try:
    spec = importlib.util.spec_from_file_location(name, REPO_ROOT / relative_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
  finally:
    for module_name, module in previous.items():
      if module is None:
        sys.modules.pop(module_name, None)
      else:
        sys.modules[module_name] = module


class NamedList(list):
  active = None
  active_color = None
  render_color_index = -1


class CleanupSafetyTests(unittest.TestCase):
  @classmethod
  def setUpClass(cls):
    cls.utils = load_module(
      'cleanup_utils_for_test',
      'NuniAvatarToolkit/features/cleanup/utils.py',
      {'bmesh': types.ModuleType('bmesh')},
    )

  def test_preserves_nested_material_and_modifier_attribute_references(self):
    nested_tree = types.SimpleNamespace(nodes=[
      types.SimpleNamespace(type='ATTRIBUTE', attribute_name='DetailUV'),
      types.SimpleNamespace(type='VERTEX_COLOR', layer_name='Tint'),
    ])
    root_tree = types.SimpleNamespace(nodes=[
      types.SimpleNamespace(type='GROUP', node_tree=nested_tree),
    ])
    material = types.SimpleNamespace(use_nodes=True, node_tree=root_tree)

    modifier_property = types.SimpleNamespace(type='STRING', identifier='uv_layer')
    modifier = types.SimpleNamespace(
      name='UV Warp',
      uv_layer='ModifierUV',
      node_group=types.SimpleNamespace(nodes=[
        types.SimpleNamespace(
          type='INPUT_NAMED_ATTRIBUTE',
          inputs=[types.SimpleNamespace(default_value='GeometryNodesUV')],
        ),
      ]),
      bl_rna=types.SimpleNamespace(properties=[modifier_property]),
      items=lambda: (),
    )

    uv_layers = NamedList([
      types.SimpleNamespace(name='ActiveUV', active_render=False),
      types.SimpleNamespace(name='RenderUV', active_render=True),
      types.SimpleNamespace(name='DetailUV', active_render=False),
      types.SimpleNamespace(name='ModifierUV', active_render=False),
      types.SimpleNamespace(name='GeometryNodesUV', active_render=False),
      types.SimpleNamespace(name='UnusedUV', active_render=False),
    ])
    uv_layers.active = uv_layers[0]

    color_attributes = NamedList([
      types.SimpleNamespace(name='Tint'),
      types.SimpleNamespace(name='UnusedColor'),
    ])
    obj = types.SimpleNamespace(
      data=types.SimpleNamespace(
        materials=[material],
        uv_layers=uv_layers,
        color_attributes=color_attributes,
      ),
      modifiers=[modifier],
    )

    self.assertEqual(self.utils.find_unused_uv_maps(obj), ['UnusedUV'])
    self.assertEqual(self.utils.find_unused_color_attributes(obj), ['UnusedColor'])


class TextureRelinkSafetyTests(unittest.TestCase):
  @classmethod
  def setUpClass(cls):
    bpy = types.ModuleType('bpy')
    bpy.path = types.SimpleNamespace(abspath=lambda path: path)
    cls.utils = load_module(
      'texture_relink_utils_for_test',
      'NuniAvatarToolkit/features/texture_relink/utils.py',
      {'bpy': bpy},
    )

  def test_partial_match_is_not_applied_automatically(self):
    with tempfile.TemporaryDirectory() as directory:
      Path(directory, 'Body_normal.png').touch()
      image = types.SimpleNamespace(
        name='Body.png',
        source='FILE',
        packed_file=None,
        filepath=str(Path(directory, 'missing', 'Body.png')),
        reload=lambda: self.fail('partial match must not reload the image'),
      )

      result = self.utils.relink_missing_textures([image], directory)

    self.assertEqual(result['relinked'], [])
    self.assertEqual(len(result['ambiguous']), 1)


class DiagnosticsRotationTests(unittest.TestCase):
  @classmethod
  def setUpClass(cls):
    cls.utils = load_module(
      'diagnostics_utils_for_test',
      'NuniAvatarToolkit/features/diagnostics/utils.py',
      {'bmesh': types.ModuleType('bmesh')},
    )

  def test_rotation_modes(self):
    quaternion = types.SimpleNamespace(
      rotation_mode='QUATERNION',
      rotation_quaternion=(0.9238795, 0.0, 0.3826834, 0.0),
    )
    quaternion_identity = types.SimpleNamespace(
      rotation_mode='QUATERNION',
      rotation_quaternion=(-1.0, 0.0, 0.0, 0.0),
    )
    axis_angle = types.SimpleNamespace(
      rotation_mode='AXIS_ANGLE',
      rotation_axis_angle=(0.25, 0.0, 0.0, 1.0),
    )
    euler = types.SimpleNamespace(
      rotation_mode='XYZ',
      rotation_euler=(0.0, 0.0, 0.1),
    )

    self.assertTrue(self.utils.has_unapplied_rotation(quaternion))
    self.assertFalse(self.utils.has_unapplied_rotation(quaternion_identity))
    self.assertTrue(self.utils.has_unapplied_rotation(axis_angle))
    self.assertTrue(self.utils.has_unapplied_rotation(euler))


class HiddenMeshSafetyMarginTests(unittest.TestCase):
  @classmethod
  def setUpClass(cls):
    mathutils = types.ModuleType('mathutils')
    mathutils.Vector = object
    cls.utils = load_module(
      'hidden_mesh_utils_for_test',
      'NuniAvatarToolkit/features/hidden_mesh/utils.py',
      {'mathutils': mathutils},
    )

  def test_insets_hidden_faces_by_shared_edge_rings(self):
    polygons = []
    for index in range(5):
      polygons.append(types.SimpleNamespace(edge_keys=[
        (index, 100 + index),
        (index + 1, 101 + index),
        (200 + index, 300 + index),
        (400 + index, 500 + index),
      ]))
    mesh = types.SimpleNamespace(polygons=polygons)
    hidden = [False, True, True, True, False]

    none = self.utils.inset_hidden_face_mask(mesh, hidden, 'NONE')
    small = self.utils.inset_hidden_face_mask(mesh, hidden, 'SMALL')
    medium = self.utils.inset_hidden_face_mask(mesh, hidden, 'MEDIUM')

    self.assertEqual(none.tolist(), [False, True, True, True, False])
    self.assertEqual(small.tolist(), [False, False, True, False, False])
    self.assertEqual(medium.tolist(), [False, False, False, False, False])


if __name__ == '__main__':
  unittest.main()
