$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path $PSScriptRoot).Path
$python = Join-Path $projectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python)) {
    throw "Chưa có .venv. Hãy chạy: python -m venv .venv; .venv\Scripts\python.exe -m pip install -e . pyinstaller"
}
$vendor = Join-Path $projectRoot "ocr2md\vendor\7zip"
& $python -m PyInstaller --noconfirm --onefile --name OCR2MD `
    --distpath (Join-Path $projectRoot "work\dist-final") `
    --workpath (Join-Path $projectRoot "work\pyinstaller-build") `
    --specpath (Join-Path $projectRoot "work") `
    --add-binary "$vendor\7z.exe;ocr2md\vendor\7zip" `
    --add-binary "$vendor\7z.dll;ocr2md\vendor\7zip" `
    --add-data "$vendor\License.txt;ocr2md\vendor\7zip" `
    (Join-Path $projectRoot "launcher.py")
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed." }