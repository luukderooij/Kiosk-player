# Kiosk Player

Een webinterface om het scherm in het pand te beheren. Hij draait op de Ubuntu 24.04-kiosk zelf en start VLC voor je.
Je hebt er geen ssh-commando's meer voor nodig.

- **Media**: video's en afbeeldingen uploaden vanuit de browser, met voorbeeldplaatjes en de duur.
- **Wachtrijen**: zet bestanden in een vaste volgorde en kies per afbeelding hoeveel seconden die in beeld blijft. Een wachtrij kan doorlopend herhalen of één keer spelen.
- **Planning**: kies welke wachtrij op welke dagen en tijden speelt, eventueel alleen binnen een periode. Daarnaast stel je een standaardwachtrij in voor de rest van de tijd.
- **Nu**: zie wat er op het scherm staat en bedien VLC met vorige, pauze, volgende, stop en herstart. Je kunt ook direct een wachtrij starten.
- Stopt VLC onverwacht, dan start Kiosk Player hem vanzelf opnieuw.

---

## Installeren

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

### Bijwerken

Pak de nieuwe versie uit en voer `sudo ./install.sh protectiepartners` opnieuw uit. Je media, wachtrijen, planning en wachtwoord blijven bewaard.

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

| Wat | Commando |
|---|---|
| Status van de dienst | `systemctl status kiosk-player` |
| Logboek bekijken | `journalctl -u kiosk-player -f` |
| Herstarten | `sudo systemctl restart kiosk-player` |
| Stoppen (VLC stopt ook) | `sudo systemctl stop kiosk-player` |
| Wachtwoord vergeten | `sudo -u protectiepartners env KIOSK_DATA_DIR=/home/protectiepartners/kiosk-player python3 /opt/kiosk-player/run.py set-password` en daarna `sudo systemctl restart kiosk-player` |
| Verwijderen (media blijft) | `sudo ./uninstall.sh` |

Alle gegevens staan in `~/kiosk-player`:

```
~/kiosk-player/
  media/          je video's en afbeeldingen
  data.json       wachtrijen, planning en instellingen
  config.json     poort en wachtwoord-hash
  logs/           kiosk-player.log en vlc.log (laatste VLC-uitvoer)
```

Maak je een **back-up**, kopieer dan die hele map. Wil je de poort wijzigen, pas dan `port` aan in `config.json` en herstart de dienst.

---

## Problemen oplossen

**De webinterface is niet bereikbaar.**
Controleer met `systemctl status kiosk-player` of de dienst draait. Controleer ook of de firewall de poort doorlaat met `sudo ufw status`.

**Op de pagina Nu staat dat VLC onverwacht stopte.**
Open *Technische details* onderaan de pagina. Daar staan het precieze VLC-commando en de laatste uitvoer van VLC. Dit zijn de meest voorkomende oorzaken:
- *Niemand is ingelogd op het scherm.* VLC heeft een bureaublad nodig. Zet automatisch inloggen aan voor `protectiepartners` via Instellingen → Gebruikers. Direct na het opstarten probeert Kiosk Player het vanzelf opnieuw, met een steeds langere pauze tot maximaal een minuut.
- *Het display is anders dan `:0`.* Pas het aan onder **Instellingen**. Het is dezelfde waarde als `DISPLAY=:0` in je ssh-commando.

**Er is geen geluid.**
Kiosk Player start VLC in de sessie van de gebruiker die is ingelogd. Daardoor gaat het geluid naar de normale geluidsuitgang. Controleer ook of de wachtrij niet op *Geluid uit* staat.

**Het scherm valt na een tijdje uit.**
Zet in Ubuntu bij Instellingen → Energie de optie *Scherm leegmaken* op *Nooit*.

**Een video speelt niet af in de voorvertoning.**
Sommige formaten, zoals mkv, spelen niet in elke browser. VLC op de kiosk speelt ze wel af.

---

## Veiligheid

- De webinterface gebruikt gewoon http, beveiligd met een wachtwoord. Gebruik hem alleen binnen het eigen netwerk en zet de poort niet open naar internet. Wil je van buitenaf beheren, gebruik dan een VPN.
- Na 5 verkeerde pogingen moet je een minuut wachten voordat je weer kunt inloggen.
- Wijzig je het wachtwoord, dan worden alle andere browsers uitgelogd.
- Onder **Instellingen** kun je als VLC-commando alleen `vlc` of `cvlc` invullen, en als extra opties alleen VLC-opties die met `--` beginnen. Opties die andere programma's laden of bestanden wegschrijven worden geweigerd.
- VLC wordt alleen op de kiosk zelf bediend, via een interne poort met een wachtwoord dat elke keer anders is.
- Kiosk Player weigert als root te draaien. Hij draait altijd als de kioskgebruiker.

---

## Techniek

- Het programma is geschreven in Python 3 met Flask en waitress, de standaardpakketten van Ubuntu 24.04. Er is geen pip of virtualenv nodig.
- VLC wordt gestart als `cvlc --fullscreen --loop …` met `--extraintf=http`, zodat vorige, volgende en pauze werken en de pagina Nu ziet wat er speelt. De weergavetijd per afbeelding wordt per bestand meegegeven met `:image-duration=N`.
- Elke 5 seconden bepaalt de planner wat er hoort te spelen. Is dat iets anders dan wat VLC speelt, dan start hij VLC opnieuw met de juiste lijst. Een wissel in de planning kan dus tot 5 seconden later op het scherm komen.
- Wijzig je een wachtrij die op dat moment speelt, dan start VLC direct opnieuw met de nieuwe inhoud.
- De tests voer je uit met `python3 -m pytest tests/`. Op Ubuntu heb je daarvoor `python3-pytest` nodig. GitHub voert ze bij elke push automatisch uit.
