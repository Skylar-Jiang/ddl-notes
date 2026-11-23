param(
    [switch]$InstallDependencies,
    [switch]$OneDir,
    [string]$NodePath = 'node'
)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$Python = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $Python)) {
    python -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw 'Could not create the project virtual environment.' }
    $InstallDependencies = $true
}
if ($InstallDependencies) {
    & $Python -m pip install -r requirements-build.txt
    if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
}
& $Python -m unittest discover -s tests -v
if ($LASTEXITCODE -ne 0) { throw 'Tests failed. Build stopped.' }
& $NodePath --test tests/browser_readers.test.cjs
if ($LASTEXITCODE -ne 0) { throw 'Browser reader tests failed. Build stopped.' }
& $Python tools/make_icon.py
if ($LASTEXITCODE -ne 0) { throw 'Icon generation failed.' }
$Mode = if ($OneDir) { '--onedir' } else { '--onefile' }
& $Python -m PyInstaller --noconfirm --clean $Mode --windowed --name DDLNotes `
    --icon ddl_notes/assets/app.ico --add-data 'ddl_notes/assets;ddl_notes/assets' `
    --hidden-import pystray._win32 --exclude-module numpy --exclude-module pandas `
    --exclude-module playwright `
    --exclude-module matplotlib --exclude-module scipy --exclude-module IPython run.py
if ($LASTEXITCODE -ne 0) { throw 'PyInstaller build failed.' }
& $Python -m PyInstaller --noconfirm --clean --onefile --console --name DDLNotesSync `
    --exclude-module tkinter --exclude-module numpy --exclude-module pandas `
    --exclude-module matplotlib --exclude-module scipy --exclude-module IPython sync_host.py
if ($LASTEXITCODE -ne 0) { throw 'Native sync helper build failed.' }
& $Python -m PyInstaller --noconfirm --clean --onedir --console --name DDLNotesAutoSync `
    --add-data 'browser-helper;browser-helper' --exclude-module tkinter `
    --exclude-module numpy --exclude-module pandas --exclude-module matplotlib `
    --exclude-module scipy --exclude-module IPython sync_worker.py
if ($LASTEXITCODE -ne 0) { throw 'Desktop auto sync worker build failed.' }
$BundleDirectory = if ($OneDir) { Join-Path $PSScriptRoot 'dist\DDLNotes' } else { Join-Path $PSScriptRoot 'dist' }
if ($OneDir) { Copy-Item -LiteralPath 'dist\DDLNotesSync.exe' -Destination $BundleDirectory -Force }
if ($OneDir) { Copy-Item -LiteralPath 'dist\DDLNotesAutoSync' -Destination $BundleDirectory -Recurse -Force }
Copy-Item -LiteralPath 'browser-helper' -Destination $BundleDirectory -Recurse -Force
Copy-Item -LiteralPath 'SYNC-SETUP.md' -Destination $BundleDirectory -Force
Copy-Item -LiteralPath 'README.md' -Destination $BundleDirectory -Force
Copy-Item -LiteralPath 'TESTING.md' -Destination $BundleDirectory -Force
if (-not $OneDir) {
    & $Python tools/package_bundle.py --directory $BundleDirectory
    if ($LASTEXITCODE -ne 0) { throw 'Bundle packaging failed.' }
}
Write-Host 'Build finished. See the dist directory.'
