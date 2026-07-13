# 🚌 OVapi Departures Proxy

Een lichte Docker-container die realtime OV-vertrektijden van **OVapi** (v0.ovapi.nl) uitleest, opschoont en via een lokaal HTTP-endpoint aanbiedt. Ontworpen voor gebruik met Home Assistant en andere tools die vaak willen pollen zonder OVapi te belasten.

> **Onofficieel project.** Los van OVapi zelf. OVapi is een semi-privé, niet-commercieel project — deze container gaat er netjes mee om (zie fair use hieronder).

## Features

- 🚌 Leest realtime vertrektijden (incl. vertraging) van OVapi
- ⚡ In-memory cache: Home Assistant mag vaak pollen, OVapi wordt met rust gelaten
- 🕐 Correcte tijdzone-afhandeling (Europe/Amsterdam, ook met containerklok op UTC)
- 🔍 Filteren op lijn en aantal vertrekken
- 🛡️ Fair use: pollinterval minimaal 60 s + identificerende User-Agent
- 💾 Bij een OVapi-storing wordt de laatste goede data geserveerd (`stale: true`)
- 🏠 Kant-en-klare Home Assistant REST-sensor en Lovelace-kaart
- 🐳 Docker Compose / Portainer ondersteuning

---

## TimingPointCode (TPC) bepalen

Elke halte-**richting** heeft bij OVapi een eigen TPC — de richtingkeuze zit dus in de TPC-keuze. Bepaal de juiste TPC met het meegeleverde script:

```bash
python scripts/find_tpc.py <TPC1> <TPC2> --line <lijn> --dest "<bestemming>"
```

Het script toont per TPC welke lijnen/bestemmingen er langskomen en meldt de match. Met `--save-fixture tests/fixtures/tpc_live.json` sla je meteen een echte respons op voor de testsuite. Tip: draai dit overdag; 's nachts kan de lijst leeg zijn.

Voorbeeld voor halte "Katwijk, Gemeentehuis": `54460130` = lijn 385 richting Den Haag CS, `54460131` = de tegenrichting.

---

## Installatie

`docker-compose.yml` is zelfstandig: alle environment variables staan inline en het gebruikt het kant-en-klare image van GHCR — er is geen `.env` nodig.

**Portainer:** ga naar **Stacks → Add stack → Web editor**, plak de inhoud van `docker-compose.yml`, pas de waarden aan en deploy.

**Zonder Portainer:**

```bash
docker compose up -d
curl http://localhost:8000/departures
```

**Updaten:** `docker compose pull && docker compose up -d` (de stack volgt `:latest`).

**Terugrollen:** zet in de compose tijdelijk een specifieke versietag (bv.
`image: ghcr.io/lucasplug/ovapi-departures-proxy:1.0.0`) of een image-digest
(`docker images --digests`), en draai `docker compose up -d`. Terug naar
nieuwste: tag weer op `:latest` zetten en opnieuw pullen.

**Lokaal ontwikkelen** (bouwt uit de broncode, leest `.env`):

```bash
cp .env.example .env
docker compose -f docker-compose.dev.yml up -d --build
```

De service bindt op `0.0.0.0` en is dus ook vanaf andere machines bereikbaar op `http://<docker-host>:<PORT>`. Een andere poort kiezen = zowel `PORT` als beide kanten van de `ports:`-mapping aanpassen.

---

## Environment variables

Alle configuratie gaat via environment variables; intervallen zijn in **seconden**.

| Variabele | Omschrijving | Standaard |
|------------|--------------|-----------|
| `OVAPI_TPC` | TimingPointCode van je halte-richting | *(verplicht)* |
| `POLL_INTERVAL_SECONDS` | Pollinterval richting OVapi; minimum 60 (lager wordt geclampt) | `180` |
| `USER_AGENT` | Identificerende User-Agent richting OVapi | projectnaam + repo-URL |
| `PORT` | Poort van de HTTP-API | `8000` |
| `LINE_FILTER` | Alleen deze lijnen tonen, comma-separated (bv. `385`) | *(leeg = alles)* |
| `LIMIT` | Maximum aantal vertrekken (bv. `4`) | `0` *(onbeperkt)* |
| `TZ` | Tijdzone van de container (parsing is sowieso Europe/Amsterdam) | `Europe/Amsterdam` |
| `OVAPI_BASE_URL` | Basis-URL van OVapi (zie noot hieronder) | `http://v0.ovapi.nl` |

> **Waarom HTTP en geen HTTPS?** `v0.ovapi.nl` serveert een TLS-certificaat dat alleen voor `de.ovapi.nl` is uitgegeven, waardoor HTTPS-certificaatvalidatie faalt (geverifieerd juli 2026). De data is openbare reisinformatie; vrijwel alle OVapi-integraties gebruiken daarom HTTP. Mocht OVapi dit ooit fixen, zet dan `OVAPI_BASE_URL=https://v0.ovapi.nl`.

---

## Endpoints

### `GET /departures`

Query-parameters (optioneel): `?line=385` (overschrijft `LINE_FILTER`) en `?limit=4` (overschrijft `LIMIT`).

Het antwoord is bewust een **object** met top-level keys (geen kale array), zodat Home Assistant er met `json_attributes` attributen uit kan lezen:

```json
{
  "stop_name": "Katwijk, Gemeentehuis",
  "updated": "2026-07-12T16:50:12+02:00",
  "age_seconds": 42,
  "stale": false,
  "departures": [
    {
      "line": "385",
      "destination": "Den Haag CS",
      "transport_type": "BUS",
      "planned": "2026-07-12T16:58:00+02:00",
      "expected": "2026-07-12T16:59:30+02:00",
      "delay_minutes": 2,
      "minutes_until": 9
    }
  ]
}
```

Een lege `departures`-lijst (bv. 's nachts) is een geldige respons, geen fout. `stale: true` betekent: de laatste OVapi-poll mislukte, dit is de laatst bekende goede data. Met `age_seconds` (leeftijd van de cache) zie je het verschil tussen één mislukte poll en data die al uren oud is.

### `GET /health`

Geeft altijd `200` zolang de webserver draait, met `status: "ok"` of `"degraded"`, plus `age_seconds`, `consecutive_failures` en `last_error` in de body. Wordt gebruikt door de Docker `HEALTHCHECK`.

---

## Home Assistant

Home Assistant bereikt de container via het IP of de hostnaam van je Docker-host: `http://<docker-host>:8000`. Draait HA op een andere machine, VM of container? Zorg dan dat de poort openstaat in de firewall van de Docker-host en dat het netwerkverkeer tussen beide is toegestaan. Test eventueel eerst met `curl http://<docker-host>:8000/health`.

### REST-sensor (`configuration.yaml`)

State = minuten tot het eerstvolgende vertrek; een lege lijst geeft `unknown`. `scan_interval` mag kort: HA leest alleen de cache van de container, niet OVapi.

```yaml
sensor:
  - platform: rest
    name: "Bus 385 naar Den Haag CS"
    resource: http://<docker-host>:8000/departures
    scan_interval: 60
    unit_of_measurement: "min"
    value_template: >-
      {% if value_json.departures %}
        {{ value_json.departures[0].minutes_until }}
      {% else %}
        {{ none }}
      {% endif %}
    json_attributes:
      - departures
      - stop_name
      - stale
      - updated
```

### Lovelace-kaart (markdown, geen custom card nodig)

```yaml
type: markdown
title: 🚌 385 → Den Haag CS
content: >-
  {% set d = state_attr('sensor.bus_385_naar_den_haag_cs', 'departures') %}
  {% if d %}
  {% for dep in d %}
  **{{ dep.line }}** naar {{ dep.destination }} — over **{{ dep.minutes_until }} min**
  ({{ as_timestamp(dep.expected) | timestamp_custom('%H:%M') }}{% if dep.delay_minutes > 0 %}, +{{ dep.delay_minutes }} min vertraging{% endif %})

  {% endfor %}
  {% else %}
  _Geen vertrekken bekend (nachtpauze of geen data)._
  {% endif %}
  {% if state_attr('sensor.bus_385_naar_den_haag_cs', 'stale') %}

  ⚠️ _Data is mogelijk verouderd (OVapi tijdelijk niet bereikbaar)._
  {% endif %}
```

Alternatief: met [flex-table-card](https://github.com/custom-cards/flex-table-card) (via HACS) kun je de `departures`-attribuutlijst als nette tabel tonen.

---

## Ontwikkelen & testen

```bash
pip install -r requirements-dev.txt
pytest
```

De tests draaien volledig zonder netwerk, tegen `tests/fixtures/tpc_sample.json` (zelfde formaat als een echte `/tpc/<TPC>`-respons). Getest worden o.a. parsing, sortering, filtering op lijn, vertragingsberekening, de lege-lijst-case en de UTC↔NL-tijdzonecase. Een met `scripts/find_tpc.py --save-fixture` opgenomen live-capture (`tests/fixtures/tpc_live.json`, buiten git) wordt automatisch extra gevalideerd.

---

## Licentie

[MIT](LICENSE). Onofficieel project; niet gelieerd aan OVapi of vervoerders.
