# Kiosk Player

Een webinterface om het scherm in het pand te beheren. Hij draait op de kiosk zelf en start VLC voor je. De kiosk kan een Ubuntu 24.04-pc zijn of een Windows 10/11-pc.
Je hebt er geen ssh-commando's meer voor nodig.

- **Media**: video's en afbeeldingen uploaden vanuit de browser, met voorbeeldplaatjes en de duur.
- **Wachtrijen**: zet bestanden in een vaste volgorde en kies per afbeelding hoeveel seconden die in beeld blijft. Een wachtrij kan doorlopend herhalen of één keer spelen.
- **Planning**: kies welke wachtrij op welke dagen en tijden speelt, eventueel alleen binnen een periode. Daarnaast stel je een standaardwachtrij in voor de rest van de tijd.
- **Nu**: zie wat er op het scherm staat en bedien VLC met vorige, pauze, volgende, stop en herstart. Je kunt ook direct een wachtrij starten.
- Stopt VLC onverwacht, dan start Kiosk Player hem vanzelf opnieuw.

---

## Snel installeren

Plak één regel in een terminal op de kiosk. Kiosk Player wordt dan gedownload van GitHub en geïnstalleerd. Het installatiescript stelt daarna dezelfde vragen als bij de gewone installatie hieronder, zoals het wachtwoord voor de webinterface.

**Ubuntu** (in een terminal, als de kioskgebruiker; sudo vraagt om je wachtwoord):

```bash
curl -fsSL https://raw.githubusercontent.com/luukderooij/Kiosk-player/main/get.sh | bash
```

**Windows, PowerShell** (in een gewoon PowerShell-venster, als de kioskgebruiker):

```powershell
irm https://raw.githubusercontent.com/luukderooij/Kiosk-player/main/get.ps1 | iex
```

**Windows, opdrachtprompt (cmd)** of via Windows-toets + R:

```bat
powershell -NoProfile -ExecutionPolicy Bypass -Command "irm https://raw.githubusercontent.com/luukderooij/Kiosk-player/main/get.ps1 | iex"
```

Wil je een andere branch of poort, zet dan eerst een omgevingsvariabele:

| | Ubuntu | Windows (PowerShell) |
|---|---|---|
| Andere branch | `curl -fsSL …/get.sh \| KIOSK_BRANCH=test bash` | `$env:KIOSK_BRANCH = 'test'` en daarna de regel |
| Andere poort | `curl -fsSL …/get.sh \| KIOSK_PORT=8090 bash` | `$env:KIOSK_PORT = '8090'` en daarna de regel |

Dezelfde regel werkt ook om bij te werken. Je media, wachtrijen, planning en wachtwoord blijven bewaard.

> Een script van internet direct uitvoeren betekent dat je de inhoud vertrouwt. Wil je het eerst lezen, download het dan, bekijk het, en voer het daarna uit:
> `curl -fsSLO https://raw.githubusercontent.com/luukderooij/Kiosk-player/main/get.sh && less get.sh && bash get.sh`

---

## Installeren op Ubuntu

Kopieer de map naar de kiosk en voer het installatiescript uit:

```bash
scp kiosk-player.zip protectiepartners@ip-adres-ubuntu:~
ssh -t protectiepartners@ip-adres-ubuntu
unzip kiosk-player.zip
cd kiosk-player
sudo ./install.sh protectiepartners
```

Het script doet het volgende:

1. Het installeert `python3-flask`, `python3-waitress`, `vlc` en `ffmpeg` uit de standaard Ubuntu-pakketten.
2. Het kopieert het programma naar `/opt/kiosk-player`.
3. Het maakt de gegevensmap `~/kiosk-player` voor media, wachtrijen en planning.
4. Het vraagt welk wachtwoord je voor de webinterface wilt gebruiken.
5. Het biedt aan de video's en afbeeldingen uit `~/Documents` over te nemen. De originelen blijven staan.
6. Het maakt de systemd-dienst `kiosk-player` aan. Die start automatisch op en draait als `protectiepartners`, dezelfde gebruiker als je ssh-commando.
7. Staat de ufw-firewall aan, dan zet het poort 8080 open.

Daarna open je in de browser **http://ip-adres-ubuntu:8080**.

Wil je een andere poort, start het script dan zo: `sudo KIOSK_PORT=8090 ./install.sh protectiepartners`

> **Let op:** Kiosk Player sluit bij het starten andere VLC-vensters van deze gebruiker. Zo stopt ook de video die je eerder met de hand via ssh startte, en komen er geen twee video's over elkaar. Gebruik je oude ssh-commando daarom niet meer naast Kiosk Player. Wil je dit gedrag niet, zet het dan uit onder **Instellingen**.

### Bijwerken via de website

Bijwerken kan via **Instellingen → Software-update**. Je ziet daar welke versie er nu draait en of er op GitHub een nieuwere is.

1. Kies bij **Branch** welke versie je wilt. Meestal is dat *main (standaard)*. Een andere branch kies je om een testversie te proberen.
2. Kies **Bijwerken**. Bij een andere branch heet de knop **Deze versie testen**. Kiosk Player downloadt de versie, controleert hem, installeert hem en herstart. Het scherm is dan ongeveer 10 seconden zwart, waarna de pagina vanzelf opnieuw laadt.
3. Wil je terug, kies dan **Vorige versie terugzetten**.

Start een nieuwe versie niet goed op, dan zet Kiosk Player na drie pogingen vanzelf de vorige versie terug. Dat zie je daarna als melding in het paneel. Je media, wachtrijen, planning en wachtwoord blijven bij elke update bewaard.

> Werkt de knop niet en staat er dat de programmamap niet schrijfbaar is? Dan is Kiosk Player geïnstalleerd met een oudere versie van het script. Voer eenmalig `sudo ./install.sh protectiepartners` uit met deze versie, daarna werkt bijwerken via de website.

Dit werkt op Ubuntu en op Windows hetzelfde.

### Bijwerken met het installatiescript

Pak de nieuwe versie uit en voer `sudo ./install.sh protectiepartners` opnieuw uit. Op Windows is dat `install.ps1`. Je media, wachtrijen, planning en wachtwoord blijven bewaard. Dit is nodig als een nieuwe versie andere pakketten nodig heeft, of als `run.py`, het installatiescript of de dienst is veranderd. De website werkt alleen de map `app/` bij.

---

## Installeren op Windows

Kiosk Player werkt op Windows 10 en 11. Log op de kiosk-pc in als de gebruiker die het scherm toont. Kopieer de map naar die pc, pak hem uit, en open in die map een gewoon PowerShell-venster, dus **niet** als administrator:

```powershell
powershell -ExecutionPolicy Bypass -File .\install.ps1
```

Het script doet het volgende:

1. Het installeert Python 3.12, VLC en ffmpeg met winget als ze er nog niet zijn. Voor VLC vraagt Windows om toestemming.
2. Het kopieert het programma naar `%LOCALAPPDATA%\KioskPlayer`, met een eigen Python-omgeving met Flask en waitress.
3. Het maakt de gegevensmap `%USERPROFILE%\kiosk-player` voor media, wachtrijen en planning.
4. Het vraagt welk wachtwoord je voor de webinterface wilt gebruiken.
5. Het biedt aan de video's en afbeeldingen uit je map Documenten over te nemen. De originelen blijven staan.
6. Het maakt de geplande taak **Kiosk Player**, die start zodra deze gebruiker inlogt. Lukt dat niet, dan komt er een snelkoppeling in de map Opstarten.
7. Het zet poort 8080 open in de firewall, alleen voor het eigen netwerk (profiel *Privé* of *Domein*). Daarvoor vraagt Windows om toestemming.
8. Het vraagt of het scherm en de slaapstand nooit automatisch uit moeten gaan. Voor een kiosk is dat aan te raden.

Daarna open je in de browser **http://ip-adres-van-de-pc:8080**. Een andere poort kies je zo: `powershell -ExecutionPolicy Bypass -File .\install.ps1 -Port 8090`

Nog twee instellingen in Windows:
- **Automatisch inloggen.** VLC heeft een bureaublad nodig, dus de kioskgebruiker moet na het opstarten ingelogd zijn. Zet automatisch inloggen aan via `netplwiz`, of via Instellingen → Accounts → Aanmeldingsopties.
- **Netwerkprofiel.** Staat het netwerk op *Openbaar*, dan blokkeert de firewall de webinterface. Zet het op *Privé* via Instellingen → Netwerk en internet.

---

## Voorbeeld: vanaf maandagochtend een afbeelding tussen de video

1. **Media**: upload de PNG. De video staat er al als je die bij de installatie hebt overgenomen. Anders upload je hem ook.
2. **Wachtrijen**: open de bestaande wachtrij of maak een nieuwe, bijvoorbeeld *Bedrijfspand november*. Kies **Media toevoegen** en klik de video en daarna de PNG aan. Vul bij de PNG het aantal seconden in, bijvoorbeeld 15. Laat **Doorlopend herhalen** aan en kies **Opslaan**.
3. **Planning**: kies bij *Als er niets gepland staat* de wachtrij *Bedrijfspand november*.

Wil je dat de nieuwe versie pas maandag begint, maak dan twee wachtrijen. De ene bevat alleen de video en de andere de video met de PNG. Zet de eerste als standaardwachtrij en maak een regel voor de tweede:
- Dagen: **Elke dag**, tijd: **Hele dag**
- Vanaf: de datum van maandag, tot en met: leeg

Vanaf maandag 00:00 speelt dan automatisch de versie met de PNG.

---

## Hoe de planning werkt

- Een **regel** zegt: speel deze wachtrij op deze dagen, van deze tijd tot deze tijd. Je kunt er een begin- en einddatum aan geven.
- Valt de eindtijd op of vóór de begintijd, dan loopt de regel door tot de volgende dag. Een regel van 22:00 tot 06:00 op vrijdag loopt dus tot zaterdagochtend. *Hele dag* betekent van 00:00 tot 24:00.
- Overlappen twee regels, dan **wint de regel die het laatst begon**. Zo kun je een regel voor de hele dag maken en daarbinnen een kortere regel, bijvoorbeeld van 12:00 tot 13:00 voor de lunch. Begint een regel later en loopt hij nog door, dan neemt de andere regel het daarna weer over.
- Staat er niets gepland, dan speelt de **standaardwachtrij**. Heb je die niet ingesteld, dan speelt er niets. Je ziet dan het bureaublad, of een zwart scherm als je dat aanzet.
- Een wachtrij die **één keer** speelt, stopt na het laatste item. Daarna speelt de standaardwachtrij tot de regel afloopt. Hij start niet opnieuw tot de regel de volgende keer begint.
- Bij **Planning** zie je per week precies wat er wanneer speelt. Op de pagina **Nu** staan de komende wissels.

### Handmatig ingrijpen

Op de pagina **Nu** kun je een wachtrij starten of op **Stop** drukken. Die keuze blijft staan tot de planning de volgende keer wisselt of tot je op **Terug naar planning** drukt. Wil je de planning helemaal uitzetten, gebruik dan de schakelaar **Planning actief**. Wat er op dat moment speelt, blijft dan staan.

---

## Beheer op de kiosk

### Ubuntu

| Wat | Commando |
|---|---|
| Status van de dienst | `systemctl status kiosk-player` |
| Logboek bekijken | `journalctl -u kiosk-player -f` |
| Herstarten | `sudo systemctl restart kiosk-player` |
| Stoppen (VLC stopt ook) | `sudo systemctl stop kiosk-player` |
| Wachtwoord vergeten | `sudo -u protectiepartners env KIOSK_DATA_DIR=/home/protectiepartners/kiosk-player python3 /opt/kiosk-player/run.py set-password` en daarna `sudo systemctl restart kiosk-player` |
| Verwijderen (media blijft) | `sudo ./uninstall.sh` |

### Windows

Voer deze commando's uit in PowerShell, als de kioskgebruiker.

| Wat | Commando |
|---|---|
| Status | `Get-ScheduledTask -TaskName 'Kiosk Player'` |
| Logboek bekijken | `Get-Content $env:USERPROFILE\kiosk-player\logs\kiosk-player.log -Wait -Tail 30` |
| Fouten bij het opstarten | `Get-Content $env:USERPROFILE\kiosk-player\logs\stderr.log -Tail 30` |
| Herstarten | `Stop-ScheduledTask 'Kiosk Player'; Start-ScheduledTask 'Kiosk Player'` |
| Stoppen (VLC stopt ook) | `Stop-ScheduledTask 'Kiosk Player'` |
| Wachtwoord vergeten | `& "$env:LOCALAPPDATA\KioskPlayer\.venv\Scripts\python.exe" "$env:LOCALAPPDATA\KioskPlayer\run.py" set-password` en daarna herstarten |
| Verwijderen (media blijft) | `powershell -ExecutionPolicy Bypass -File .\uninstall.ps1` |

### Gegevens

Alle gegevens staan in `~/kiosk-player`, op Windows `%USERPROFILE%\kiosk-player`:

```
~/kiosk-player/
  media/          je video's en afbeeldingen
  data.json       wachtrijen, planning en instellingen
  config.json     poort, wachtwoord-hash en de GitHub-repository voor updates
  logs/           kiosk-player.log en vlc.log (laatste VLC-uitvoer); op Windows ook stderr.log
```

Maak je een **back-up**, kopieer dan die hele map. Wil je de poort wijzigen, pas dan `port` aan in `config.json` en herstart de dienst.

---

## Problemen oplossen

**De webinterface is niet bereikbaar.**
Controleer met `systemctl status kiosk-player` of de dienst draait. Controleer ook of de firewall de poort doorlaat met `sudo ufw status`.
Op Windows kijk je in `kiosk-player\logs\stderr.log`. Controleer ook of het netwerk op *Privé* staat en of de firewallregel *Kiosk Player* bestaat.

**Op de pagina Nu staat dat VLC onverwacht stopte.**
Open *Technische details* onderaan de pagina. Daar staan het precieze VLC-commando en de laatste uitvoer van VLC. Dit zijn de meest voorkomende oorzaken:
- *Niemand is ingelogd op het scherm.* VLC heeft een bureaublad nodig. Zet automatisch inloggen aan voor `protectiepartners` via Instellingen → Gebruikers. Direct na het opstarten probeert Kiosk Player het vanzelf opnieuw, met een steeds langere pauze tot maximaal een minuut.
- *Het display is anders dan `:0`* (alleen Ubuntu). Pas het aan onder **Instellingen**. Het is dezelfde waarde als `DISPLAY=:0` in je ssh-commando.
- *VLC is niet gevonden* (Windows). Onder **Instellingen** staat bij VLC-commando welke vlc.exe Kiosk Player gebruikt. Staat er dat VLC niet gevonden is, installeer VLC dan opnieuw of vul het volledige pad naar vlc.exe in.

**Er is geen geluid.**
Kiosk Player start VLC in de sessie van de gebruiker die is ingelogd. Daardoor gaat het geluid naar de normale geluidsuitgang. Controleer ook of de wachtrij niet op *Geluid uit* staat.

**Het scherm valt na een tijdje uit.**
Zet in Ubuntu bij Instellingen → Energie de optie *Scherm leegmaken* op *Nooit*. Op Windows stel je bij Instellingen → Systeem → Energie het scherm en de slaapstand in op *Nooit*. Dat biedt het installatiescript ook aan.

**Een video speelt niet af in de voorvertoning.**
Sommige formaten, zoals mkv, spelen niet in elke browser. VLC op de kiosk speelt ze wel af.

---

## Veiligheid

- De webinterface gebruikt gewoon http, beveiligd met een wachtwoord. Gebruik hem alleen binnen het eigen netwerk en zet de poort niet open naar internet. Wil je van buitenaf beheren, gebruik dan een VPN.
- Na 5 verkeerde pogingen moet je een minuut wachten voordat je weer kunt inloggen.
- Wijzig je het wachtwoord, dan worden alle andere browsers uitgelogd.
- Onder **Instellingen** kun je als VLC-commando alleen `vlc` of `cvlc` invullen, op Windows ook het pad naar vlc.exe in een programmamap. Als extra opties zijn alleen VLC-opties toegestaan die met `--` beginnen. Opties die andere programma's laden of bestanden wegschrijven worden geweigerd.
- VLC wordt alleen op de kiosk zelf bediend, via een interne poort met een wachtwoord dat elke keer anders is.
- Kiosk Player weigert als root te draaien. Hij draait altijd als de kioskgebruiker. Op Windows draait hij zonder administratorrechten.
- Updates via de website komen alleen uit de ingestelde GitHub-repository (`update_repo` in `config.json`). Iedereen met het wachtwoord van de webinterface kan dus elke branch uit die repository installeren. Geef alleen mensen schrijfrechten op de repository die je dat toevertrouwt.

---

## Techniek

- Het programma is geschreven in Python 3 met Flask en waitress. Op Ubuntu zijn dat de standaardpakketten van Ubuntu 24.04, zonder pip of virtualenv. Op Windows staan ze in een eigen Python-omgeving.
- Op Ubuntu start systemd Kiosk Player en herstart hem als dat nodig is. Op Windows doet de geplande taak dat met `run.py --supervise`.
- VLC wordt gestart als `cvlc --fullscreen --loop …`, op Windows als `vlc.exe --intf=dummy --fullscreen …`. Daarbij komt `--extraintf=http`, zodat vorige, volgende en pauze werken en de pagina Nu ziet wat er speelt. De weergavetijd per afbeelding wordt per bestand meegegeven met `:image-duration=N`.
- Elke 5 seconden bepaalt de planner wat er hoort te spelen. Is dat iets anders dan wat VLC speelt, dan start hij VLC opnieuw met de juiste lijst. Een wissel in de planning kan dus tot 5 seconden later op het scherm komen.
- Wijzig je een wachtrij die op dat moment speelt, dan start VLC direct opnieuw met de nieuwe inhoud.
- De tests voer je uit met `python3 -m pytest tests/`. Op Ubuntu heb je daarvoor `python3-pytest` nodig. GitHub voert ze bij elke push automatisch uit, op Ubuntu en op Windows.
