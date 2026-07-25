import os
import sys
import traceback

import addon_utils
import bpy

bl_info = {
    "name": "Nuni Dev Reload",
    "author": "Nunifuchisaka",
    "version": (1, 0, 0),
    "blender": (3, 6, 0),
    "location": "N/A (バックグラウンドタイマーのみ、UIは持たない)",
    "description": "NuniAvatarToolkit開発用: ソースファイルの変更を検知して自動的にリロードする",
    "category": "Development",
    "doc_url": "",
    "tracker_url": "",
}

WATCH_PACKAGE = "NuniAvatarToolkit"
POLL_INTERVAL = 1.0

_last_signature = None


def _watch_dir():
    # Assumes NuniAvatarToolkit is a sibling folder in the same addons directory as this module.
    # If the directory layout changes, _compute_signature will always return None and watching will silently stop.
    addons_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(addons_dir, WATCH_PACKAGE)


def _compute_signature(path):
    if not os.path.isdir(path):
        return None
    latest_mtime = 0.0
    file_count = 0
    for root, _dirs, files in os.walk(path):
        for name in files:
            if not name.endswith(".py"):
                continue
            file_count += 1
            full_path = os.path.join(root, name)
            try:
                mtime = os.path.getmtime(full_path)
            except OSError:
                continue
            if mtime > latest_mtime:
                latest_mtime = mtime
    return (latest_mtime, file_count)


def _reload_package():
    try:
        addon_utils.disable(WATCH_PACKAGE, default_set=False)
        for name in [n for n in list(sys.modules)
                     if n == WATCH_PACKAGE or n.startswith(WATCH_PACKAGE + ".")]:
            del sys.modules[name]
        result = addon_utils.enable(WATCH_PACKAGE, default_set=False)
        if result is not None:
            print("[nuni_dev_reload] reloaded " + WATCH_PACKAGE)
        else:
            print("[nuni_dev_reload] FAILED to reload " + WATCH_PACKAGE + " (see traceback above)")
    except Exception:
        traceback.print_exc()


def _poll():
    global _last_signature
    signature = _compute_signature(_watch_dir())
    if signature is not None and _last_signature is not None and signature != _last_signature:
        _reload_package()
    if signature is not None:
        _last_signature = signature
    return POLL_INTERVAL


def register():
    if not bpy.app.timers.is_registered(_poll):
        bpy.app.timers.register(_poll, first_interval=POLL_INTERVAL, persistent=True)


def unregister():
    if bpy.app.timers.is_registered(_poll):
        bpy.app.timers.unregister(_poll)
