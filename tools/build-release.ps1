param(
    [string]$RepoRoot = (Split-Path -Parent $PSScriptRoot)
)

# 配布用ZIPを作成する。ZIPのトップレベルに NuniAvatarToolkit フォルダを置き、
# __pycache__・*.pyc・休止中の features/texture_bake/ を除外する。

$ErrorActionPreference = "Stop"

Add-Type -AssemblyName System.IO.Compression
Add-Type -AssemblyName System.IO.Compression.FileSystem

$addonName = "NuniAvatarToolkit"
$addonDir = Join-Path $RepoRoot $addonName
$initPath = Join-Path $addonDir "__init__.py"
if (-not (Test-Path $initPath)) {
    Write-Error "アドオンの __init__.py が見つかりません: $initPath"
    exit 1
}

$initText = [System.IO.File]::ReadAllText($initPath, [System.Text.Encoding]::UTF8)
$match = [regex]::Match($initText, '"version"\s*:\s*\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\)')
if (-not $match.Success) {
    Write-Error "bl_info の version を読み取れません: $initPath"
    exit 1
}
$version = "{0}.{1}.{2}" -f $match.Groups[1].Value, $match.Groups[2].Value, $match.Groups[3].Value

$zipPath = Join-Path $RepoRoot "$addonName-$version.zip"
if (Test-Path $zipPath) {
    Remove-Item $zipPath -Force
}

$addonRoot = (Resolve-Path $addonDir).Path.TrimEnd('\', '/')
$excludedDir = Join-Path $addonRoot "features\texture_bake"

$files = Get-ChildItem -Path $addonRoot -Recurse -File | Where-Object {
    $full = $_.FullName
    -not ($full -like "*\__pycache__\*") -and
    $_.Extension -ne ".pyc" -and
    -not $full.StartsWith($excludedDir + "\", [System.StringComparison]::OrdinalIgnoreCase)
} | Sort-Object FullName

# エントリ名の区切りは macOS/Linux でも展開できるよう必ず "/" にする。
$zip = [System.IO.Compression.ZipFile]::Open($zipPath, [System.IO.Compression.ZipArchiveMode]::Create)
try {
    foreach ($file in $files) {
        $relative = $file.FullName.Substring($addonRoot.Length + 1).Replace('\', '/')
        $entryName = "$addonName/$relative"
        [System.IO.Compression.ZipFileExtensions]::CreateEntryFromFile(
            $zip, $file.FullName, $entryName, [System.IO.Compression.CompressionLevel]::Optimal
        ) | Out-Null
    }
}
finally {
    $zip.Dispose()
}

Write-Host "作成しました: $zipPath ($($files.Count) ファイル)"
