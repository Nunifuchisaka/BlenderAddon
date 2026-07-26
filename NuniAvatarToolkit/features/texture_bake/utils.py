"""Bake-proxy construction and Cycles self-bake mechanics for the texture_bake feature.

Unlike the other features' utils.py modules, this one necessarily calls bpy.data/bpy.ops
(creating temporary objects/materials and running the bake operator is the whole point) -
but it still defines no bpy.types classes, so it needs no register()/unregister().
"""

import bmesh
import bpy
import numpy as np


def duplicate_source_for_bake(context, source_obj, material_slot_index, name="AMT_BakeProxy"):
    """Duplicates source_obj's mesh, keeps only the faces using material_slot_index, and gives
    the proxy a single-user copy of that one material (so baking never mutates the user's
    original data). Returns (proxy_obj, proxy_material, original_uv_layer_name).
    Raises ValueError with a Japanese message for any precondition that isn't met.
    """
    if not (0 <= material_slot_index < len(source_obj.material_slots)):
        raise ValueError("ベイク元マテリアルスロットの指定が範囲外です")
    original_material = source_obj.material_slots[material_slot_index].material
    if original_material is None or original_material.node_tree is None:
        raise ValueError("選択したマテリアルスロットにノードベースのマテリアルが設定されていません")
    if not any(poly.material_index == material_slot_index for poly in source_obj.data.polygons):
        raise ValueError("ベイク元メッシュに、指定したマテリアルスロットを使用している面がありません")
    if source_obj.data.uv_layers.active is None:
        raise ValueError("ベイク元メッシュにUVマップがありません")

    mesh_copy = None
    proxy_obj = None
    proxy_material = None
    try:
        mesh_copy = source_obj.data.copy()
        proxy_obj = bpy.data.objects.new(name, mesh_copy)
        proxy_obj.matrix_world = source_obj.matrix_world.copy()
        context.scene.collection.objects.link(proxy_obj)

        bm = bmesh.new()
        try:
            bm.from_mesh(mesh_copy)
            bm.faces.ensure_lookup_table()
            faces_to_delete = [f for f in bm.faces if f.material_index != material_slot_index]
            bmesh.ops.delete(bm, geom=faces_to_delete, context='FACES')
            for f in bm.faces:
                f.material_index = 0
            bm.to_mesh(mesh_copy)
        finally:
            bm.free()

        proxy_material = original_material.copy()
        mesh_copy.materials.clear()
        mesh_copy.materials.append(proxy_material)
        return proxy_obj, proxy_material, mesh_copy.uv_layers.active.name
    except Exception:
        _remove_proxy_data(proxy_obj, mesh_copy, proxy_material)
        raise


def compute_uv_bbox(mesh, uv_layer_name):
    uv_layer = mesh.uv_layers[uv_layer_name]
    n = len(uv_layer.data)
    coords = np.empty(n * 2, dtype=np.float64)
    uv_layer.data.foreach_get('uv', coords)
    coords = coords.reshape(n, 2)
    return (
        float(coords[:, 0].min()), float(coords[:, 1].min()),
        float(coords[:, 0].max()), float(coords[:, 1].max()),
    )


def remap_uv_layer(mesh, uv_layer_name, src_bbox, dst_rect, fit_mode='UNIFORM'):
    """Applies one rigid affine transform (scale + offset) mapping src_bbox onto dst_rect,
    to every UV coordinate in uv_layer_name. UNIFORM preserves aspect ratio (letterboxed
    within dst_rect); STRETCH fills dst_rect exactly, distorting if aspect ratios differ.
    """
    src_min_u, src_min_v, src_max_u, src_max_v = src_bbox
    dst_min_u, dst_min_v, dst_max_u, dst_max_v = dst_rect

    src_w = max(src_max_u - src_min_u, 1e-9)
    src_h = max(src_max_v - src_min_v, 1e-9)
    dst_w = max(dst_max_u - dst_min_u, 1e-9)
    dst_h = max(dst_max_v - dst_min_v, 1e-9)

    if fit_mode == 'UNIFORM':
        scale_u = scale_v = min(dst_w / src_w, dst_h / src_h)
    else:
        scale_u = dst_w / src_w
        scale_v = dst_h / src_h

    offset_u = dst_min_u + (dst_w - src_w * scale_u) * 0.5
    offset_v = dst_min_v + (dst_h - src_h * scale_v) * 0.5

    uv_layer = mesh.uv_layers[uv_layer_name]
    n = len(uv_layer.data)
    coords = np.empty(n * 2, dtype=np.float64)
    uv_layer.data.foreach_get('uv', coords)
    coords = coords.reshape(n, 2)

    coords[:, 0] = (coords[:, 0] - src_min_u) * scale_u + offset_u
    coords[:, 1] = (coords[:, 1] - src_min_v) * scale_v + offset_v

    uv_layer.data.foreach_set('uv', coords.reshape(-1))
    mesh.update()


def ensure_uv_map_node_for_shading(material, uv_layer_name):
    """Pins every currently-unconnected Image Texture node's Vector input to uv_layer_name,
    so shading keeps using the proxy's original UVs regardless of which layer is "active"
    (which the bake step changes) or of Blender's implicit-active-UV shading default.
    """
    node_tree = material.node_tree
    image_nodes = [n for n in node_tree.nodes if n.type == 'TEX_IMAGE']
    unconnected = [n for n in image_nodes if not n.inputs['Vector'].is_linked]
    if not unconnected:
        return
    uv_node = node_tree.nodes.new('ShaderNodeUVMap')
    uv_node.uv_map = uv_layer_name
    uv_node.location = (-400, 0)
    for n in unconnected:
        node_tree.links.new(uv_node.outputs['UV'], n.inputs['Vector'])


def add_bake_target_node(material, image):
    node_tree = material.node_tree
    for n in node_tree.nodes:
        n.select = False
    bake_node = node_tree.nodes.new('ShaderNodeTexImage')
    bake_node.image = image
    bake_node.select = True
    bake_node.location = (0, 300)
    node_tree.nodes.active = bake_node
    return bake_node


def run_self_bake(context, proxy_obj, uv_layer_name, bake_type, margin_px, samples):
    """Bakes proxy_obj onto itself (no selected-to-active) using uv_layer_name as the
    rasterization layout, into whichever image is on the node_tree.nodes.active Image Texture
    node of the proxy's (single) material. Temporarily forces Cycles - baking to an image is
    Cycles-only in Blender - restoring the scene's original engine/samples/active-UV in
    finally regardless of success or failure.
    """
    scene = context.scene
    original_engine = scene.render.engine
    original_samples = getattr(getattr(scene, 'cycles', None), 'samples', None)
    original_active_uv = proxy_obj.data.uv_layers.active

    for obj in context.selected_objects:
        obj.select_set(False)
    proxy_obj.select_set(True)
    context.view_layer.objects.active = proxy_obj

    try:
        scene.render.engine = 'CYCLES'
        if original_samples is not None:
            scene.cycles.samples = samples
        proxy_obj.data.uv_layers.active = proxy_obj.data.uv_layers[uv_layer_name]

        bake_kwargs = dict(
            type=bake_type,
            use_selected_to_active=False,
            margin=margin_px,
            margin_type='EXTEND',
            use_clear=False,
        )
        if bake_type == 'DIFFUSE':
            bake_kwargs['pass_filter'] = {'COLOR'}

        result = bpy.ops.object.bake(**bake_kwargs)
        if 'FINISHED' not in result:
            raise RuntimeError(f"ベイクに失敗しました({bake_type}): {result}")
    finally:
        scene.render.engine = original_engine
        if original_samples is not None:
            scene.cycles.samples = original_samples
        if original_active_uv is not None:
            proxy_obj.data.uv_layers.active = original_active_uv


def _remove_proxy_data(proxy_obj, mesh=None, material=None):
  if proxy_obj is not None:
    mesh = proxy_obj.data
    materials = list(mesh.materials)
    if material is not None and material not in materials:
      materials.append(material)
    bpy.data.objects.remove(proxy_obj, do_unlink=True)
  else:
    materials = [material] if material is not None else []
  if mesh is not None and mesh.users == 0:
    bpy.data.meshes.remove(mesh)
  for mat in materials:
    if mat is not None and mat.users == 0:
      bpy.data.materials.remove(mat)


def cleanup_proxy(proxy_obj):
  if proxy_obj is not None:
    _remove_proxy_data(proxy_obj)
