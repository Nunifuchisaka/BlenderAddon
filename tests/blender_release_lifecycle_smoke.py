"""Install/update real add-on ZIPs in an isolated Blender user directory.

Run with Blender --background --factory-startup --python-exit-code 1 --python
tests/blender_release_lifecycle_smoke.py. Source fixtures and preferences live
only in a temporary directory; the repository and real user installation stay
untouched.
"""

import importlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile

import bpy


PACKAGE = "NuniAvatarToolkit"
WORKER_FLAG = "--amt-release-worker"
SCENE_PROPERTIES = {
    "amt_armature_align", "amt_bone_follow", "amt_cleanup", "amt_cloth_fit",
    "amt_diagnostics", "amt_hidden_mesh", "amt_poke_through", "amt_texture_relink",
}
UPDATED_CATEGORY = "AMT Release Smoke Updated"
UPDATED_LABEL = "AMT Updated Cleanup Scan"


def _zip_package(package_dir, archive):
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as result:
        for source in sorted(package_dir.rglob("*")):
            if source.is_file():
                result.write(source, source.relative_to(package_dir.parent))


def _make_fixtures(directory):
    source = Path(__file__).resolve().parents[1] / PACKAGE
    original = directory / "initial" / PACKAGE
    shutil.copytree(
        source, original,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "texture_bake"),
    )
    helper = original / "core" / "ui.py"
    helper.write_text(helper.read_text(encoding="utf-8") + "\n\ndef release_smoke_helper():\n    return 'initial-helper'\n", encoding="utf-8")
    feature = original / "features" / "cleanup" / "operators.py"
    feature.write_text(
        feature.read_text(encoding="utf-8")
        + "\n\nfrom ...core.ui import release_smoke_helper\n"
        + "\ndef release_smoke_feature():\n    return release_smoke_helper() + ':initial-feature'\n",
        encoding="utf-8",
    )
    _zip_package(original, directory / "initial.zip")

    updated = directory / "updated" / PACKAGE
    shutil.copytree(original, updated)
    top = updated / "__init__.py"
    text = top.read_text(encoding="utf-8")
    match = re.search(r'"version"\s*:\s*\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\)', text)
    assert match is not None
    version = tuple(int(value) for value in match.groups())
    updated_version = (*version[:2], version[2] + 1)
    text = text[:match.start()] + f'"version": {updated_version}' + text[match.end():]
    # Same-second source timestamps must not accidentally retain an old .pyc.
    # Different size plus an explicit mtime change make top-level reload real.
    top.write_text(text + "\n# Isolated updated ZIP lifecycle fixture.\n", encoding="utf-8")

    helper = updated / "core" / "ui.py"
    helper.write_text(
        helper.read_text(encoding="utf-8")
        .replace('TOOLKIT_CATEGORY = "Avatar Toolkit"', f'TOOLKIT_CATEGORY = "{UPDATED_CATEGORY}"')
        .replace("initial-helper", "updated-helper-with-new-code"),
        encoding="utf-8",
    )
    feature = updated / "features" / "cleanup" / "operators.py"
    feature.write_text(
        feature.read_text(encoding="utf-8")
        .replace('bl_label = "スキャン"', f'bl_label = "{UPDATED_LABEL}"')
        .replace("initial-feature", "updated-feature-with-new-code"),
        encoding="utf-8",
    )
    _zip_package(updated, directory / "updated.zip")
    (directory / "versions.json").write_text(json.dumps([version, updated_version]), encoding="utf-8")


def _scene_properties():
    return {prop.identifier for prop in bpy.types.Scene.bl_rna.properties if prop.identifier.startswith("amt_")}


def _check_enabled():
    addon = sys.modules[PACKAGE]
    assert _scene_properties() == SCENE_PROPERTIES
    assert len(addon._modules) == 10
    assert PACKAGE + ".features.texture_bake" not in sys.modules
    report = addon.core_report
    for name in SCENE_PROPERTIES - {"amt_hidden_mesh"}:
        properties = getattr(bpy.context.scene, name)
        item = properties.report_lines.add()
        assert isinstance(item, report.AMT_ReportLine), name
        properties.report_lines.clear()
    return addon


def _check_disabled():
    assert _scene_properties() == set()
    assert not hasattr(bpy.types, "AMT_ReportLine")
    for identifier in ("amt_cleanup_scan", "amt_check_poke_through"):
        try:
            getattr(bpy.ops.object, identifier).get_rna_type()
        except (KeyError, RuntimeError):
            pass
        else:
            raise AssertionError(f"Operator remains registered: {identifier}")


def _worker(directory):
    original_version, updated_version = json.loads((directory / "versions.json").read_text(encoding="utf-8"))
    assert bpy.ops.preferences.addon_install(filepath=str(directory / "initial.zip"), overwrite=True) == {"FINISHED"}
    for cycle in range(3):
        assert bpy.ops.preferences.addon_enable(module=PACKAGE) == {"FINISHED"}
        addon = _check_enabled()
        assert addon.bl_info["version"] == tuple(original_version)
        assert bpy.ops.preferences.addon_disable(module=PACKAGE) == {"FINISHED"}
        _check_disabled()
        print("RELEASE_LIFECYCLE_CYCLE_OK", cycle)

    assert bpy.ops.preferences.addon_enable(module=PACKAGE) == {"FINISHED"}
    old_helper = sys.modules[PACKAGE + ".core.ui"]
    old_feature = sys.modules[PACKAGE + ".features.cleanup.operators"]
    old_report = sys.modules[PACKAGE + ".core.report"]
    assert old_feature.release_smoke_feature() == "initial-helper:initial-feature"
    assert bpy.ops.preferences.addon_install(filepath=str(directory / "updated.zip"), overwrite=True) == {"FINISHED"}
    # Guarantee Blender's timestamp-based reload independently of install speed.
    installed = Path(addon.__file__)
    stamp = max(installed.stat().st_mtime, getattr(addon, "__time__", 0)) + 2
    os.utime(installed, (stamp, stamp))
    importlib.invalidate_caches()
    assert bpy.ops.preferences.addon_enable(module=PACKAGE) == {"FINISHED"}
    addon = _check_enabled()
    helper = sys.modules[PACKAGE + ".core.ui"]
    feature = sys.modules[PACKAGE + ".features.cleanup.operators"]
    assert addon.bl_info["version"] == tuple(updated_version)
    assert helper is not old_helper and feature is not old_feature
    assert addon.core_report is not old_report
    assert helper.TOOLKIT_CATEGORY == UPDATED_CATEGORY
    assert feature.release_smoke_feature() == "updated-helper-with-new-code:updated-feature-with-new-code"
    assert bpy.ops.object.amt_cleanup_scan.get_rna_type().name == UPDATED_LABEL
    assert sys.modules[PACKAGE + ".features.cleanup.panel"].VIEW3D_PT_amt_cleanup.bl_category == UPDATED_CATEGORY
    print("RELEASE_UPDATED_CHILD_CODE_OK", addon.bl_info["version"])

    # Direct Python reload must remove previous RNA classes before reconstruction.
    previous_report = addon.core_report
    addon = importlib.reload(addon)
    _check_disabled()
    addon.register()
    _check_enabled()
    assert addon.core_report is not previous_report
    assert bpy.ops.preferences.addon_disable(module=PACKAGE) == {"FINISHED"}
    _check_disabled()
    print("BLENDER_RELEASE_LIFECYCLE_SMOKE_OK", bpy.app.version_string)


def main():
    with tempfile.TemporaryDirectory(prefix="amt-release-lifecycle-") as temporary:
        directory = Path(temporary)
        _make_fixtures(directory)
        environment = os.environ.copy()
        environment["BLENDER_USER_CONFIG"] = str(directory / "config")
        environment["BLENDER_USER_SCRIPTS"] = str(directory / "scripts")
        environment["BLENDER_USER_EXTENSIONS"] = str(directory / "extensions")
        result = subprocess.run(
            [bpy.app.binary_path, "--background", "--factory-startup", "--threads", "2",
             "--python-exit-code", "1", "--python", str(Path(__file__).resolve()),
             "--", WORKER_FLAG, str(directory)],
            env=environment, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, timeout=120,
        )
        print(result.stdout, end="")
        assert result.returncode == 0, f"Isolated release lifecycle failed: {result.returncode}"
        assert "BLENDER_RELEASE_LIFECYCLE_SMOKE_OK" in result.stdout


if WORKER_FLAG in sys.argv:
    _worker(Path(sys.argv[sys.argv.index(WORKER_FLAG) + 1]))
else:
    main()
