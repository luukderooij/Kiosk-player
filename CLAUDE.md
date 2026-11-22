# CLAUDE.md

Dit bestand geeft Claude Code richtlijnen voor het werken in deze repository.

## Wat dit is

Kiosk Player is een webinterface (Flask) die VLC aanstuurt op het scherm in het pand. Hij draait op een Ubuntu 24.04-kiosk of op een Windows 10/11-pc. Gebruikers uploaden media, stellen wachtrijen samen en plannen die in. De gebruikersdocumentatie staat in [README.md](README.md). Alle teksten in de UI, logmeldingen, foutmeldingen en codecommentaar zijn Nederlands. Houd dat zo.

## Commando's

```bash
python -m pytest tests/                                    # alle tests (op Linux: python3)
python -m pytest tests/test_schedule.py::test_from_monday_onwards   # één test
KIOSK_DATA_DIR=./tmp-data python run.py                    # lokaal starten (poort 8080)
KIOSK_DATA_DIR=./tmp-data python run.py set-password       # wachtwoord instellen
KIOSK_DATA_DIR=./tmp-data python run.py --supervise        # met supervisor, zoals op Windows
```

- **Dependencies per platform.** Op Linux komen ze uit apt (`python3-flask`, `python3-waitress`, `vlc`, `ffmpeg`), zonder pip of venv. Gebruik daar geen pakketten die Ubuntu 24.04 niet meelevert. Op Windows maakt `install.ps1` een venv met `flask>=3,<4` en `waitress>=3,<4`; VLC, ffmpeg en Python komen via winget. Een nieuwe dependency moet dus in beide installatiescripts, en moet op Ubuntu 24.04 als apt-pakket bestaan.
- Waitress is optioneel. Ontbreekt het, dan valt `main()` terug op de ingebouwde server van Flask.
- Er is geen linter of formatter geconfigureerd. Er is ook geen build-stap voor de frontend.
- CI ([.github/workflows/tests.yml](.github/workflows/tests.yml)) draait de tests bij elke push op Ubuntu 24.04 (apt-pakketten, zoals de kiosk) en op Windows (pip, zoals `install.ps1`). Daar controleert hij ook de syntaxis van `install.sh` en de PowerShell-scripts.
- De ontwikkelmachine is Windows. De app start daar ook gewoon, en alle tests draaien op beide platforms. Lokaal heb je `pytest` en `flask` nodig.
- [install.sh](install.sh) installeert of werkt bij op Linux. Het kopieert `app/` en `run.py` naar `/opt/kiosk-player`, schrijft `VERSION.json` en maakt de kioskgebruiker eigenaar van die map, wat nodig is voor updates via de website. Daarna maakt het de systemd-dienst `kiosk-player` aan. [uninstall.sh](uninstall.sh) verwijdert het programma en laat de gegevensmap staan, behalve met `--alles`.
- [install.ps1](install.ps1) doet hetzelfde op Windows, zonder admin. Het installeert naar `%LOCALAPPDATA%\KioskPlayer` met een venv in `.venv\`, en maakt de geplande taak **Kiosk Player**. Die start bij het inloggen `pythonw.exe run.py --supervise`. Lukt de taak niet, dan komt er een snelkoppeling in de map Opstarten. Voor de firewallregel (alleen de profielen Privé en Domein) en VLC vraagt Windows om toestemming. [uninstall.ps1](uninstall.ps1) verwijdert het weer, met `-Alles` ook de data.
- **De `.ps1`-bestanden bevatten alleen ASCII.** Windows PowerShell 5.1 leest een bestand zonder BOM als ANSI, dus schrijf `geinstalleerd` in plaats van `geïnstalleerd`. CI controleert dit.

## Architectuur

Eén proces met drie soorten threads: de webserver, de planner-lus in `Controller` en de media-worker in `MediaLibrary`.

- [run.py](run.py) is het startpunt. Normaal roept het eerst `guard_update()` aan en daarna `app.server.main`. `guard_update()` zet een update via de website terug als die niet start, zie [Updates via de website](#updates-via-de-website). Met `--supervise` (Windows) start het zichzelf als kindproces en herstart het dat na afsluiten, zie [Windows](#windows).
- [app/system.py](app/system.py) bevat alles wat per besturingssysteem verschilt: VLC en ffmpeg zoeken, VLC starten en stoppen, andere VLC's sluiten, de omgeving voor VLC, en weten of er een supervisor is. Lees het platform altijd als `system.IS_WINDOWS`, nooit als kopie, zodat tests het andere platform kunnen nabootsen. Nieuwe platformverschillen horen hier, niet verspreid door de code.
- [app/server.py](app/server.py) bevat `create_app(data_dir)`, die alle objecten opbouwt en alle Flask-routes definieert (pagina's, `/api/...`, `/media/...`, `/thumb/...`). Ook de invoervalidatie zit hier (`_str`, `_time`, `_date`, `ApiError`). Verder login, de beveiliging in `before_request`, logging en `main()`. `main()` controleert eerst of de poort vrij is, zodat een tweede exemplaar niet het VLC van het eerste sluit.
- [app/controller.py](app/controller.py) is de regisseur. Elke `TICK` (5 s), of direct na `poke()`, bepaalt `desired()` wat er hoort te spelen. Dat gebeurt in deze volgorde: handmatige override, dan het tijdvak uit de planning, dan `finished_key` voor wachtrijen die één keer spelen, en anders de standaardwachtrij. `build_spec()` maakt daar een `PlaySpec` van. Wijkt `spec.signature()` af van wat VLC draait, dan start VLC opnieuw. Crasht VLC, dan volgt een backoff van 5 s, daarna steeds dubbel zo lang, tot maximaal 60 s.
- [app/player.py](app/player.py) beheert het VLC-proces via `system`. Op Linux is dat `cvlc` met de X11/XWayland-omgeving, op Windows `vlc.exe --intf=dummy`. VLC wordt bediend via de HTTP-interface op 127.0.0.1 met een willekeurig wachtwoord per start. De afbeeldingsduur gaat per item mee als `:image-duration=N`.
- [app/schedule.py](app/schedule.py) bevat pure functies zonder I/O: `resolve`, `timeline` en `upcoming_changes`. Overlappen regels, dan wint de regel die het laatst begon, daarna de kortste, dan het kleinste datumbereik en dan de nieuwste. Eindigt een regel op of vóór zijn begintijd, dan loopt hij door tot de volgende dag. `Slot.key` is per keer dat een regel voorkomt uniek, en override en `finished_key` zijn daarop gebaseerd.
- [app/store.py](app/store.py) regelt de opslag. `Store` gebruikt `data.json` (wachtrijen, regels, instellingen, runtime) en `Config` gebruikt `config.json` (poort, wachtwoord-hash, sessiesleutel, `update_repo`, `github_token`). Alles wordt geschreven via `atomic_write_json`, dat op Windows een paar keer opnieuw probeert als een virusscanner of OneDrive het bestand vasthoudt.
- [app/media.py](app/media.py) bevat de mediabibliotheek. Een achtergrond-worker haalt met ffprobe en ffmpeg de duur, de resolutie en een miniatuur op. Die gegevens komen in `media.json`. `path_for()` is de enige toegestane manier om een bestandsnaam om te zetten naar een pad, want hij blokkeert path traversal.
- [app/updater.py](app/updater.py) regelt de software-update via GitHub: branches ophalen, een commit downloaden als tarball, die controleren, `app/` omwisselen en herstarten. De routes zijn `/api/update...` in `server.py`, en het paneel **Software-update** staat op de pagina Instellingen.
- [app/static/](app/static/) is de frontend: een single-page app in vanilla JS zonder framework of build. [app.js](app/static/app.js) routeert op de hash (`#nu`, `#media`, `#wachtrijen`, `#planning`, `#instellingen`) en pollt `/api/state` elke 2,5 s. `/api/all` geeft `info.platform` (`linux` of `windows`), waarmee de instellingen het veld Display verbergen en andere hulpteksten tonen.

### Gegevensmap

Die staat in `KIOSK_DATA_DIR`, standaard `~/kiosk-player` (op Windows `%USERPROFILE%\kiosk-player`). Hij bevat `media/`, `thumbs/`, `logs/`, `data.json`, `media.json`, `config.json` en `zwart.png`, en op Windows ook `logs/stderr.log` van de supervisor. Nieuwe instellingen voeg je toe aan `DEFAULT_SETTINGS` of `DEFAULT_CONFIG` in `store.py`. Bestaande bestanden worden met die defaults samengevoegd, dus een update blijft compatibel met oude data. Houd dat zo: installaties worden bijgewerkt met behoud van de data.

### Windows

Windows heeft geen systemd, daarom vervangt `run.py --supervise` die rol:

- **Supervisor.** De supervisor start `python.exe run.py` als kindproces, met `KIOSK_SUPERVISED=1`, `CREATE_NO_WINDOW` en een pijp als stdin. Na afsluiten (update, crash) start hij het kind opnieuw, na 2, 4, 6 tot maximaal 30 seconden. De uitvoer van het kind komt in `logs/stderr.log`. Een lock op `supervisor.lock` zorgt dat er maar één supervisor draait.
- **Stoppen.** Stopt de supervisor, dan sluit de pijp. `watch_supervisor()` in `server.py` merkt dat, stopt VLC en sluit het kind af. Er blijft dus geen los proces achter. Dat is getest door de supervisor hard te stoppen.
- **Elk subproces krijgt `**system.child_kwargs()`**, dus `stdin=DEVNULL` en geen consolevenster. Onder de supervisor leest een thread op de stdin-pijp. Een kind dat die pijp erft, blijft op Windows bij het opstarten hangen, omdat bewerkingen op zo'n synchrone pijp op elkaar wachten. Dit gebeurde echt met de importcontrole van de updater, en `test_without_devnull_it_hangs_on_windows` bewijst het. VLC zelf krijgt `system.popen_kwargs()`.
- **VLC-commando.** Op Windows is `vlc_command` één programma: `vlc` (zoek `vlc.exe` op, de standaard `cvlc` betekent hier hetzelfde) of een volledig pad naar `vlc.exe` in Program Files of `%LOCALAPPDATA%\Programs`. Splits het niet met `shlex`, want dat breekt de backslashes. De validatie staat in `validate_vlc_command`.
- **Wachtwoord via een pijp.** Windows PowerShell 5.1 zet een BOM voor tekst die naar een programma wordt gepipet. `set-password` leest stdin daarom als `utf-8-sig`.

### Updates via de website

In het paneel **Software-update** kies je een branch van de repository uit `update_repo` in `config.json` (standaard `luukderooij/Kiosk-player`). Kiosk Player installeert dan de nieuwste commit van die branch. Zo test je ook een andere branch op de kiosk. De update loopt zo:

1. **Branch controleren.** De gekozen branch moet in de branchlijst van GitHub staan. Daarna werkt de updater alleen nog met de commit-sha, dus er komt geen vrije invoer in een URL. De download komt van `codeload.github.com` en mag maximaal 50 MB zijn.
2. **Uitpakken en controleren.** Het archief wordt uitgepakt met `filter="data"`. Daarna voert `Updater.verify()` drie controles uit. De vereiste bestanden moeten er zijn, waaronder `app/updater.py`, zodat je niet per ongeluk een versie zonder updatefunctie installeert. Elk `.py`-bestand moet compileren. En `import app.server` moet slagen in een apart proces.
3. **Omwisselen.** `app/` wordt `app.prev/` en de nieuwe `app/` komt ervoor in de plaats, met `system.rename`, dat op Windows een paar keer opnieuw probeert. Dan worden `VERSION.json` en `update-state.json` (`status: trial`) geschreven.
4. **Herstarten.** Het proces stopt VLC en sluit af met `os._exit(0)`. Daarna start systemd (`Restart=always`) of de supervisor het opnieuw.
5. **Automatisch terugzetten.** Bij elke start telt `run.py` de pogingen zolang de status `trial` is. Draait de nieuwe versie 30 seconden, dan wordt de status `ok`. Start hij 3 keer niet goed op, dan zet `run.py` `app.prev/` terug en wordt de status `rolled_back`. De interface laat dat daarna zien. Op Windows is dit end-to-end getest: een update naar een versie die daar crasht, was na ongeveer een minuut automatisch teruggezet. Dat was met de oude wachttijden; met de huidige gaat het sneller.

Programmamap (Linux `/opt/kiosk-player`, eigendom van de kioskgebruiker; Windows `%LOCALAPPDATA%\KioskPlayer`):

```
app/  app.prev/  app.failed/  .staging/  run.py  VERSION.json  update-state.json
(Windows ook: .venv/  supervisor.lock)
```

Regels hierbij:
- **`run.py`** wordt alleen door de installatiescripts bijgewerkt, nooit door de website. Anders kan een kapotte versie ook de terugzetting kapotmaken. Houd het klein en gebruik er alleen de standaardbibliotheek in. Wijzigingen in `run.py`, de installatiescripts, de systemd-unit of de dependencies komen dus pas op de kiosk na opnieuw `install.sh` of `install.ps1`.
- **Wanneer updaten weigert.** Updaten weigert met een melding in `Updater.problem()` als de map een git-checkout is (een ontwikkelmap), als de programmamap niet schrijfbaar is (een oude installatie: draai dan eenmalig het installatiescript opnieuw), of als er geen supervisor is (`system.supervised()`: `INVOCATION_ID` van systemd of `KIOSK_SUPERVISED=1`).
- **Oude data.** Andere branches lezen dezelfde `data.json`. Een oudere versie moet onbekende velden laten staan. `Store` doet dat nu al, want het voegt bestaande data samen met de defaults. Verwijder velden nooit zonder migratie.
- **Privé-repository.** Zet dan `github_token` in `config.json`. Dat kan alleen in het bestand, niet via de website. Zonder token mag de kiosk 60 GitHub-verzoeken per uur doen. Antwoorden worden 60 seconden gecachet.

## Afspraken en valkuilen

- **Locking:** wie `store.data` wijzigt, houdt `store.lock` vast (een RLock) en roept daarna `store.save()` aan. Roep na een wijziging die invloed heeft op wat er speelt `controller.poke()` of `controller.tick()` aan. Er is een tweede lock, `Controller.tick_lock`. Neem altijd eerst `tick_lock` en dan `store.lock`, nooit andersom, en roep `tick()` niet aan terwijl je `store.lock` vasthoudt. VLC starten of stoppen gebeurt alleen onder `tick_lock` en nooit onder `store.lock`, zodat de API en `status()` niet wachten op VLC.
- **Sessies:** een sessie bevat een afgeleide van de wachtwoord-hash (`pw_tag()` in `server.py`). Wijzig je het wachtwoord, dan zijn alle andere sessies daardoor ongeldig.
- **VLC-instellingen:** op Linux moet `vlc_command` `vlc` of `cvlc` zijn; voor Windows, zie [Windows](#windows). De extra opties moeten met `--` beginnen. Opties die code laden, de interne bediening overnemen of bestanden wegschrijven staan in `BLOCKED_VLC_OPTIONS` en worden geweigerd. Zo kan de webinterface geen willekeurige commando's uitvoeren.
- **CSRF:** elke POST, PUT en DELETE op `/api/` vereist de header `X-Requested-With: kiosk`. De `api()`-helper in `app.js` stuurt die mee. Nieuwe fetch- of XHR-aanroepen moeten dat ook doen.
- **Validatie:** valideer invoer in `server.py` met de bestaande helpers en gooi `ApiError` met een Nederlandse melding. De frontend toont `error` uit de JSON-respons.
- **Root:** op Linux weigert de app als root te draaien, omdat VLC dat niet wil. Alleen met `KIOSK_ALLOW_ROOT=1` lukt het wel.
- **Tests:** er zijn vijf testbestanden. [test_schedule.py](tests/test_schedule.py) test de planningsregels; houd `schedule.py` vrij van I/O. [test_controller.py](tests/test_controller.py) test de regisseur met een `FakePlayer` in plaats van VLC. [test_server.py](tests/test_server.py) test login, sessies, `set-password` en validatie met de Flask-testclient, met de fixtures `linux` en `windows` voor platformgedrag. [test_updater.py](tests/test_updater.py) test de update en de terugzetting in `run.py` met een nep-GitHub (`FakeGitHub`), dus zonder netwerk. [test_system.py](tests/test_system.py) test de platformlaag, de supervisorlock en de stdin-hang. Voeg een test toe als je de planning, de logica in `desired()`, de beveiliging, de update of platformgedrag wijzigt.
- **Niet getest op echte hardware:** VLC schermvullend op een Windows-kiosk (`--intf=dummy`), `install.ps1` op een schone pc, en de geplande taak. Controleer dat bij wijzigingen daaraan met de hand.
- **Documentatie:** verandert gedrag dat gebruikers zien, zoals de planning, de installatie of de instellingen, werk dan ook [README.md](README.md) bij.
- De repository staat in een OneDrive-map. Zet testdata (`tmp-data/`), media en caches niet in git.
