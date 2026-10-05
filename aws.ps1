[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [ValidateSet('up', 'down', 'deploy', 'status', 'nuke')]
    [string]$Command = 'status'
)

$ErrorActionPreference = 'Stop'

$bash = $null
foreach ($candidate in @(
        "$env:ProgramFiles\Git\bin\bash.exe",
        "${env:ProgramFiles(x86)}\Git\bin\bash.exe",
        "$env:LOCALAPPDATA\Programs\Git\bin\bash.exe")) {
    if (Test-Path $candidate) { $bash = $candidate; break }
}
if (-not $bash) {
    $onPath = (Get-Command bash -ErrorAction SilentlyContinue).Source
    if ($onPath -and $onPath -notlike "*\System32\bash.exe") { $bash = $onPath }
}
if (-not $bash) {
    Write-Error "bash not found. Install Git for Windows, which provides it."
}

Push-Location $PSScriptRoot
try {
    & $bash 'scripts/aws.sh' $Command
    $code = $LASTEXITCODE
}
finally {
    Pop-Location
}
exit $code
