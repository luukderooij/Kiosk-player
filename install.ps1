<#
Kiosk Player installeren of bijwerken op Windows 10/11.

  powershell -ExecutionPolicy Bypass -File .\install.ps1
  powershell -ExecutionPolicy Bypass -File .\install.ps1 -Port 8090

Voer dit uit als de gebruiker die op het scherm is ingelogd, in een gewoon
PowerShell-venster (niet "Als administrator"). Voor de firewall en VLC vraagt
Windows zelf om toestemming.

Opnieuw uitvoeren werkt het programma bij; media, wachtrijen en planning blijven bewaard.
Dit bestand bevat bewust alleen ASCII-tekens (Windows PowerShell 5.1 leest het anders verkeerd).
#>
param(
    [int]$Port = 0,
    [string]$InstallDir = (Join-Path $env:LOCALAPPDATA 'KioskPlayer')
)
$ErrorActionPreference = 'Stop'
$Src = Split-Path -Parent $MyInvocation.MyCommand.Path
$DataDir = Join-Path $env:USERPROFILE 'kiosk-player'
$TaskName = 'Kiosk Player'
$User = "$env:USERDOMAIN\$env:USERNAME"
$Startup = Join-Path ([Environment]::GetFolderPath('Startup')) 'Kiosk Player.lnk'

function Step([string]$msg) { Write-Host "==> $msg" -ForegroundColor Cyan }
function Test-Admin {
    $id = [Security.Principal.WindowsIdentity]::GetCurrent()
    ([Security.Principal.WindowsPrincipal]$id).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}
function Install-WithWinget([string]$id) {
    if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
        throw "winget ontbreekt. Installeer '$id' met de hand, of installeer 'App Installer' uit de Microsoft Store."
    }
    winget install -e --id $id --accept-source-agreements --accept-package-agreements --silent
    # -1978335189 (0x8A15002B): staat er al / geen update
    if ($LASTEXITCODE -ne 0 -and $LASTEXITCODE -ne -1978335189) { throw "winget kon $id niet installeren (code $LASTEXITCODE)." }
}
function Find-Python {
    $cands = @()
    if (Get-Command py -ErrorAction SilentlyContinue) {
        $p = & py -3 -c "import sys; print(sys.executable)"
        if ($LASTEXITCODE -eq 0 -and $p) { $cands += "$p".Trim() }
    }
    $cmd = Get-Command python -ErrorAction SilentlyContinue
    if ($cmd -and $cmd.Source -notlike '*WindowsApps*') { $cands += $cmd.Source }
    $cands += @(Get-ChildItem "$env:LOCALAPPDATA\Programs\Python\Python3*\python.exe" -ErrorAction SilentlyContinue |
        Sort-Object FullName -Descending | ForEach-Object { $_.FullName })
    $cands += @(Get-ChildItem "$env:ProgramFiles\Python3*\python.exe" -ErrorAction SilentlyContinue |
        Sort-Object FullName -Descending | ForEach-Object { $_.FullName })
    foreach ($c in $cands) {
        & $c -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)"
        if ($LASTEXITCODE -eq 0) { return $c }
    }
    return $null
}
function Find-Vlc {
    foreach ($base in @($env:ProgramFiles, ${env:ProgramFiles(x86)}, "$env:LOCALAPPDATA\Programs")) {
        if ($base -and (Test-Path (Join-Path $base 'VideoLAN\VLC\vlc.exe'))) { return (Join-Path $base 'VideoLAN\VLC\vlc.exe') }
    }
    return $null
}
function Stop-KioskPlayer {
    if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
        Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    }
    $pattern = "*$InstallDir*run.py*"
    Get-CimInstance Win32_Process -Filter "Name like 'python%.exe'" |
        Where-Object { $_.CommandLine -and $_.CommandLine -like $pattern } |
        ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
    Start-Sleep -Seconds 1
}

Write-Host "Kiosk Player wordt geinstalleerd voor gebruiker $User."
if (Test-Admin) {
    Write-Warning "Dit venster draait als administrator. Dat mag, maar Kiosk Player wordt ingesteld voor $User. Is dat niet de gebruiker die op het scherm inlogt, stop dan nu (Ctrl+C)."
}

Step "Python zoeken"
$Python = Find-Python
if (-not $Python) {
    Step "Python 3.12 installeren met winget"
    Install-WithWinget 'Python.Python.3.12'
    $Python = Find-Python
    if (-not $Python) { throw "Python is geinstalleerd maar niet gevonden. Open een nieuw PowerShell-venster en start dit script opnieuw." }
}
Write-Host "    $Python"

Step "VLC zoeken"
if (-not (Find-Vlc)) {
    Step "VLC installeren met winget (Windows vraagt mogelijk om toestemming)"
    Install-WithWinget 'VideoLAN.VLC'
}
Write-Host "    $(Find-Vlc)"

Step "ffmpeg zoeken (voor duur en voorbeeldplaatjes)"
$wingetLinks = Join-Path $env:LOCALAPPDATA 'Microsoft\WinGet\Links\ffprobe.exe'
if (-not (Get-Command ffprobe -ErrorAction SilentlyContinue) -and -not (Test-Path $wingetLinks)) {
    try { Install-WithWinget 'Gyan.FFmpeg' }
    catch { Write-Warning "ffmpeg kon niet worden geinstalleerd: $_. Kiosk Player werkt, maar zonder voorbeeldplaatjes." }
}

Step "Draaiende Kiosk Player stoppen"
Stop-KioskPlayer

Step "Programma kopieren naar $InstallDir"
New-Item -ItemType Directory -Force $InstallDir | Out-Null
foreach ($name in 'app', 'app.prev', 'app.failed', 'app.swap', '.staging') {
    $p = Join-Path $InstallDir $name
    if (Test-Path $p) { Remove-Item -Recurse -Force $p }
}
Remove-Item -Force (Join-Path $InstallDir 'update-state.json') -ErrorAction SilentlyContinue
Copy-Item -Recurse (Join-Path $Src 'app') $InstallDir
Copy-Item (Join-Path $Src 'run.py') $InstallDir
Get-ChildItem $InstallDir -Recurse -Directory -Filter __pycache__ -ErrorAction SilentlyContinue | Remove-Item -Recurse -Force

Step "Python-omgeving met Flask en waitress"
$Venv = Join-Path $InstallDir '.venv'
$VPy = Join-Path $Venv 'Scripts\python.exe'
$VPyw = Join-Path $Venv 'Scripts\pythonw.exe'
if (-not (Test-Path $VPy)) {
    & $Python -m venv $Venv
    if ($LASTEXITCODE -ne 0) { throw "Kon de Python-omgeving niet maken." }
}
& $VPy -m pip install --disable-pip-version-check --quiet --upgrade "flask>=3,<4" "waitress>=3,<4"
if ($LASTEXITCODE -ne 0) { throw "Kon Flask en waitress niet installeren (heeft de pc internet?)." }

# Welke versie dit is. Uit een git-checkout weten we branch en commit, uit een zip niet.
$sha = '-'; $branch = '-'
if ((Get-Command git -ErrorAction SilentlyContinue) -and (Test-Path (Join-Path $Src '.git'))) {
    $sha = "$(& git -C $Src rev-parse HEAD)".Trim()
    $branch = "$(& git -C $Src rev-parse --abbrev-ref HEAD)".Trim()
    if (-not $sha) { $sha = '-' }
    if (-not $branch) { $branch = '-' }
}
& $VPy -c "import datetime, json, sys; p, b, s = sys.argv[1:4]; json.dump({'source': 'install.ps1', 'branch': None if b == '-' else b, 'sha': None if s == '-' else s, 'installed_at': datetime.datetime.now().isoformat(timespec='seconds'), 'previous': None}, open(p, 'w'), indent=2)" (Join-Path $InstallDir 'VERSION.json') $branch $sha

Step "Gegevensmap $DataDir"
New-Item -ItemType Directory -Force (Join-Path $DataDir 'media') | Out-Null
$Cfg = Join-Path $DataDir 'config.json'
& $VPy -c "import json, os, sys; p, port = sys.argv[1], int(sys.argv[2]); c = json.load(open(p)) if os.path.exists(p) else {}; c['port'] = port or c.get('port', 8080); json.dump(c, open(p, 'w'), indent=2)" $Cfg $Port
$PortNow = [int](& $VPy -c "import json, sys; print(json.load(open(sys.argv[1])).get('port', 8080))" $Cfg)

$hasPw = & $VPy -c "import json, sys; print('ja' if json.load(open(sys.argv[1])).get('password_hash') else 'nee')" $Cfg
if ("$hasPw".Trim() -eq 'nee') {
    do {
        $p1 = Read-Host "Kies een wachtwoord voor de webinterface (minstens 8 tekens)" -AsSecureString
        $p2 = Read-Host "Nogmaals" -AsSecureString
        $s1 = [Runtime.InteropServices.Marshal]::PtrToStringBSTR([Runtime.InteropServices.Marshal]::SecureStringToBSTR($p1))
        $s2 = [Runtime.InteropServices.Marshal]::PtrToStringBSTR([Runtime.InteropServices.Marshal]::SecureStringToBSTR($p2))
        $ok = ($s1 -ceq $s2) -and ($s1.Length -ge 8)
        if (-not $ok) { Write-Host "Niet gelijk of te kort. Probeer het opnieuw." }
    } until ($ok)
    # set-password leest stdin als UTF-8 en negeert de BOM die PowerShell ervoor zet
    $OutputEncoding = New-Object System.Text.UTF8Encoding $false
    $env:KIOSK_DATA_DIR = $DataDir
    $s1 | & $VPy (Join-Path $InstallDir 'run.py') set-password
    Remove-Item Env:KIOSK_DATA_DIR
    $s1 = $null; $s2 = $null
}

# Bestaande media uit Documenten overnemen (alleen de eerste keer, en alleen als je dat wilt)
$docs = [Environment]::GetFolderPath('MyDocuments')
$mediaDir = Join-Path $DataDir 'media'
if ((Test-Path $docs) -and -not (Get-ChildItem $mediaDir -ErrorAction SilentlyContinue)) {
    $ext = '.mp4', '.mkv', '.mov', '.avi', '.webm', '.m4v', '.png', '.jpg', '.jpeg'
    $found = @(Get-ChildItem $docs -File -ErrorAction SilentlyContinue | Where-Object { $ext -contains $_.Extension.ToLower() })
    if ($found.Count -gt 0) {
        Write-Host "Gevonden in ${docs}:"
        $found | ForEach-Object { Write-Host "    $($_.Name)" }
        $answer = Read-Host "Deze bestanden kopieren naar de mediabibliotheek? [j/N]"
        if ($answer -match '^[jJ]') {
            $found | Copy-Item -Destination $mediaDir
            Write-Host "    Gekopieerd. De originelen blijven staan."
        }
    }
}

Step "Automatisch starten bij inloggen"
$taskOk = $false
try {
    $action = New-ScheduledTaskAction -Execute $VPyw -Argument "`"$(Join-Path $InstallDir 'run.py')`" --supervise" -WorkingDirectory $InstallDir
    $trigger = New-ScheduledTaskTrigger -AtLogOn -User $User
    $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable `
        -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1)
    $principal = New-ScheduledTaskPrincipal -UserId $User -LogonType Interactive -RunLevel Limited
    Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -Principal $principal `
        -Description "Kiosk Player: webinterface om VLC op het scherm te beheren" -Force | Out-Null
    $taskOk = $true
    if (Test-Path $Startup) { Remove-Item -Force $Startup }
} catch {
    Write-Warning "Kon de geplande taak niet maken ($_). Er komt een snelkoppeling in de map Opstarten."
    $sh = New-Object -ComObject WScript.Shell
    $lnk = $sh.CreateShortcut($Startup)
    $lnk.TargetPath = $VPyw
    $lnk.Arguments = "`"$(Join-Path $InstallDir 'run.py')`" --supervise"
    $lnk.WorkingDirectory = $InstallDir
    $lnk.Save()
}

Step "Firewall: poort $PortNow openzetten voor het eigen netwerk"
$fw = "Remove-NetFirewallRule -DisplayName 'Kiosk Player' -ErrorAction SilentlyContinue; " +
      "New-NetFirewallRule -DisplayName 'Kiosk Player' -Direction Inbound -Protocol TCP -LocalPort $PortNow -Action Allow -Profile Private,Domain | Out-Null"
try {
    if (Test-Admin) { Invoke-Expression $fw }
    else { Start-Process powershell -Verb RunAs -Wait -WindowStyle Hidden -ArgumentList "-NoProfile -Command $fw" }
} catch {
    Write-Warning "De firewallregel is niet gemaakt. Doe dat later in een PowerShell 'Als administrator':"
    Write-Host "    $fw"
}

$answer = Read-Host "Scherm en slaapstand nooit automatisch uitzetten (aan te raden voor een kiosk)? [j/N]"
if ($answer -match '^[jJ]') {
    powercfg /change monitor-timeout-ac 0
    powercfg /change standby-timeout-ac 0
}

Step "Kiosk Player starten"
if ($taskOk) { Start-ScheduledTask -TaskName $TaskName }
else { Start-Process -FilePath $VPyw -ArgumentList "`"$(Join-Path $InstallDir 'run.py')`" --supervise" -WorkingDirectory $InstallDir }

$up = $false
for ($i = 0; $i -lt 30 -and -not $up; $i++) {
    Start-Sleep -Seconds 1
    try { Invoke-WebRequest -UseBasicParsing -TimeoutSec 2 "http://127.0.0.1:$PortNow/login" | Out-Null; $up = $true } catch { }
}
$ip = (Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
    Where-Object { $_.IPAddress -notlike '127.*' -and $_.IPAddress -notlike '169.254.*' } |
    Select-Object -First 1).IPAddress
Write-Host ""
if ($up) {
    Write-Host "Klaar. Open in je browser:  http://$(if ($ip) { $ip } else { '<ip-van-deze-pc>' }):$PortNow" -ForegroundColor Green
} else {
    Write-Warning "Kiosk Player reageert nog niet. Bekijk $DataDir\logs\stderr.log en $DataDir\logs\kiosk-player.log"
    exit 1
}
Write-Host "Media, wachtrijen en planning staan in $DataDir"
