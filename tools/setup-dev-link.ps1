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
