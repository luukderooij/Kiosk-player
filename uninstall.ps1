<#
Kiosk Player verwijderen op Windows.

  powershell -ExecutionPolicy Bypass -File .\uninstall.ps1          # programma weg, media en instellingen blijven
  powershell -ExecutionPolicy Bypass -File .\uninstall.ps1 -Alles   # ook de gegevensmap met alle media

Dit bestand bevat bewust alleen ASCII-tekens.
#>
param(
    [switch]$Alles,
    [string]$InstallDir = (Join-Path $env:LOCALAPPDATA 'KioskPlayer')
)
$ErrorActionPreference = 'Stop'
$DataDir = Join-Path $env:USERPROFILE 'kiosk-player'
$TaskName = 'Kiosk Player'
$Startup = Join-Path ([Environment]::GetFolderPath('Startup')) 'Kiosk Player.lnk'

if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
    Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
}
if (Test-Path $Startup) { Remove-Item -Force $Startup }
$pattern = "*$InstallDir*run.py*"
Get-CimInstance Win32_Process -Filter "Name like 'python%.exe'" |
    Where-Object { $_.CommandLine -and $_.CommandLine -like $pattern } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
Start-Sleep -Seconds 1
if (Test-Path $InstallDir) { Remove-Item -Recurse -Force $InstallDir }
Write-Host "Programma verwijderd."

try {
    Start-Process powershell -Verb RunAs -Wait -WindowStyle Hidden -ArgumentList "-NoProfile -Command Remove-NetFirewallRule -DisplayName 'Kiosk Player' -ErrorAction SilentlyContinue"
} catch {
    Write-Warning "De firewallregel 'Kiosk Player' is blijven staan. Verwijder hem eventueel via Windows Defender Firewall."
}

if ($Alles -and (Test-Path $DataDir)) {
    $answer = Read-Host "Ook $DataDir met alle media verwijderen? Dit kan niet ongedaan worden. [j/N]"
    if ($answer -match '^[jJ]') {
        Remove-Item -Recurse -Force $DataDir
        Write-Host "Gegevensmap verwijderd."
    }
} elseif (Test-Path $DataDir) {
    Write-Host "Media en instellingen staan nog in $DataDir"
}
