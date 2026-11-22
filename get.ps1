# Kiosk Player in een keer downloaden en installeren op Windows 10/11.
#
#   irm https://raw.githubusercontent.com/luukderooij/Kiosk-player/main/get.ps1 | iex
#
# Opties via omgevingsvariabelen (zet ze in hetzelfde venster voor je de regel uitvoert):
#   $env:KIOSK_BRANCH = 'test-branch'   een andere branch installeren (standaard main)
#   $env:KIOSK_PORT = '8090'            een andere webpoort (standaard 8080)
#
# Dit script haalt de versie op van GitHub en start daarna install.ps1 daaruit.
# Het draait via iex in het venster van de gebruiker: daarom alles in een scriptblok
# (geen gelekte variabelen of instellingen) en nooit 'exit' (dat sluit het venster).
# Dit bestand bevat bewust alleen ASCII-tekens.
& {
    $ErrorActionPreference = 'Stop'
    $ProgressPreference = 'SilentlyContinue'   # Invoke-WebRequest is anders erg traag in PowerShell 5.1
    [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12

    $repo = 'luukderooij/Kiosk-player'
    $branch = if ($env:KIOSK_BRANCH) { $env:KIOSK_BRANCH } else { 'main' }
    $headers = @{ 'User-Agent' = 'kiosk-player-installer'; 'Accept' = 'application/vnd.github.sha' }

    Write-Host "==> Versie opzoeken: $repo, branch $branch" -ForegroundColor Cyan
    try {
        $sha = "$(Invoke-RestMethod -Headers $headers "https://api.github.com/repos/$repo/commits/$([uri]::EscapeDataString($branch))")".Trim()
    } catch {
        Write-Host "Branch '$branch' niet gevonden op GitHub, of GitHub is niet bereikbaar: $_" -ForegroundColor Red
        return
    }
    if ($sha -notmatch '^[0-9a-f]{40}$') { Write-Host "Onverwacht antwoord van GitHub: $sha" -ForegroundColor Red; return }

    $tmp = Join-Path ([IO.Path]::GetTempPath()) ("kiosk-player-" + [guid]::NewGuid().ToString('N').Substring(0, 8))
    New-Item -ItemType Directory -Force $tmp | Out-Null
    try {
        Write-Host "==> Downloaden ($($sha.Substring(0, 7)))" -ForegroundColor Cyan
        $zip = Join-Path $tmp 'kiosk-player.zip'
        Invoke-WebRequest -UseBasicParsing -Headers @{ 'User-Agent' = 'kiosk-player-installer' } -OutFile $zip "https://codeload.github.com/$repo/zip/$sha"
        Expand-Archive -Path $zip -DestinationPath $tmp
        $src = Get-ChildItem $tmp -Directory | Select-Object -First 1
        $env:KIOSK_GIT_SHA = $sha
        $env:KIOSK_GIT_BRANCH = $branch
        $psArgs = @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', (Join-Path $src.FullName 'install.ps1'))
        if ($env:KIOSK_PORT) { $psArgs += @('-Port', $env:KIOSK_PORT) }
        & powershell.exe @psArgs
        if ($LASTEXITCODE -ne 0) { Write-Host "De installatie is niet gelukt (code $LASTEXITCODE)." -ForegroundColor Red }
    } finally {
        Remove-Item Env:KIOSK_GIT_SHA, Env:KIOSK_GIT_BRANCH -ErrorAction SilentlyContinue
        Remove-Item -Recurse -Force $tmp -ErrorAction SilentlyContinue
    }
}
