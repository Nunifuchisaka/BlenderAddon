bl_info = {
    "name": "NuniAvatarToolkit",
    "author": "Nunifuchisaka",
    "version": (1, 4, 0),
    "blender": (3, 6, 0),
    "location": "3Dビューポート > サイドバー(Nキー) > Avatar Toolkit",
    "description": "VRChat/VRMアバター向けの制作支援ツール集(メッシュ最適化・統合用ボーンウェイト・アーマチュア位置合わせ・診断)",
    "category": "Mesh",
    "doc_url": "",
    "tracker_url": "",
}

from .core import report as core_report
from .features import armature_align, bone_follow, cleanup, diagnostics, hidden_mesh, merge, texture_relink
from .features.hidden_mesh.api import run as run_hidden_mesh

# texture_bake は一時的に無効化中(後のバージョンで再開予定)。
# 再開するときは features/texture_bake/ をそのまま使えるので、上の import と下の _modules へ texture_bake を戻す。
# core_report must register first: feature modules declare CollectionProperty(type=AMT_ReportLine).
_modules = (core_report, hidden_mesh, cleanup, merge, diagnostics, texture_relink, armature_align, bone_follow)


def register():
    for module in _modules:
        module.register()


def unregister():
    for module in reversed(_modules):
        module.unregister()
