<#
.SYNOPSIS
  Create, inspect and destroy the AWS deployment, from PowerShell.

.DESCRIPTION
  A thin wrapper over scripts/aws.sh. It exists because the Makefile does not: `make` is
  not installed on Windows by default, so every `make aws-*` target in the README is
  unrunnable on the machine this project is actually developed on.

  The logic lives in the shell script rather than here so there is one implementation
  rather than two that drift apart. This only finds a bash to run it with.

.EXAMPLE
  .\aws.ps1 status     # what is running, and what it cost
  .\aws.ps1 up         # create everything and deploy   (~15 min)
  .\aws.ps1 down       # destroy everything billable    (~10 min)
  .\aws.ps1 deploy     # redeploy onto a running host
  .\aws.ps1 nuke       # also destroy bronze, ECR and stored keys
#>
[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [ValidateSet('up', 'down', 'deploy', 'status', 'nuke')]
    [string]$Command = 'status'
)

$ErrorActionPreference = 'Stop'

# Git Bash by name and path first, PATH last. `bash` on PATH is usually
# C:\Windows\System32\bash.exe, which is not a shell but the WSL launcher: it runs the
# script inside the WSL filesystem, where the project directory and the Windows AWS CLI
# do not exist. It fails in a way that reads like a broken script rather than the wrong
# interpreter -- the observed symptom was `set: pipefail` on a line that is valid bash.
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

# A relative path, run from the project root, rather than the absolute one: bash reads
# `C:\Users\...` as a relative path containing no directory separators it recognises and
# reports "No such file or directory" for a file that is plainly there.
Push-Location $PSScriptRoot
try {
    & $bash 'scripts/aws.sh' $Command
    $code = $LASTEXITCODE
}
finally {
    Pop-Location
}
exit $code
