import importlib.util
import sys
import tempfile
import types
import unittest
from unittest import mock
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

  def test_modifiers_without_id_property_support_are_skipped(self):
    def raise_type_error():
      raise TypeError("bpy_struct.items(): this type doesn't support IDProperties")

    modifier = types.SimpleNamespace(
      name='Armature',
      bl_rna=types.SimpleNamespace(properties=[]),
      items=raise_type_error,
    )
    uv_layers = NamedList([
      types.SimpleNamespace(name='UVMap', active_render=True),
      types.SimpleNamespace(name='UnusedUV', active_render=False),
    ])
    uv_layers.active = uv_layers[0]
    obj = types.SimpleNamespace(
      data=types.SimpleNamespace(materials=[], uv_layers=uv_layers),
      modifiers=[modifier],
    )

    self.assertEqual(self.utils.find_unused_uv_maps(obj), ['UnusedUV'])


class TextureRelinkSafetyTests(unittest.TestCase):
  @classmethod
  def setUpClass(cls):
    bpy = types.ModuleType('bpy')
    bpy.path = types.SimpleNamespace(abspath=lambda path, library=None: path)
    bpy.data = types.SimpleNamespace(images=types.SimpleNamespace(
      load=mock.Mock(return_value=types.SimpleNamespace(size=(2, 2), has_data=True)),
      remove=mock.Mock(),
    ))
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
        library=None,
        reload=lambda: self.fail('partial match must not reload the image'),
      )

      result = self.utils.relink_missing_textures([image], directory)

    self.assertEqual(result['relinked'], [])
    self.assertEqual(len(result['ambiguous']), 1)

  def _missing_image(self, directory, name, **extra):
    values = dict(
      name=name, source='FILE', packed_file=None, library=None,
      filepath=str(Path(directory, 'missing', name)), reload=lambda: None,
      size=(2, 2), has_data=True,
    )
    values.update(extra)
    return types.SimpleNamespace(**values)

  def test_linked_images_are_reported_but_not_changed(self):
    with tempfile.TemporaryDirectory() as directory:
      Path(directory, 'Body.png').touch()
      image = self._missing_image(directory, 'Body.png', library=object())
      old_path = image.filepath

      result = self.utils.relink_missing_textures([image], directory)

    self.assertEqual(result['linked'], [image])
    self.assertEqual(result['relinked'], [])
    self.assertEqual(image.filepath, old_path)

  def test_failed_reload_is_rolled_back_and_batch_continues(self):
    def broken_reload():
      raise RuntimeError('cannot reload')

    with tempfile.TemporaryDirectory() as directory:
      Path(directory, 'Broken.png').touch()
      Path(directory, 'Good.png').touch()
      broken = self._missing_image(directory, 'Broken.png', reload=broken_reload)
      good = self._missing_image(directory, 'Good.png')
      old_path = broken.filepath

      result = self.utils.relink_missing_textures([broken, good], directory)

    self.assertEqual(broken.filepath, old_path)
    self.assertEqual([image for image, _ in result['failed']], [broken])
    self.assertEqual([image for image, _ in result['relinked']], [good])

  def test_webp_files_are_candidates(self):
    with tempfile.TemporaryDirectory() as directory:
      Path(directory, 'Skin.webp').touch()
      self.assertEqual(len(self.utils.find_candidate_files(directory)), 1)

  def test_decoder_failure_does_not_touch_original_and_removes_probe(self):
    undecoded = types.SimpleNamespace(size=(0, 0), has_data=False)
    with tempfile.TemporaryDirectory() as directory:
      Path(directory, 'Broken.png').touch()
      image = self._missing_image(directory, 'Broken.png', reload=mock.Mock())
      old_path = image.filepath
      with mock.patch.object(self.utils.bpy.data.images, 'load', return_value=undecoded) as load:
        with mock.patch.object(self.utils.bpy.data.images, 'remove') as remove:
          result = self.utils.relink_missing_textures([image], directory)
    self.assertEqual(image.filepath, old_path)
    image.reload.assert_not_called()
    self.assertEqual(result['relinked'], [])
    self.assertEqual([entry[0] for entry in result['failed']], [image])
    load.assert_called_once_with(str(Path(directory, 'Broken.png')), check_existing=False)
    remove.assert_called_once_with(undecoded)

  def test_reload_without_exception_but_without_pixels_is_rolled_back(self):
    with tempfile.TemporaryDirectory() as directory:
      Path(directory, 'Broken.png').touch()
      image = self._missing_image(directory, 'Broken.png', size=(0, 0), has_data=False)
      old_path = image.filepath
      result = self.utils.relink_missing_textures([image], directory)
    self.assertEqual(image.filepath, old_path)
    self.assertEqual(result['relinked'], [])
    self.assertEqual([entry[0] for entry in result['failed']], [image])


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

  def test_delta_rotation_and_scale_are_checked(self):
    delta_euler = types.SimpleNamespace(
      rotation_mode='XYZ', rotation_euler=(0.0, 0.0, 0.0), delta_rotation_euler=(0.0, 0.2, 0.0),
    )
    delta_quaternion = types.SimpleNamespace(
      rotation_mode='QUATERNION', rotation_quaternion=(1.0, 0.0, 0.0, 0.0),
      delta_rotation_quaternion=(0.9238795, 0.0, 0.3826834, 0.0),
    )
    delta_scale = types.SimpleNamespace(scale=(1.0, 1.0, 1.0), delta_scale=(1.0, 2.0, 1.0))
    negative_delta = types.SimpleNamespace(scale=(1.0, 1.0, 1.0), delta_scale=(-1.0, -1.0, -1.0))

    self.assertTrue(self.utils.has_unapplied_rotation(delta_euler))
    self.assertTrue(self.utils.has_unapplied_rotation(delta_quaternion))
    self.assertEqual(self.utils.has_non_uniform_or_negative_scale(delta_scale), (False, True))
    self.assertEqual(self.utils.has_non_uniform_or_negative_scale(negative_delta), (True, False))

  def test_ranks_are_reported_per_platform(self):
    self.assertEqual(self.utils.platform_ranks(25000, 'triangles'), "PC: Excellent / Quest: Very Poor")
    self.assertEqual(self.utils.platform_ranks(5856, 'triangles'), "PC: Excellent / Quest: Excellent")
    self.assertEqual(self.utils.platform_ranks(70001, 'triangles'), "PC: Very Poor / Quest: Very Poor")
    self.assertEqual(self.utils.platform_ranks(2, 'material_slots'), "PC: Excellent / Quest: Medium")
    self.assertEqual(self.utils.platform_ranks(120, 'bones'), "PC: Good / Quest: Medium")

  def test_material_slots_count_every_slot(self):
    material = object()
    meshes = [
      types.SimpleNamespace(material_slots=[types.SimpleNamespace(material=material)] * 20),
      types.SimpleNamespace(material_slots=[types.SimpleNamespace(material=None)]),
    ]
    self.assertEqual(self.utils.count_material_slots(meshes), 21)


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
