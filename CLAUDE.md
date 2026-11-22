# CLAUDE.md

Dit bestand geeft Claude Code richtlijnen voor het werken in deze repository.

## Wat dit is

Kiosk Player is een webinterface (Flask) die op een Ubuntu 24.04-kiosk draait en VLC aanstuurt op het scherm in het pand. Gebruikers uploaden media, stellen wachtrijen samen en plannen die in. De gebruikersdocumentatie staat in [README.md](README.md). Alle teksten in de UI, logmeldingen, foutmeldingen en codecommentaar zijn Nederlands. Houd dat zo.

## Commando's

```bash
python3 -m pytest tests/                                   # alle tests
python3 -m pytest tests/test_schedule.py::test_from_monday_onwards   # één test
KIOSK_DATA_DIR=./tmp-data python3 run.py                   # lokaal starten (poort 8080)
KIOSK_DATA_DIR=./tmp-data python3 run.py set-password      # wachtwoord instellen
```

- Er is geen `requirements.txt` of `pyproject.toml`. Bewust: op de kiosk komen de dependencies uit apt (`python3-flask`, `python3-waitress`, `vlc`, `ffmpeg`), dus geen pip of venv. Gebruik geen andere pakketten dan wat Ubuntu 24.04 meelevert, en de standaardbibliotheek.
- Waitress is optioneel. Ontbreekt het, dan valt `main()` terug op de ingebouwde server van Flask.
- Er is geen linter of formatter geconfigureerd. Er is ook geen build-stap voor de frontend.
- CI ([.github/workflows/tests.yml](.github/workflows/tests.yml)) draait de tests bij elke push op Ubuntu 24.04, met dezelfde apt-pakketten als de kiosk.
- De ontwikkelmachine is Windows, maar de app is alleen voor Linux bedoeld. `os.geteuid`, `os.killpg`, `pkill` en `/run/user/<uid>` bestaan niet op Windows. De app zelf start daarom niet op Windows, maar alle tests draaien daar wel. Lokaal heb je daarvoor `pytest` en `flask` nodig.
- [install.sh](install.sh) installeert of werkt bij op de kiosk. Het kopieert `app/` en `run.py` naar `/opt/kiosk-player`, schrijft `VERSION.json` en maakt de kioskgebruiker eigenaar van die map. Dat laatste is nodig voor updates via de website. Daarna maakt het de systemd-dienst `kiosk-player` aan, die draait als de kioskgebruiker. [uninstall.sh](uninstall.sh) verwijdert het programma en laat de gegevensmap staan, behalve met `--alles`.

## Architectuur

Eén proces met drie soorten threads: de webserver, de planner-lus in `Controller` en de media-worker in `MediaLibrary`.

- [run.py](run.py) is het startpunt. Het roept eerst `guard_update()` aan en daarna `app.server.main`. `guard_update()` zet een update via de website terug als die niet start, zie [Updates via de website](#updates-via-de-website).
- [app/server.py](app/server.py) bevat `create_app(data_dir)`, die alle objecten opbouwt en alle Flask-routes definieert (pagina's, `/api/...`, `/media/...`, `/thumb/...`). Ook de invoervalidatie zit hier (`_str`, `_time`, `_date`, `ApiError`). Verder login, de beveiliging in `before_request`, logging en `main()`.
- [app/controller.py](app/controller.py) is de regisseur. Elke `TICK` (5 s), of direct na `poke()`, bepaalt `desired()` wat er hoort te spelen. Dat gebeurt in deze volgorde: handmatige override, dan het tijdvak uit de planning, dan `finished_key` voor wachtrijen die één keer spelen, en anders de standaardwachtrij. `build_spec()` maakt daar een `PlaySpec` van. Wijkt `spec.signature()` af van wat VLC draait, dan start VLC opnieuw. Crasht VLC, dan volgt een backoff van 5 s, daarna steeds dubbel zo lang, tot maximaal 60 s.
- [app/player.py](app/player.py) beheert het VLC-proces (`cvlc`), met de omgeving voor X11/XWayland, geluid en D-Bus. VLC wordt bediend via de HTTP-interface op 127.0.0.1 met een willekeurig wachtwoord per start. De afbeeldingsduur gaat per item mee als `:image-duration=N`.
- [app/schedule.py](app/schedule.py) bevat pure functies zonder I/O: `resolve`, `timeline` en `upcoming_changes`. Overlappen regels, dan wint de regel die het laatst begon, daarna de kortste, dan het kleinste datumbereik en dan de nieuwste. Eindigt een regel op of vóór zijn begintijd, dan loopt hij door tot de volgende dag. `Slot.key` is per keer dat een regel voorkomt uniek, en override en `finished_key` zijn daarop gebaseerd.
- [app/store.py](app/store.py) regelt de opslag. `Store` gebruikt `data.json` (wachtrijen, regels, instellingen, runtime) en `Config` gebruikt `config.json` (poort, wachtwoord-hash, sessiesleutel). Alles wordt geschreven via `atomic_write_json`.
- [app/media.py](app/media.py) bevat de mediabibliotheek. Een achtergrond-worker haalt met ffprobe en ffmpeg de duur, de resolutie en een miniatuur op. Die gegevens komen in `media.json`. `path_for()` is de enige toegestane manier om een bestandsnaam om te zetten naar een pad, want hij blokkeert path traversal.
- [app/updater.py](app/updater.py) regelt de software-update via GitHub: branches ophalen, een commit downloaden als tarball, die controleren, `app/` omwisselen en herstarten. De routes zijn `/api/update...` in `server.py`, en het paneel **Software-update** staat op de pagina Instellingen.
- [app/static/](app/static/) is de frontend: een single-page app in vanilla JS zonder framework of build. [app.js](app/static/app.js) routeert op de hash (`#nu`, `#media`, `#wachtrijen`, `#planning`, `#instellingen`) en pollt `/api/state` elke 2,5 s.

### Gegevensmap

Die staat in `KIOSK_DATA_DIR`, standaard `~/kiosk-player`, en bevat `media/`, `thumbs/`, `logs/`, `data.json`, `media.json`, `config.json` en `zwart.png`. Nieuwe instellingen voeg je toe aan `DEFAULT_SETTINGS` of `DEFAULT_CONFIG` in `store.py`. Bestaande bestanden worden met die defaults samengevoegd, dus een update blijft compatibel met oude data. Houd dat zo: installaties worden bijgewerkt met behoud van de data.

### Updates via de website

In het paneel **Software-update** kies je een branch van de repository uit `update_repo` in `config.json` (standaard `luukderooij/Kiosk-player`). Kiosk Player installeert dan de nieuwste commit van die branch. Zo test je ook een andere branch op de kiosk. De update loopt zo:

1. **Branch controleren.** De gekozen branch moet in de branchlijst van GitHub staan. Daarna werkt de updater alleen nog met de commit-sha, dus er komt geen vrije invoer in een URL. De download komt van `codeload.github.com` en mag maximaal 50 MB zijn.
2. **Uitpakken en controleren.** Het archief wordt uitgepakt met `filter="data"`. Daarna voert `Updater.verify()` drie controles uit. De vereiste bestanden moeten er zijn, waaronder `app/updater.py`, zodat je niet per ongeluk een versie zonder updatefunctie installeert. Elk `.py`-bestand moet compileren. En `import app.server` moet slagen in een apart proces.
3. **Omwisselen.** `app/` wordt `app.prev/` en de nieuwe `app/` komt ervoor in de plaats. Dan worden `VERSION.json` en `update-state.json` (`status: trial`) geschreven.
4. **Herstarten.** Het proces stopt VLC en sluit af met `os._exit(0)`. Systemd start het opnieuw, dankzij `Restart=always`.
5. **Automatisch terugzetten.** Bij elke start telt `run.py` de pogingen zolang de status `trial` is. Draait de nieuwe versie 30 seconden, dan wordt de status `ok`. Start hij 3 keer niet goed op, dan zet `run.py` `app.prev/` terug en wordt de status `rolled_back`. De interface laat dat daarna zien.

Programmamap op de kiosk (`/opt/kiosk-player`, eigendom van de kioskgebruiker):

```
app/  app.prev/  app.failed/  .staging/  run.py  VERSION.json  update-state.json
```

Regels hierbij:
- **`run.py`** wordt alleen door `install.sh` bijgewerkt, nooit door de website. Anders kan een kapotte versie ook de terugzetting kapotmaken. Houd het klein en gebruik er alleen de standaardbibliotheek in. Wijzigingen in `run.py`, `install.sh`, de systemd-unit of apt-pakketten komen dus pas op de kiosk na `sudo ./install.sh`.
- **Wanneer updaten weigert.** Updaten weigert met een melding in `Updater.problem()` als de map een git-checkout is (een ontwikkelmap), als de programmamap niet schrijfbaar is (een oude installatie: draai dan eenmalig `install.sh` opnieuw), of als het proces niet onder systemd draait (`INVOCATION_ID` ontbreekt).
- **Oude data.** Andere branches lezen dezelfde `data.json`. Een oudere versie moet onbekende velden laten staan. `Store` doet dat nu al, want het voegt bestaande data samen met de defaults. Verwijder velden nooit zonder migratie.
- **Privé-repository.** Zet dan `github_token` in `config.json`. Dat kan alleen in het bestand, niet via de website. Zonder token mag de kiosk 60 GitHub-verzoeken per uur doen. Antwoorden worden 60 seconden gecachet.

## Afspraken en valkuilen

- **Locking:** wie `store.data` wijzigt, houdt `store.lock` vast (een RLock) en roept daarna `store.save()` aan. Roep na een wijziging die invloed heeft op wat er speelt `controller.poke()` of `controller.tick()` aan. Er is een tweede lock, `Controller.tick_lock`. Neem altijd eerst `tick_lock` en dan `store.lock`, nooit andersom, en roep `tick()` niet aan terwijl je `store.lock` vasthoudt. VLC starten of stoppen gebeurt alleen onder `tick_lock` en nooit onder `store.lock`, zodat de API en `status()` niet wachten op VLC.
- **Sessies:** een sessie bevat een afgeleide van de wachtwoord-hash (`pw_tag()` in `server.py`). Wijzig je het wachtwoord, dan zijn alle andere sessies daardoor ongeldig.
- **VLC-instellingen:** `vlc_command` moet `vlc` of `cvlc` zijn, en de extra opties moeten met `--` beginnen. Opties die code laden, de interne bediening overnemen of bestanden wegschrijven staan in `BLOCKED_VLC_OPTIONS` en worden geweigerd. Zo kan de webinterface geen willekeurige commando's uitvoeren.
- **CSRF:** elke POST, PUT en DELETE op `/api/` vereist de header `X-Requested-With: kiosk`. De `api()`-helper in `app.js` stuurt die mee. Nieuwe fetch- of XHR-aanroepen moeten dat ook doen.
- **Validatie:** valideer invoer in `server.py` met de bestaande helpers en gooi `ApiError` met een Nederlandse melding. De frontend toont `error` uit de JSON-respons.
- **Root:** de app weigert als root te draaien, omdat VLC dat niet wil. Alleen met `KIOSK_ALLOW_ROOT=1` lukt het wel.
- **Tests:** er zijn vier testbestanden. [test_schedule.py](tests/test_schedule.py) test de planningsregels; houd `schedule.py` vrij van I/O. [test_controller.py](tests/test_controller.py) test de regisseur met een `FakePlayer` in plaats van VLC. [test_server.py](tests/test_server.py) test login, sessies en validatie met de Flask-testclient. [test_updater.py](tests/test_updater.py) test de update en de terugzetting in `run.py` met een nep-GitHub (`FakeGitHub`), dus zonder netwerk. Voeg een test toe als je de planning, de logica in `desired()`, de beveiliging of de update wijzigt.
- **Documentatie:** verandert gedrag dat gebruikers zien, zoals de planning, de installatie of de instellingen, werk dan ook [README.md](README.md) bij.
- De repository staat in een OneDrive-map. Zet testdata (`tmp-data/`), media en caches niet in git.
