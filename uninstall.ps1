<#
Kiosk Player verwijderen op Windows.

Kan ook via Instellingen > Apps > Kiosk Player > Verwijderen.

  powershell -ExecutionPolicy Bypass -File "$env:LOCALAPPDATA\KioskPlayer\uninstall.ps1"          # media en instellingen blijven
  powershell -ExecutionPolicy Bypass -File "$env:LOCALAPPDATA\KioskPlayer\uninstall.ps1" -Alles   # ook de gegevensmap met alle media

install.ps1 zet dit script in de programmamap; het verwijdert die map ook zelf.
Dit bestand bevat bewust alleen ASCII-tekens.
#>
param(
    [switch]$Alles,
    [switch]$Pauze,   # wacht op Enter aan het eind (gebruikt door Instellingen > Apps, anders sluit het venster meteen)
    [string]$InstallDir = (Join-Path $env:LOCALAPPDATA 'KioskPlayer')
)
$ErrorActionPreference = 'Stop'
$DataDir = Join-Path $env:USERPROFILE 'kiosk-player'
$TaskName = 'Kiosk Player'
$Startup = Join-Path ([Environment]::GetFolderPath('Startup')) 'Kiosk Player.lnk'
$UninstallKey = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\KioskPlayer'
Set-Location ([IO.Path]::GetTempPath())   # niet in de map staan die we gaan verwijderen

function Get-KioskProcess([string]$extra) {
    Get-CimInstance Win32_Process -Filter "Name like 'python%.exe'" |
        Where-Object { $_.CommandLine -and $_.CommandLine -like "*$InstallDir*run.py*$extra" }
}

# 1. Supervisor stoppen. Kiosk Player merkt dat en stopt zelf VLC (zie watch_supervisor).
if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
    Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
}
Get-KioskProcess '*--supervise*' | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
for ($i = 0; $i -lt 10 -and @(Get-KioskProcess '').Count; $i++) { Start-Sleep -Milliseconds 500 }

# 2. Wat dan nog draait hard stoppen, ook een VLC van Kiosk Player (herkenbaar aan de interne bediening).
Get-KioskProcess '' | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
Get-CimInstance Win32_Process -Filter "Name = 'vlc.exe'" |
    Where-Object { $_.CommandLine -like '*--extraintf=http*--http-host=127.0.0.1*' } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
Start-Sleep -Seconds 1

# 3. Programma, snelkoppeling en registratie bij Instellingen > Apps weghalen.
if (Test-Path $Startup) { Remove-Item -Force $Startup }
if (Test-Path $UninstallKey) { Remove-Item -Recurse -Force $UninstallKey }
$removed = $false
for ($i = 0; $i -lt 5 -and -not $removed; $i++) {
    try {
        if (Test-Path $InstallDir) { Remove-Item -Recurse -Force $InstallDir }
        $removed = $true
    } catch { Start-Sleep -Seconds 1 }
}
if ($removed) {
    Write-Host "Programma verwijderd."
} else {
    Write-Warning ("De map $InstallDir kon niet helemaal weg, omdat een ander programma er nog iets in open heeft " +
                   "(bijvoorbeeld een Verkenner- of PowerShell-venster dat in die map staat). Sluit dat en verwijder de map met de hand.")
}

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
if ($Pauze) { Read-Host "Druk op Enter om dit venster te sluiten" | Out-Null }
