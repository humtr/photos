$ErrorActionPreference = "Stop"

Write-Host "Installing OpenSSH Server..."
$capability = "OpenSSH.Server~~~~0.0.1.0"
$dism = "$env:WINDIR\System32\dism.exe"
& $dism /Online /Add-Capability /CapabilityName:$capability
if ($LASTEXITCODE -ne 0) {
    throw "DISM failed to install $capability. Exit code: $LASTEXITCODE"
}

Write-Host "Starting sshd..."
Set-Service -Name sshd -StartupType Automatic
Start-Service -Name sshd

Write-Host "Configuring firewall..."
try {
    Get-NetConnectionProfile |
        Where-Object { $_.IPv4Connectivity -ne "Disconnected" } |
        Set-NetConnectionProfile -NetworkCategory Private
} catch {
    Write-Warning "Could not change network profile to Private: $($_.Exception.Message)"
}

try {
    Set-NetFirewallProfile -Profile Domain,Private,Public -AllowLocalFirewallRules True
} catch {
    Write-Warning "Could not enable local firewall rule merge: $($_.Exception.Message)"
}

if (-not (Get-NetFirewallRule -Name OpenSSH-Server-In-TCP -ErrorAction SilentlyContinue)) {
    New-NetFirewallRule `
        -Name OpenSSH-Server-In-TCP `
        -DisplayName "OpenSSH Server (sshd)" `
        -Enabled True `
        -Direction Inbound `
        -Protocol TCP `
        -Action Allow `
        -LocalPort 22 | Out-Null
} else {
    Set-NetFirewallRule -Name OpenSSH-Server-In-TCP -Enabled True -Direction Inbound -Action Allow
    Set-NetFirewallRule -Name OpenSSH-Server-In-TCP -Profile Any
}

netsh advfirewall firewall add rule name="Codex OpenSSH 22" dir=in action=allow protocol=TCP localport=22 profile=any enable=yes | Out-Null
netsh advfirewall set currentprofile logging droppedconnections enable | Out-Null
netsh advfirewall set currentprofile logging allowedconnections enable | Out-Null

Write-Host "Verifying..."
Get-Service sshd | Select-Object Name,Status,StartType | Format-List
Get-NetFirewallRule -Name OpenSSH-Server-In-TCP | Select-Object Name,Enabled,Direction,Action | Format-List
Get-NetFirewallProfile | Select-Object Name,Enabled,DefaultInboundAction,AllowLocalFirewallRules | Format-Table
Get-NetConnectionProfile | Select-Object Name,InterfaceAlias,NetworkCategory,IPv4Connectivity | Format-Table
netsh advfirewall show currentprofile
netsh advfirewall firewall show rule name="Codex OpenSSH 22"
netstat -ano | Select-String ":22"

Write-Host "OpenSSH Server setup complete."
