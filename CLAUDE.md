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
- De ontwikkelmachine is Windows, maar de app is alleen voor Linux bedoeld. `os.geteuid`, `os.killpg`, `pkill` en `/run/user/<uid>` bestaan niet op Windows. De app zelf start daarom niet op Windows. Alleen de tests (pure schema-logica) draaien daar wel.
- [install.sh](install.sh) installeert of werkt bij op de kiosk: kopieert `app/` en `run.py` naar `/opt/kiosk-player` en maakt de systemd-dienst `kiosk-player` aan, die draait als de kioskgebruiker. [uninstall.sh](uninstall.sh) verwijdert het programma en laat de gegevensmap staan, behalve met `--alles`.

## Architectuur

Eén proces met drie soorten threads: de webserver, de planner-lus in `Controller` en de media-worker in `MediaLibrary`.

- [run.py](run.py) is het startpunt en roept `app.server.main` aan.
- [app/server.py](app/server.py) bevat `create_app(data_dir)`, die alle objecten opbouwt en alle Flask-routes definieert (pagina's, `/api/...`, `/media/...`, `/thumb/...`). Ook de invoervalidatie zit hier (`_str`, `_time`, `_date`, `ApiError`). Verder login, de beveiliging in `before_request`, logging en `main()`.
- [app/controller.py](app/controller.py) is de regisseur. Elke `TICK` (5 s), of direct na `poke()`, bepaalt `desired()` wat er hoort te spelen. Dat gebeurt in deze volgorde: handmatige override, dan het tijdvak uit de planning, dan `finished_key` voor wachtrijen die één keer spelen, en anders de standaardwachtrij. `build_spec()` maakt daar een `PlaySpec` van. Wijkt `spec.signature()` af van wat VLC draait, dan start VLC opnieuw. Crasht VLC, dan volgt een backoff van 5 s, daarna steeds dubbel zo lang, tot maximaal 60 s.
- [app/player.py](app/player.py) beheert het VLC-proces (`cvlc`), met de omgeving voor X11/XWayland, geluid en D-Bus. VLC wordt bediend via de HTTP-interface op 127.0.0.1 met een willekeurig wachtwoord per start. De afbeeldingsduur gaat per item mee als `:image-duration=N`.
- [app/schedule.py](app/schedule.py) bevat pure functies zonder I/O: `resolve`, `timeline` en `upcoming_changes`. Overlappen regels, dan wint de regel die het laatst begon, daarna de kortste, dan het kleinste datumbereik en dan de nieuwste. Eindigt een regel op of vóór zijn begintijd, dan loopt hij door tot de volgende dag. `Slot.key` is per keer dat een regel voorkomt uniek, en override en `finished_key` zijn daarop gebaseerd.
- [app/store.py](app/store.py) regelt de opslag. `Store` gebruikt `data.json` (wachtrijen, regels, instellingen, runtime) en `Config` gebruikt `config.json` (poort, wachtwoord-hash, sessiesleutel). Alles wordt geschreven via `atomic_write_json`.
- [app/media.py](app/media.py) bevat de mediabibliotheek. Een achtergrond-worker haalt met ffprobe en ffmpeg de duur, de resolutie en een miniatuur op. Die gegevens komen in `media.json`. `path_for()` is de enige toegestane manier om een bestandsnaam om te zetten naar een pad, want hij blokkeert path traversal.
- [app/static/](app/static/) is de frontend: een single-page app in vanilla JS zonder framework of build. [app.js](app/static/app.js) routeert op de hash (`#nu`, `#media`, `#wachtrijen`, `#planning`, `#instellingen`) en pollt `/api/state` elke 2,5 s.

### Gegevensmap

Die staat in `KIOSK_DATA_DIR`, standaard `~/kiosk-player`, en bevat `media/`, `thumbs/`, `logs/`, `data.json`, `media.json`, `config.json` en `zwart.png`. Nieuwe instellingen voeg je toe aan `DEFAULT_SETTINGS` of `DEFAULT_CONFIG` in `store.py`. Bestaande bestanden worden met die defaults samengevoegd, dus een update blijft compatibel met oude data. Houd dat zo: installaties worden bijgewerkt met behoud van de data.

## Afspraken en valkuilen

- **Locking:** wie `store.data` wijzigt, houdt `store.lock` vast (een RLock) en roept daarna `store.save()` aan. Roep na een wijziging die invloed heeft op wat er speelt `controller.poke()` of `controller.tick()` aan.
- **CSRF:** elke POST, PUT en DELETE op `/api/` vereist de header `X-Requested-With: kiosk`. De `api()`-helper in `app.js` stuurt die mee. Nieuwe fetch- of XHR-aanroepen moeten dat ook doen.
- **Validatie:** valideer invoer in `server.py` met de bestaande helpers en gooi `ApiError` met een Nederlandse melding. De frontend toont `error` uit de JSON-respons.
- **Root:** de app weigert als root te draaien, omdat VLC dat niet wil. Alleen met `KIOSK_ALLOW_ROOT=1` lukt het wel.
- **Tests:** er zijn alleen tests voor `schedule.py`. Houd die module vrij van I/O, zodat de tests overal draaien. Voeg een test toe als je de planningsregels wijzigt.
- **Documentatie:** verandert gedrag dat gebruikers zien, zoals de planning, de installatie of de instellingen, werk dan ook [README.md](README.md) bij.
- De repository staat in een OneDrive-map. Zet testdata (`tmp-data/`), media en caches niet in git.
