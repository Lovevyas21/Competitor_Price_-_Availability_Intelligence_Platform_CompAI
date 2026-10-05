Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

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
