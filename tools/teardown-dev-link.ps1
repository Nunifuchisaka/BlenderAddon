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
