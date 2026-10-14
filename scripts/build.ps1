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
$outputDir = Join-Path $projectRoot 'dist/HtmlCourseReader'

Push-Location -LiteralPath $projectRoot
try {
    foreach ($required in @($pythonExe, "$assets/app.ico", 'main.py', 'LICENSE', 'THIRD_PARTY_NOTICES.txt', 'licenses')) {
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

    Copy-Item -LiteralPath 'LICENSE', 'THIRD_PARTY_NOTICES.txt' -Destination $outputDir
    Copy-Item -LiteralPath 'licenses' -Destination $outputDir -Recurse
    Write-Host "Build complete: $outputDir/HtmlCourseReader.exe"
} finally {
    Pop-Location
}
