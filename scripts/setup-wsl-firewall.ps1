<#
.SYNOPSIS
  Allow Windows -> WSL access to the local Postgres and Redis ports.

.DESCRIPTION
  With `networkingMode=mirrored` in .wslconfig, traffic from Windows into the WSL VM is
  policed by the Hyper-V firewall. That is a different firewall from Windows Firewall,
  and its DefaultInboundAction is Block -- so a service listening correctly on
  0.0.0.0:5432 inside WSL still refuses connections from Windows.

  This script adds two narrow inbound rules (TCP 5432 and 6379) for the WSL VM only.

  It deliberately does NOT set `-DefaultInboundAction Allow` on the VM, which is the
  usual advice online: that opens every port on the VM to the host, which is far more
  than this project needs.

  Requires an elevated (Administrator) PowerShell. Safe to run more than once.

.NOTES
  See docs/adr/ADR-006-local-database-runtime.md for the reasoning.
#>

#Requires -RunAsAdministrator

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

# Fixed GUID Microsoft assigns to the WSL VM creator.
$WslVmCreatorId = '{40E0AC32-46A5-438A-A0B2-2B479E8F2E90}'

$rules = @(
    @{ Name = 'WSL-Postgres-5432'; Display = 'WSL Postgres 5432'; Port = 5432 },
    @{ Name = 'WSL-Redis-6379';    Display = 'WSL Redis 6379';    Port = 6379 }
)

foreach ($rule in $rules) {
    $existing = Get-NetFirewallHyperVRule -Name $rule.Name -ErrorAction SilentlyContinue
    if ($existing) {
        Write-Host ("[skip]  {0} already exists" -f $rule.Name)
        continue
    }

    New-NetFirewallHyperVRule `
        -Name $rule.Name `
        -DisplayName $rule.Display `
        -Direction Inbound `
        -VMCreatorId $WslVmCreatorId `
        -Protocol TCP `
        -LocalPorts $rule.Port `
        -Action Allow | Out-Null

    Write-Host ("[added] {0} -> TCP {1}" -f $rule.Name, $rule.Port)
}

Write-Host ''
Write-Host 'Hyper-V firewall rules for the WSL VM:'
Get-NetFirewallHyperVRule -VMCreatorId $WslVmCreatorId -ErrorAction SilentlyContinue |
    Where-Object { $_.Name -like 'WSL-*' } |
    Select-Object Name, Direction, Action |
    Format-Table -AutoSize

Write-Host 'Verifying connectivity from Windows...'
foreach ($port in 5432, 6379) {
    $result = Test-NetConnection -ComputerName 'localhost' -Port $port -WarningAction SilentlyContinue
    $state = if ($result.TcpTestSucceeded) { 'OK' } else { 'STILL BLOCKED' }
    Write-Host ("  localhost:{0} -> {1}" -f $port, $state)
}
