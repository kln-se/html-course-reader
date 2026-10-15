# Build a Windows portable distribution using the project's virtual environment.
[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

if ([Environment]::OSVersion.Platform -ne [PlatformID]::Win32NT) {
    throw 'Build on Windows. Cross-compilation is not supported.'
}

$projectRoot = Split-Path -Parent $PSScriptRoot
$pythonExe = Join-Path $projectRoot '.venv/Scripts/python.exe'
$assets = Join-Path $projectRoot 'src/course_reader/assets'
$hooksDir = Join-Path $projectRoot 'scripts/hooks'
$outputDir = Join-Path $projectRoot 'dist/HtmlCourseReader'

Push-Location -LiteralPath $projectRoot
try {
    foreach ($required in @($pythonExe, "$assets/app.ico", "$hooksDir/hook-PySide6.QtGui.py", 'main.py', 'LICENSE')) {
        if (-not (Test-Path -LiteralPath $required)) {
            throw "Required path is missing: $required"
        }
    }
    if (Test-Path -LiteralPath $outputDir) {
        throw "Output already exists: $outputDir. Move it elsewhere before rebuilding to preserve user data."
    }

    $buildArguments = @(
        '-B', '-m', 'PyInstaller', '--onedir', '--windowed',
        '--name', 'HtmlCourseReader', '--distpath', 'dist',
        '--workpath', 'build', '--specpath', 'build',
        '--additional-hooks-dir', $hooksDir,
        # This application uses Widgets, not QML. Avoid collecting the entire
        # QML plugin tree; native DLL dependencies are still resolved normally.
        '--exclude-module', 'PySide6.QtQml',
        '--exclude-module', 'PySide6.QtQuick',
        '--exclude-module', 'PySide6.QtQuickWidgets',
        '--exclude-module', 'PySide6.QtWebEngineQuick',
        '--icon', "$assets/app.ico",
        '--add-data', "${assets}:src/course_reader/assets", 'main.py'
    )
    & $pythonExe @buildArguments
    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller failed with exit code $LASTEXITCODE."
    }
    if (-not (Test-Path -LiteralPath "$outputDir/HtmlCourseReader.exe" -PathType Leaf)) {
        throw 'PyInstaller did not produce the expected executable.'
    }

    # Detect accidental reintroduction of the unused QML distribution.
    if (Test-Path -LiteralPath "$outputDir/_internal/PySide6/qml") {
        throw 'Unexpected QML plugin tree in output. Review the build dependencies before distribution.'
    }
    $unexpectedQtDlls = @(
        Get-ChildItem -LiteralPath "$outputDir/_internal" -Recurse -File |
            Where-Object { $_.Name -match '^Qt6(Charts|DataVisualization|Graphs|GraphsWidgets|Quick3D.*|QuickTimeline.*|VirtualKeyboard)\.dll$' }
    )
    if ($unexpectedQtDlls.Count -gt 0) {
        throw "Unexpected optional Qt modules in output: $($unexpectedQtDlls.Name -join ', '). Review dependencies before distribution."
    }

    Copy-Item -LiteralPath 'LICENSE' -Destination $outputDir
    Write-Host "Build complete: $outputDir/HtmlCourseReader.exe"
} finally {
    Pop-Location
}
