bl_info = {
    "name": "NuniAvatarToolkit",
    "author": "Nunifuchisaka",
    "version": (1, 2, 0),
    "blender": (3, 6, 0),
    "location": "3Dビューポート > サイドバー(Nキー) > Avatar Toolkit",
    "description": "VRChat/VRMアバター向けのメッシュ最適化ツール集(隠れメッシュ削除・テクスチャベイク・テクスチャ再リンク・不要データ削除・統合・診断)",
    "category": "Mesh",
    "doc_url": "",
    "tracker_url": "",
}

from .core import report as core_report
from .features import cleanup, diagnostics, hidden_mesh, merge, texture_bake, texture_relink

# core_report must register first: feature modules declare CollectionProperty(type=AMT_ReportLine).
_modules = (core_report, hidden_mesh, texture_bake, cleanup, merge, diagnostics, texture_relink)


def register():
    for module in _modules:
        module.register()


def unregister():
    for module in reversed(_modules):
        module.unregister()
