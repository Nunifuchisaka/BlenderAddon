bl_info = {
    "name": "Nuni Avatar Toolkit for Blender",
    "author": "Nunifuchisaka",
    "version": (1, 0, 0),
    "blender": (4, 2, 0),
    "location": "3Dビューポート > サイドバー(Nキー) > Avatar Toolkit",
    "description": "VRChat/VRMアバター向けの制作支援ツール集(隠れメッシュ削除・服フィット・貫通チェック・統合・診断など)",
    "category": "Mesh",
    "doc_url": "https://nunifuchisaka.github.io/nuniavatartoolkit/",
    "tracker_url": "",
}

import importlib
import sys

# Blender reloads only the top package when an installed ZIP changes. Rebuild
# every child module so helpers and copied class/function imports also update.
# Normal add-on updates unregister first; a direct Python reload may not.
if "_modules" in globals():
    if globals().get("_registered", False):
        unregister()
    for _name in tuple(sys.modules):
        if _name.startswith(__name__ + "."):
            del sys.modules[_name]
    importlib.invalidate_caches()

from .core import report as core_report
from .features import (
    armature_align, bone_follow, cleanup, cloth_fit, diagnostics, hidden_mesh, merge,
    poke_through, texture_relink,
)
from .features.hidden_mesh.api import run as run_hidden_mesh

# texture_bake は一時的に無効化中(後のバージョンで再開予定)。
# 再開するときは features/texture_bake/ をそのまま使えるので、上の import と下の _modules へ texture_bake を戻す。
# core_report must register first: feature modules declare CollectionProperty(type=AMT_ReportLine).
_modules = (
    core_report, hidden_mesh, cleanup, merge, diagnostics, texture_relink, armature_align,
    bone_follow, cloth_fit, poke_through,
)
_registered = False


def register():
    global _registered
    if _registered:
        return
    for module in _modules:
        module.register()
    _registered = True


def unregister():
    global _registered
    if not _registered:
        return
    for module in reversed(_modules):
        module.unregister()
    _registered = False
