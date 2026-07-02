# One-time compatibility patch for Azure Functions Core Tools (Python 3.12).
#
# Problem: the bundled worker loader.py evaluates f"{sys.modules}" at import
# time. Python 3.12 module repr expects MetaPathFinder._path, but the old six.py
# in Core Tools defines _SixMetaPathImporter without _path.
#
# Safe to re-run (idempotent).

$workerRoot = Join-Path $env:APPDATA "npm\node_modules\azure-functions-core-tools\bin\workers\python\3.12\WINDOWS\X64"
$sixFile = Join-Path $workerRoot "six.py"

if (-not (Test-Path $sixFile)) {
    Write-Error "Azure Functions worker six.py not found at: $sixFile"
    Write-Error "Install Core Tools: npm install -g azure-functions-core-tools@4"
    exit 1
}

$content = Get-Content $sixFile -Raw
$marker = "# SCM patch: Python 3.12 _path compat for Azure Functions worker"

if ($content -match [regex]::Escape($marker)) {
    Write-Host "Worker six.py already patched."
    exit 0
}

$needle = "class _SixMetaPathImporter(object):"
if ($content -notmatch [regex]::Escape($needle)) {
    Write-Error "Unexpected worker six.py format. Manual patch required."
    exit 1
}

$patchBlock = "# SCM patch: Python 3.12 _path compat for Azure Functions worker`r`n    @property`r`n    def _path(self):`r`n        return []`r`n`r`n"
$content = $content.Replace($needle, ($needle + "`r`n" + $patchBlock))
[System.IO.File]::WriteAllText($sixFile, $content)
Write-Host "Patched worker six.py for Python 3.12 compatibility."
