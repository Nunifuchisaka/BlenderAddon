# 開発時の自動リロード環境 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** リポジトリ内の `NuniAvatarToolkit` コードを保存するだけで、起動中のBlenderに自動的に反映される開発環境を構築する。

**Architecture:** Blenderのアドオンフォルダの外（`%LOCALAPPDATA%\NuniAvatarToolkitDev\addons`）にジャンクション経由でリポジトリを繋ぎ、その専用ディレクトリをBlenderの追加スクリプトディレクトリとして登録する。監視用の小さなアドオン `nuni_dev_reload` が `bpy.app.timers` で1秒ごとにファイル変更を検知し、対象パッケージだけを `sys.modules` から落として再有効化する。セットアップ/後始末はPowerShellスクリプトで行う。

**Tech Stack:** Python (Blender 5.0/5.2 内蔵、`bpy`/`addon_utils`)、Windows PowerShell 5.1、Windowsジャンクション(`New-Item -ItemType Junction`)。

## Global Constraints

- 対象OSはWindowsのみ。PowerShellはWindows PowerShell 5.1構文を使う(`&&`/`||`/三項演算子は不可)。
- ジャンクション作成に管理者権限は不要(シンボリックリンクと異なる)。
- ジャンクションは `%LOCALAPPDATA%\NuniAvatarToolkitDev\addons` 配下に置く。リポジトリ内には置かない。
- Blenderに`script_directory_add`で登録する値は、その**親**である `%LOCALAPPDATA%\NuniAvatarToolkitDev` にする(`...\addons`ではない)。Blenderの`addon_utils.paths()`は登録した各スクリプトディレクトリに対して自動的に`addons`サブフォルダを付加して探索するため(`addon_utils.py`のソースおよび実機で確認済み)、`...\addons`自体を登録すると`...\addons\addons`を探しにいってしまい、アドオンが一切見つからない。
- 監視・リロード対象パッケージ名は定数 `WATCH_PACKAGE = "NuniAvatarToolkit"`。
- 監視間隔は定数 `POLL_INTERVAL = 1.0`(秒)。
- `tools/` 配下は配布ZIP(`NuniAvatarToolkit/` フォルダのみを圧縮)に含まれない。
- `bpy.ops.preferences.script_directory_add(directory=<path>)` で追加した要素は `bpy.context.preferences.filepaths.script_directories` に `.directory` プロパティを持つ項目として現れる(実機で確認済み)。
- `bpy.ops.preferences.script_directory_remove(index=<int>)` はインデックス指定で削除する(実機で確認済み)。
- Blender実行ファイルパス: `C:\Program Files\Blender Foundation\Blender <version>\blender.exe`(このリポジトリの開発機では `5.0` と `5.2` が確認済み)。
- 自動テストは無し(プロジェクト全体方針)。各タスクの検証はBlenderのheadless実行(`blender.exe --background --python <script>`)またはPowerShellでの状態確認で行う。

---

### Task 1: `nuni_dev_reload` 監視アドオンの実装

**Files:**
- Create: `tools/nuni_dev_reload/__init__.py`

**Interfaces:**
- Consumes: なし(このタスクは他タスクに依存しない)
- Produces:
  - `WATCH_PACKAGE: str = "NuniAvatarToolkit"` — Task 2/3のPowerShellスクリプトが有効化/無効化する対象アドオン名として参照する文字列
  - `register() -> None` / `unregister() -> None` — Blenderのアドオン登録関数(レガシー形式の慣習通り)
  - モジュール内部関数 `_compute_signature(path: str) -> tuple[float, int] | None`、`_poll() -> float`、`_reload_package() -> None`、`_watch_dir() -> str`(他タスクからは直接呼ばれないが、本タスクの検証で使う)

- [ ] **Step 1: `tools/nuni_dev_reload/__init__.py` を作成する**

```python
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
        addon_utils.enable(WATCH_PACKAGE, default_set=False)
        print("[nuni_dev_reload] reloaded " + WATCH_PACKAGE)
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
```

- [ ] **Step 2: 構文チェック**

Run: `python -m py_compile tools/nuni_dev_reload/__init__.py`
Expected: エラーなく終了する(出力なし)。

- [ ] **Step 3: Blender headlessでregister/unregisterと`_compute_signature`を検証する**

以下の内容で `tools/nuni_dev_reload/__init__.py` を直接importして検証する(この時点ではまだBlenderのアドオンフォルダには置かない。`tools/` を直接 `sys.path` に加えてパッケージとしてimportする)。

検証スクリプトを作成する:

```python
import os
import shutil
import sys
import tempfile

sys.path.insert(0, r"E:\git\BlenderAddon\tools")
import nuni_dev_reload as mod

import bpy

# register/unregisterがタイマーの登録状態を正しく切り替えること
assert not bpy.app.timers.is_registered(mod._poll), "初期状態でタイマーが登録されているのはおかしい"
mod.register()
assert bpy.app.timers.is_registered(mod._poll), "registerでタイマーが登録されていない"
mod.register()  # 二重呼び出しでも例外にならないこと(冪等性)
mod.unregister()
assert not bpy.app.timers.is_registered(mod._poll), "unregisterでタイマーが解除されていない"
mod.unregister()  # 二重呼び出しでも例外にならないこと

# _compute_signature: 存在しないパスはNone
assert mod._compute_signature(r"E:\git\BlenderAddon\__does_not_exist__") is None

# _compute_signature: 一時ディレクトリに.pyファイルを置いて件数・mtimeが変化を検知できること
tmp_dir = tempfile.mkdtemp(prefix="nuni_sig_test_")
try:
    file_a = os.path.join(tmp_dir, "a.py")
    with open(file_a, "w", encoding="utf-8") as f:
        f.write("x = 1\n")
    sig1 = mod._compute_signature(tmp_dir)
    assert sig1 is not None and sig1[1] == 1, f"1ファイル時点の件数が不正: {sig1}"

    file_b = os.path.join(tmp_dir, "b.py")
    with open(file_b, "w", encoding="utf-8") as f:
        f.write("y = 2\n")
    sig2 = mod._compute_signature(tmp_dir)
    assert sig2 is not None and sig2[1] == 2, f"2ファイル時点の件数が不正: {sig2}"
    assert sig2 != sig1, "ファイル追加でシグネチャが変化していない"

    os.remove(file_b)
    sig3 = mod._compute_signature(tmp_dir)
    assert sig3 is not None and sig3[1] == 1, f"削除後の件数が不正: {sig3}"
    assert sig3 != sig2, "ファイル削除でシグネチャが変化していない"
finally:
    shutil.rmtree(tmp_dir, ignore_errors=True)

print("TASK1_VERIFY_OK")
```

このスクリプトを `%TEMP%\task1-verify.py` として保存し、実行する。

Run: `& "C:\Program Files\Blender Foundation\Blender 5.2\blender.exe" --background --python "$env:TEMP\task1-verify.py"`
Expected: 標準出力の末尾に `TASK1_VERIFY_OK` が出力され、`AssertionError` 等の例外が発生しないこと。

- [ ] **Step 4: `_poll`の変更検知〜自動リロードを、実際の`NuniAvatarToolkit`を使ってエンドツーエンドで検証する**

`_watch_dir()`は「自分(`nuni_dev_reload`)と同じ`addons`ディレクトリ内の`NuniAvatarToolkit`」を見る設計なので、検証用に一時ディレクトリへ両方をジャンクションで並べて配置する。

検証スクリプトを作成する:

```python
import os
import subprocess
import sys

dev_addons = r"E:\git\BlenderAddon\.tmp-task1-addons"
if os.path.isdir(dev_addons):
    import shutil
    shutil.rmtree(dev_addons)
os.makedirs(dev_addons)

subprocess.run(
    ["cmd", "/c", "mklink", "/J", os.path.join(dev_addons, "NuniAvatarToolkit"),
     r"E:\git\BlenderAddon\NuniAvatarToolkit"],
    check=True, capture_output=True, text=True,
)
subprocess.run(
    ["cmd", "/c", "mklink", "/J", os.path.join(dev_addons, "nuni_dev_reload"),
     r"E:\git\BlenderAddon\tools\nuni_dev_reload"],
    check=True, capture_output=True, text=True,
)

sys.path.insert(0, dev_addons)
import nuni_dev_reload as mod

import bpy

# 初回poll: シグネチャを記録するだけでリロードは起きない
mod._last_signature = None
sig0 = mod._poll()
assert sig0 == mod.POLL_INTERVAL
first_sig = mod._last_signature
assert first_sig is not None, "NuniAvatarToolkitが検出できていない"

# panel.pyのmtimeを更新して変更を発生させる
target_file = r"E:\git\BlenderAddon\NuniAvatarToolkit\features\hidden_mesh\panel.py"
st = os.stat(target_file)
os.utime(target_file, (st.st_atime, st.st_mtime + 5))

sys.path_bpy_types_before = id(sys.modules.get("NuniAvatarToolkit"))

mod._poll()
sig_after = mod._last_signature
assert sig_after != first_sig, "mtime変更がシグネチャに反映されていない"

module_after = sys.modules.get("NuniAvatarToolkit")
assert module_after is not None, "リロード後にNuniAvatarToolkitがsys.modulesに存在しない"
assert id(module_after) != sys.path_bpy_types_before, "モジュールが再importされていない(オブジェクトIDが同じ)"

print("TASK1_E2E_VERIFY_OK")
```

このスクリプトを `%TEMP%\task1-e2e-verify.py` として保存し、実行する。

Run: `& "C:\Program Files\Blender Foundation\Blender 5.2\blender.exe" --background --python "$env:TEMP\task1-e2e-verify.py"`
Expected: 標準出力に `[nuni_dev_reload] reloaded NuniAvatarToolkit` と `TASK1_E2E_VERIFY_OK` が出力され、例外が発生しないこと。

- [ ] **Step 5: 構文エラー発生時に監視が止まらず、修正後に復帰することを検証する**

`_reload_package`が例外を握りつぶすことを、`hidden_mesh/panel.py`に一時的な構文エラーを仕込んで確認する(Step 4で作成した`.tmp-task1-addons`のジャンクションをまだ削除していない前提)。

検証スクリプトを作成する:

```python
import sys

dev_addons = r"E:\git\BlenderAddon\.tmp-task1-addons"
sys.path.insert(0, dev_addons)
import nuni_dev_reload as mod

import bpy

target_file = r"E:\git\BlenderAddon\NuniAvatarToolkit\features\hidden_mesh\panel.py"
with open(target_file, "r", encoding="utf-8") as f:
    original_content = f.read()

broken_content = original_content + "\ndef _broken_syntax(:\n    pass\n"

try:
    with open(target_file, "w", encoding="utf-8") as f:
        f.write(broken_content)

    # 例外を外に投げないこと(投げたらここでBlenderごと落ちてテストが失敗する)
    mod._reload_package()
    print("TASK1_SYNTAX_ERROR_HANDLED_OK")
finally:
    with open(target_file, "w", encoding="utf-8") as f:
        f.write(original_content)

# 修正後、再度リロードすれば正常に復帰すること
mod._reload_package()
assert hasattr(bpy.types, "VIEW3D_PT_amt_hidden_mesh"), "修正後の再リロードでパネルクラスが復帰していない"
print("TASK1_RECOVERY_OK")
```

このスクリプトを `%TEMP%\task1-syntax-error-verify.py` として保存し、実行する。

Run: `& "C:\Program Files\Blender Foundation\Blender 5.2\blender.exe" --background --python "$env:TEMP\task1-syntax-error-verify.py"`
Expected: 標準出力に Python のトレースバック(`SyntaxError`関連)が出力されたうえで、その後に `TASK1_SYNTAX_ERROR_HANDLED_OK` と `TASK1_RECOVERY_OK` が出力され、スクリプト自体はエラー終了しないこと(Blenderプロセスがクラッシュしないこと)。

- [ ] **Step 6: 検証用の一時ジャンクションを削除する**

Run: `Remove-Item "E:\git\BlenderAddon\.tmp-task1-addons" -Recurse -Force`
Expected: エラーなく削除される。`Get-ChildItem "E:\git\BlenderAddon\NuniAvatarToolkit"` を実行し、リポジトリ本体のファイルが無事に残っていることを目視確認する(ジャンクション越しの`rmtree`でリンク先が消えていないことの確認)。`git status` で `NuniAvatarToolkit/features/hidden_mesh/panel.py` に差分が残っていないことも確認する(Step 5で復元済みのはず)。

- [ ] **Step 7: Commit**

```bash
git add tools/nuni_dev_reload/__init__.py
git commit -m "Add nuni_dev_reload watcher addon for auto-reloading NuniAvatarToolkit"
```

---

### Task 2: `setup-dev-link.ps1` セットアップスクリプト

**Files:**
- Create: `tools/setup-dev-link.ps1`

**Interfaces:**
- Consumes: Task 1で作成した `tools/nuni_dev_reload/__init__.py`(ジャンクション経由でBlenderに登録する対象として参照するのみで、コードの中身には依存しない)
- Produces: 実行すると `%LOCALAPPDATA%\NuniAvatarToolkitDev\addons` 配下にジャンクションを作成し、Blenderの設定に登録する。戻り値はなし(スクリプト)。Task 3のテスト(setup→teardownの往復確認)から呼び出される。

- [ ] **Step 1: `tools/setup-dev-link.ps1` を作成する**

```powershell
[CmdletBinding()]
param(
    [string]$BlenderVersion = "5.2",
    [string]$RepoRoot = (Split-Path -Parent $PSScriptRoot)
)

$ErrorActionPreference = "Stop"

$blenderExe = "C:\Program Files\Blender Foundation\Blender $BlenderVersion\blender.exe"
if (-not (Test-Path $blenderExe)) {
    Write-Error "Blender $BlenderVersion が見つかりません: $blenderExe"
    exit 1
}

$devRoot = Join-Path $env:LOCALAPPDATA "NuniAvatarToolkitDev"
$devAddonsDir = Join-Path $devRoot "addons"
New-Item -ItemType Directory -Force -Path $devAddonsDir | Out-Null

$junctions = @(
    @{ Link = Join-Path $devAddonsDir "NuniAvatarToolkit"; Target = Join-Path $RepoRoot "NuniAvatarToolkit" },
    @{ Link = Join-Path $devAddonsDir "nuni_dev_reload"; Target = Join-Path $RepoRoot "tools\nuni_dev_reload" }
)

foreach ($j in $junctions) {
    if (-not (Test-Path $j.Target)) {
        Write-Error "リンク先が存在しません: $($j.Target)"
        exit 1
    }
    if (Test-Path $j.Link) {
        $item = Get-Item $j.Link
        if ($item.LinkType -eq "Junction") {
            Remove-Item $j.Link -Force -Recurse -Confirm:$false
        } else {
            Write-Error "$($j.Link) はジャンクションではない実体です。手動で確認してください。"
            exit 1
        }
    }
    New-Item -ItemType Junction -Path $j.Link -Target $j.Target | Out-Null
    Write-Output "junction作成: $($j.Link) -> $($j.Target)"
}

$blenderAddonsRoot = Join-Path $env:APPDATA "Blender Foundation\Blender\$BlenderVersion\scripts\addons"
$staleCopy = Join-Path $blenderAddonsRoot "NuniAvatarToolkit"
if (Test-Path $staleCopy) {
    $item = Get-Item $staleCopy
    if ($item.LinkType -eq "Junction" -or $item.LinkType -eq "SymbolicLink") {
        Remove-Item $staleCopy -Force -Recurse -Confirm:$false
        Write-Output "既存のリンクを削除しました: $staleCopy"
    } else {
        Remove-Item $staleCopy -Recurse -Force -Confirm:$false
        Write-Output "既存の実体コピーを削除しました: $staleCopy"
    }
}

$pyScript = @"
import bpy
import addon_utils

dev_dir = r'$devRoot'
existing = [d.directory for d in bpy.context.preferences.filepaths.script_directories]
if dev_dir not in existing:
    bpy.ops.preferences.script_directory_add(directory=dev_dir)
    print('script_directory_add: ' + dev_dir)
else:
    print('script_directory already registered: ' + dev_dir)

bpy.ops.preferences.addon_refresh()

addon_utils.enable('nuni_dev_reload', default_set=True)
addon_utils.enable('NuniAvatarToolkit', default_set=True)
print('addons enabled: nuni_dev_reload, NuniAvatarToolkit')

bpy.ops.wm.save_userpref()
print('userpref saved')
"@

$pyScriptPath = Join-Path $env:TEMP "nuni-setup-dev-link.py"
Set-Content -Path $pyScriptPath -Value $pyScript -Encoding utf8

& $blenderExe --background --python $pyScriptPath
if ($LASTEXITCODE -ne 0) {
    Write-Error "Blenderの起動に失敗しました (exit code $LASTEXITCODE)"
    exit 1
}

Write-Output ""
Write-Output "セットアップ完了。"
Write-Output "  $devAddonsDir\NuniAvatarToolkit -> $RepoRoot\NuniAvatarToolkit"
Write-Output "  $devAddonsDir\nuni_dev_reload -> $RepoRoot\tools\nuni_dev_reload"
Write-Output "Blenderを起動すれば、コードを保存するだけで自動的にリロードされます。"
```

- [ ] **Step 2: 既存の実体コピーを含む状態で1回目の実行をする**

現在 `%APPDATA%\Blender Foundation\Blender\5.2\scripts\addons\NuniAvatarToolkit` に実体コピーが存在する状態(過去のZIPインストールによるもの)で、削除ロジックが動くことを確認する。

Run: `powershell -File "E:\git\BlenderAddon\tools\setup-dev-link.ps1" -BlenderVersion "5.2"`
Expected: 出力に `既存の実体コピーを削除しました` と `junction作成` が2行、`script_directory_add`、`addons enabled`、`userpref saved`、`セットアップ完了。` が表示され、`$LASTEXITCODE -eq 0` であること。

- [ ] **Step 3: ジャンクションとBlender設定が実際に反映されたことを確認する**

Run:
```powershell
Get-Item "$env:LOCALAPPDATA\NuniAvatarToolkitDev\addons\NuniAvatarToolkit" | Select-Object LinkType, Target
Get-Item "$env:LOCALAPPDATA\NuniAvatarToolkitDev\addons\nuni_dev_reload" | Select-Object LinkType, Target
```
Expected: 両方とも `LinkType` が `Junction`、`Target` がリポジトリ内の実パスを指していること。

続けてBlender側の登録状態を確認する検証スクリプトを作成する:

```python
import bpy
import addon_utils

dev_dir = r"$env:LOCALAPPDATA\NuniAvatarToolkitDev".replace("$", "")
```

上記はシェル変数展開が効かないため、PowerShellから直接埋め込む形で以下のスクリプトを生成して実行する。`script_directories`に登録されているのは`...\addons`ではなくその親(`...\NuniAvatarToolkitDev`)である点に注意(Blenderの`addon_utils.paths()`が各登録ディレクトリに`addons`を自動で付加するため)。

Run:
```powershell
$check = @"
import bpy
dev_dir = r'$env:LOCALAPPDATA\NuniAvatarToolkitDev'
dirs = [d.directory for d in bpy.context.preferences.filepaths.script_directories]
assert dev_dir in dirs, f'script_directoryに未登録: {dirs}'
enabled = {m.__name__ for m in __import__('addon_utils').modules() if __import__('addon_utils').check(m.__name__)[0]}
assert 'NuniAvatarToolkit' in enabled, f'NuniAvatarToolkitが有効化されていない: {enabled}'
assert 'nuni_dev_reload' in enabled, f'nuni_dev_reloadが有効化されていない: {enabled}'
print('TASK2_VERIFY_OK')
"@
$checkPath = Join-Path $env:TEMP "task2-verify.py"
Set-Content -Path $checkPath -Value $check -Encoding utf8
& "C:\Program Files\Blender Foundation\Blender 5.2\blender.exe" --background --python $checkPath
```
Expected: `TASK2_VERIFY_OK` が出力される。

- [ ] **Step 4: 冪等性を確認する(2回連続実行)**

Run: `powershell -File "E:\git\BlenderAddon\tools\setup-dev-link.ps1" -BlenderVersion "5.2"`
Expected: エラーなく完了し、出力に `既存のリンクを削除しました` は出ない(実体コピーは既に削除済みのため何もしない)。`script_directory already registered` が出力される。`junction作成` は2行とも出力される(既存ジャンクションを一旦削除して張り直すため)。終了コード0。

Task 1 Step 4で`_poll`のロジック自体(実ファイルのジャンクション越しmtime検知〜リロード)は検証済みのため、ここでのheadless検証は行わない。セットアップ後の実配置でGUI起動中に体感できることの確認は、本タスク末尾の「実装後の確認(管理人依頼)」セクションで行う(`bpy.app.timers`は`--background`モードのイベントループでは実質的に発火しないため、GUI起動が前提になる)。

- [ ] **Step 5: Commit**

```bash
git add tools/setup-dev-link.ps1
git commit -m "Add setup-dev-link.ps1 to link the addon into Blender via junctions"
```

---

### Task 3: `teardown-dev-link.ps1` 後始末スクリプト

**Files:**
- Create: `tools/teardown-dev-link.ps1`

**Interfaces:**
- Consumes: Task 2で作成した `tools/setup-dev-link.ps1` が構築した状態(`%LOCALAPPDATA%\NuniAvatarToolkitDev\addons` 配下のジャンクション、Blenderのscript_directories登録、有効化されたアドオン)を前提として、それらを取り除く。
- Produces: なし(スクリプト)。実行後は `%LOCALAPPDATA%\NuniAvatarToolkitDev` が削除され、Blenderの設定から登録が消える。

- [ ] **Step 1: `tools/teardown-dev-link.ps1` を作成する**

```powershell
[CmdletBinding()]
param(
    [string]$BlenderVersion = "5.2"
)

$ErrorActionPreference = "Stop"

$blenderExe = "C:\Program Files\Blender Foundation\Blender $BlenderVersion\blender.exe"
if (-not (Test-Path $blenderExe)) {
    Write-Error "Blender $BlenderVersion が見つかりません: $blenderExe"
    exit 1
}

$devDir = Join-Path $env:LOCALAPPDATA "NuniAvatarToolkitDev"
$devAddonsDir = Join-Path $devDir "addons"

$pyScript = @"
import bpy
import addon_utils

addon_utils.disable('NuniAvatarToolkit', default_set=True)
addon_utils.disable('nuni_dev_reload', default_set=True)
print('addons disabled')

dev_dir = r'$devDir'
dirs = bpy.context.preferences.filepaths.script_directories
target_index = None
for i, d in enumerate(dirs):
    if d.directory == dev_dir:
        target_index = i
        break
if target_index is not None:
    bpy.ops.preferences.script_directory_remove(index=target_index)
    print('script_directory_remove: ' + dev_dir)
else:
    print('script_directory not registered: ' + dev_dir)

bpy.ops.wm.save_userpref()
print('userpref saved')
"@

$pyScriptPath = Join-Path $env:TEMP "nuni-teardown-dev-link.py"
Set-Content -Path $pyScriptPath -Value $pyScript -Encoding utf8

& $blenderExe --background --python $pyScriptPath
if ($LASTEXITCODE -ne 0) {
    Write-Error "Blenderの起動に失敗しました (exit code $LASTEXITCODE)"
    exit 1
}

if (Test-Path $devAddonsDir) {
    Get-ChildItem -Path $devAddonsDir -Force | ForEach-Object {
        if ($_.LinkType -eq "Junction" -or $_.LinkType -eq "SymbolicLink") {
            Remove-Item $_.FullName -Force -Recurse -Confirm:$false
            Write-Output "削除: $($_.FullName)"
        } else {
            Write-Warning "$($_.FullName) はジャンクションではないため残しました。"
        }
    }
    $leftover = Get-ChildItem -Path $devAddonsDir -Force
    if ($leftover.Count -eq 0) {
        Remove-Item $devAddonsDir -Force -Confirm:$false
    }
}

if (Test-Path $devDir) {
    $leftoverRoot = Get-ChildItem -Path $devDir -Force
    if ($leftoverRoot.Count -eq 0) {
        Remove-Item $devDir -Force -Confirm:$false
        Write-Output "削除: $devDir"
    } else {
        Write-Warning "$devDir にファイルが残っているため削除をスキップしました。"
    }
}

Write-Output "後片付け完了。"
```

- [ ] **Step 2: セットアップ済みの状態から実行する**

Task 2の検証で作成された状態が残っている前提で実行する(残っていない場合は先に `setup-dev-link.ps1` を実行してから行う)。

Run: `powershell -File "E:\git\BlenderAddon\tools\teardown-dev-link.ps1" -BlenderVersion "5.2"`
Expected: `addons disabled`、`script_directory_remove: ...`、`userpref saved`、`削除: ...\NuniAvatarToolkit`、`削除: ...\nuni_dev_reload`、`削除: ...\NuniAvatarToolkitDev`、`後片付け完了。` が出力され、終了コード0。

- [ ] **Step 3: ジャンクションと設定が消えたことを確認する**

Run: `Test-Path "$env:LOCALAPPDATA\NuniAvatarToolkitDev"`
Expected: `False`

続けてBlender側の登録解除を確認する:

```powershell
$check = @"
import bpy
dev_dir = r'$env:LOCALAPPDATA\NuniAvatarToolkitDev'
dirs = [d.directory for d in bpy.context.preferences.filepaths.script_directories]
assert dev_dir not in dirs, f'script_directoryが残っている: {dirs}'
print('TASK3_VERIFY_OK')
"@
$checkPath = Join-Path $env:TEMP "task3-verify.py"
Set-Content -Path $checkPath -Value $check -Encoding utf8
& "C:\Program Files\Blender Foundation\Blender 5.2\blender.exe" --background --python $checkPath
```
Expected: `TASK3_VERIFY_OK` が出力される。

- [ ] **Step 4: リポジトリ側のファイルが無傷であることを確認する**

Run: `git status`
Expected: `nothing to commit, working tree clean`(Task 1〜3で新規作成したファイルをコミット済みの場合)。少なくとも `NuniAvatarToolkit/` 配下に意図しない変更・削除が無いこと。

- [ ] **Step 5: 再度セットアップを実行し、往復後も壊れないことを確認する(冪等性の最終確認)**

Run: `powershell -File "E:\git\BlenderAddon\tools\setup-dev-link.ps1" -BlenderVersion "5.2"`
Expected: Task 2 Step 2と同様に正常完了する。

- [ ] **Step 6: 配布ZIPに `tools/` が含まれないことを確認する**

Run:
```powershell
$dest = "E:\git\BlenderAddon\.tmp-zip-check.zip"
if (Test-Path $dest) { Remove-Item $dest -Force }
Compress-Archive -Path "E:\git\BlenderAddon\NuniAvatarToolkit" -DestinationPath $dest
Add-Type -AssemblyName System.IO.Compression.FileSystem
$zip = [System.IO.Compression.ZipFile]::OpenRead($dest)
$hasTools = $zip.Entries | Where-Object { $_.FullName -like "*tools*" }
$zip.Dispose()
Remove-Item $dest -Force
if ($hasTools) { Write-Output "NG: toolsが含まれている" } else { Write-Output "OK: toolsは含まれていない" }
```
Expected: `OK: toolsは含まれていない`

- [ ] **Step 7: Commit**

```bash
git add tools/teardown-dev-link.ps1
git commit -m "Add teardown-dev-link.ps1 to remove the dev auto-reload setup"
```

---

## 実装後の確認(管理人依頼)

全タスク完了後、以下は管理人自身での確認をお願いします(GUI操作を伴うため技師・エージェントでは代替できません):

- Blenderを通常通りGUI起動し、サイドバー「Avatar Toolkit」タブの各パネルが問題なく動作すること。
- `NuniAvatarToolkit/features/hidden_mesh/panel.py` の `bl_label = "隠れメッシュ削除"` を適当なテキストエディタで書き換えて保存し、Blenderを再起動せずに1〜2秒程度でサイドバーのパネル名が変わることを確認する。確認後は元の文言に戻して保存すること。
- 実際に `NuniAvatarToolkit/features/` 配下のコードを編集・保存し、Blenderを再起動せずに変更が反映されることを日常的な確認サイクルとして体感すること。
