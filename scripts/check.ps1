$ErrorActionPreference='Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)
Get-ChildItem extension -Filter *.js | ForEach-Object {
  node --check $_.FullName
  if ($LASTEXITCODE) { throw "JavaScript syntax: $($_.Name)" }
}
& .venv\Scripts\python.exe -m compileall -q service scripts
if ($LASTEXITCODE) { throw 'Python syntax failed' }
node tests/worker.test.cjs
if ($LASTEXITCODE) { throw 'Window lifecycle tests failed' }
node tests/archive.test.cjs
if ($LASTEXITCODE) { throw 'Archive integrity tests failed' }
node tests/offscreen.test.cjs
if ($LASTEXITCODE) { throw 'Capture mode contract tests failed' }
node tests/pcm-queue.test.cjs
if ($LASTEXITCODE) { throw 'PCM flow control tests failed' }
& .venv\Scripts\python.exe -m pytest tests -q -p no:cacheprovider
if ($LASTEXITCODE) { throw 'Tests failed' }
