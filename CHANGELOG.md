# Changelog

Alle merkbare wijzigingen aan Kiosk Player staan in dit bestand. Het nieuwste staat bovenaan.

De indeling volgt [Keep a Changelog](https://keepachangelog.com/nl/1.1.0/). Bij elke wijziging staat de commit tussen haakjes. Die zie je ook in **Instellingen → Software-update** bij de geïnstalleerde versie.

## [Nog niet uitgebracht]

Alles hieronder staat op `main`, maar heeft nog geen eigen versienummer. Het programma noemt zichzelf nog versie 1.0.

### Toegevoegd

- **Changelog in de webinterface.** Met **Wat is er nieuw** in het paneel Software-update lees je de changelog van de gekozen branch voordat je bijwerkt. Bij **Over deze kiosk** staat de changelog van de versie die nu draait.
- **Installeren in één regel.** Op Ubuntu met `curl … | bash`, op Windows met `irm … | iex` in PowerShell of via cmd. Met `KIOSK_BRANCH` en `KIOSK_PORT` kies je een andere branch of poort. Na zo'n installatie weet het paneel Software-update meteen welke versie er draait. Zie *Snel installeren* in de README. (`369d1b7`)
- **Windows 10 en 11** worden ondersteund, naast Ubuntu 24.04. `install.ps1` installeert zonder administratorrechten, haalt Python, VLC en ffmpeg op met winget, en start Kiosk Player bij het inloggen via de geplande taak *Kiosk Player*. `uninstall.ps1` verwijdert het weer. Op de pagina Instellingen staan het systeem en de gevonden vlc.exe; het veld Display staat daar alleen nog op Ubuntu. (`a21c426`)
- **Bijwerken via de website**, in het paneel **Instellingen → Software-update**. Je ziet welke versie er draait en wat er nieuw is op GitHub. Je kunt bijwerken, een andere branch als testversie installeren, en de vorige versie terugzetten. Start een nieuwe versie drie keer niet goed op, dan zet Kiosk Player vanzelf de vorige versie terug. (`8fb2345`)
- Automatische tests op GitHub bij elke wijziging, op Ubuntu en op Windows. (`73ca6b6`, `a21c426`)

### Gewijzigd

- De pagina **Nu** en de rest van de webinterface blijven reageren terwijl VLC start of stopt. Voorheen kon de interface daarbij een paar seconden vastlopen. (`73ca6b6`)
- `install.sh` maakt de kioskgebruiker eigenaar van `/opt/kiosk-player`, zodat bijwerken via de website kan. Op een bestaande installatie moet je daarvoor eenmalig `sudo ./install.sh` opnieuw uitvoeren. (`8fb2345`)

### Opgelost

- Versie `a21c426` en `369d1b7` startten niet als waitress geïnstalleerd was, en dat is bij elke installatie zo, op Ubuntu en op Windows. Heb je via de website naar zo'n versie bijgewerkt, dan is de vorige versie vanzelf teruggezet. Heb je zo'n versie nieuw geïnstalleerd, voer de installatie dan opnieuw uit. Bijwerken via de website kan in dat geval niet, omdat de website niet start. (`1970bed`)
- Stonden een geplande wachtrij én de standaardwachtrij allebei op **één keer spelen**, dan speelden ze eindeloos om en om. Nu speelt er na afloop van beide niets meer, tot de regel opnieuw begint. (`73ca6b6`)

### Beveiliging

- Wijzig je het wachtwoord, dan worden alle andere browsers uitgelogd. Na deze update moet iedereen één keer opnieuw inloggen. (`73ca6b6`)
- Als VLC-commando zijn alleen nog `vlc` en `cvlc` toegestaan, op Windows ook het pad naar vlc.exe in een programmamap. Als extra opties zijn alleen VLC-opties met `--` toegestaan, zonder opties die andere programma's laden of bestanden wegschrijven. Zo kan de webinterface geen willekeurige programma's starten. (`73ca6b6`, `a21c426`)
- Updates via de website komen alleen uit de ingestelde GitHub-repository, en alleen van branches die daar echt bestaan. (`8fb2345`)

## [1.0] - 2026-11-22

Eerste versie. (`2d6be57`)

- Webinterface voor het scherm op een Ubuntu 24.04-kiosk, met de pagina's **Nu**, **Media**, **Wachtrijen**, **Planning** en **Instellingen**.
- Video's en afbeeldingen uploaden, met voorbeeldplaatjes en de duur.
- Wachtrijen met een vaste volgorde, een weergavetijd per afbeelding, en doorlopend herhalen of één keer spelen.
- Planning met regels per dag en tijd, eventueel binnen een periode, plus een standaardwachtrij.
- VLC bedienen: vorige, pauze, volgende, stop en herstart. Stopt VLC onverwacht, dan start Kiosk Player hem opnieuw.
- Installatie met `install.sh` als systemd-dienst, en verwijderen met `uninstall.sh`.

[Nog niet uitgebracht]: https://github.com/luukderooij/Kiosk-player/compare/2d6be57...main
[1.0]: https://github.com/luukderooij/Kiosk-player/commit/2d6be57
