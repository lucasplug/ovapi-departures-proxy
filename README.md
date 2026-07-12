# ovapi-departures-proxy

Kleine Docker-service die realtime OV-vertrektijden van [OVapi](https://v0.ovapi.nl)
ophaalt, opschoont en via een lokaal HTTP-endpoint aanbiedt, zodat Home Assistant
(of iets anders) de data snel en vaak kan uitlezen zonder OVapi te belasten.

> **Onofficieel project.** Dit staat volledig los van OVapi zelf. OVapi is een
> semi-privé, niet-commercieel project — ga er netjes mee om: deze service pollt
> standaard eens per 180 seconden (minimum 60, lagere waarden worden geclampt) en
> stuurt een identificerende User-Agent mee.

## Hoe het werkt

```
OVapi (v0.ovapi.nl)  <-- poll elke POLL_INTERVAL_SECONDS (fair use)
        |
   [container: FastAPI + in-memory cache]
        |
Home Assistant REST-sensor  <-- mag vaak pollen (bv. elke 60 s), leest alleen de cache
```

- Een asyncio-achtergrondtaak haalt `https://v0.ovapi.nl/tpc/<OVAPI_TPC>` op en
  cachet het geparste resultaat in memory.
- Bij een fout of lege OVapi-response blijft de laatste goede data staan en wordt
  `stale: true` gezet — de service crasht niet en geeft geen fout terug.
- Tijden van OVapi zijn lokale NL-tijden zónder offset; ze worden expliciet als
  `Europe/Amsterdam` geparst, dus "minuten tot vertrek" klopt ook als de container
  in UTC draait.
- Al vertrokken of vervallen ritten worden niet meer getoond; sortering is op
  verwachte (realtime) vertrektijd.

## Stap 1: bepaal je TimingPointCode (TPC)

Elke halte-**richting** heeft bij OVapi een eigen TPC — de richtingkeuze zit dus in
de TPC-keuze. Voor "Katwijk, Gemeentehuis" zijn de kandidaten `54460130` en
`54460131`. Bepaal welke bij lijn 385 richting Den Haag CS hoort:

```bash
python scripts/find_tpc.py 54460130 54460131 --line 385 --dest "Den Haag"
```

Het script toont per TPC welke lijnen/bestemmingen er langskomen en meldt de match.
Met `--save-fixture tests/fixtures/tpc_live.json` sla je meteen een echte respons op
die door de testsuite wordt meegenomen. Tip: draai dit overdag; 's nachts kan de
lijst met passes leeg zijn.

Voor deze halte is de uitkomst (geverifieerd tegen de live API, juli 2026):
**`54460130` = richting Den Haag CS**; `54460131` is de tegenrichting
(alles richting Katwijk).

## Draaien

```bash
cp .env.example .env        # en vul OVAPI_TPC (stap 1), LINE_FILTER, etc. in
docker compose up -d --build
curl http://localhost:8000/departures
```

De service bindt op `0.0.0.0`, zodat hij ook vanaf andere machines (zoals de
Home Assistant-VM) bereikbaar is op `http://<Docker-VM-IP>:<PORT>`.

## Environment variables

Alle configuratie gaat via environment variables (zie `.env.example`); intervallen
zijn in **seconden**.

| Variabele | Default | Betekenis |
|---|---|---|
| `OVAPI_TPC` | — (verplicht) | TimingPointCode van je halte-richting |
| `POLL_INTERVAL_SECONDS` | `180` | Pollinterval richting OVapi; minimum 60 (lager wordt geclampt) |
| `USER_AGENT` | projectnaam + repo-URL | Identificerende User-Agent richting OVapi |
| `PORT` | `8000` | Poort van de HTTP-API |
| `LINE_FILTER` | leeg (alles) | Alleen deze lijnen tonen, comma-separated (bv. `385`) |
| `LIMIT` | `0` (onbeperkt) | Maximum aantal vertrekken (bv. `4`) |
| `TZ` | `Europe/Amsterdam` | Tijdzone van de container (parsing is sowieso Europe/Amsterdam) |
| `OVAPI_BASE_URL` | `http://v0.ovapi.nl` | Basis-URL van OVapi (zie noot hieronder); ook handig voor tests |

> **Waarom HTTP en geen HTTPS?** `v0.ovapi.nl` serveert een TLS-certificaat dat
> alleen voor `de.ovapi.nl` is uitgegeven, waardoor HTTPS-certificaatvalidatie
> faalt (geverifieerd juli 2026). De data is openbare reisinformatie; vrijwel
> alle OVapi-integraties gebruiken daarom HTTP. Mocht OVapi dit ooit fixen, zet
> dan `OVAPI_BASE_URL=https://v0.ovapi.nl`.

## Endpoints

### `GET /departures`

Query-parameters (optioneel): `?line=385` (overschrijft `LINE_FILTER`) en
`?limit=4` (overschrijft `LIMIT`).

Het antwoord is bewust een **object** met top-level keys (geen kale array), zodat
Home Assistant er met `json_attributes` attributen uit kan lezen:

```json
{
  "stop_name": "Katwijk, Gemeentehuis",
  "updated": "2026-07-12T16:50:12+02:00",
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

Een lege `departures`-lijst (bv. 's nachts) is een geldige respons, geen fout.
`stale: true` betekent: de laatste OVapi-poll mislukte, dit is de laatst bekende
goede data.

### `GET /health`

Geeft altijd `200` zolang de webserver draait, met `status: "ok"` of `"degraded"`
in de body. Wordt gebruikt door de Docker `HEALTHCHECK`.

## Home Assistant

De setup hieronder gaat uit van twee losse VM's (bv. op één Proxmox-host):
Home Assistant OS in de ene, Docker in de andere. Er is geen gedeeld
docker-netwerk en geen servicenaam-resolutie — HA bereikt de service puur via
het IP van de Docker-VM.

### REST-sensor (`configuration.yaml`)

State = minuten tot het eerstvolgende vertrek; een lege lijst geeft `unknown`.
`scan_interval` mag kort: HA leest alleen de cache van de container, niet OVapi.

```yaml
sensor:
  - platform: rest
    name: "Bus 385 naar Den Haag CS"
    resource: http://<DOCKER-VM-IP>:8000/departures
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

Alternatief: met [flex-table-card](https://github.com/custom-cards/flex-table-card)
(via HACS) kun je de `departures`-attribuutlijst als nette tabel tonen.

### Netwerk-checklist (twee VM's)

- [ ] Docker-VM heeft een **vast IP** (DHCP-reservering of statisch).
- [ ] De gekozen poort (default `8000`) is open in de firewall van de Docker-VM
      (bv. `ufw allow 8000/tcp`).
- [ ] Verkeer tussen de subnetten/VLAN's van de HA-VM en de Docker-VM is toegestaan.
- [ ] Test vanaf HA: **Ontwikkelhulpmiddelen → Acties** of via SSH:
      `curl http://<DOCKER-VM-IP>:8000/health`.

## Ontwikkelen & testen

```bash
pip install -r requirements-dev.txt
pytest
```

De tests draaien volledig zonder netwerk, tegen `tests/fixtures/tpc_sample.json`
(zelfde formaat als een echte `/tpc/<TPC>`-respons: dynamische TPC-key, `Stop` +
`Passes`, naïeve lokale tijden). Getest worden o.a. parsing, sortering, filtering
op lijn, vertragingsberekening, de lege-lijst-case en de UTC↔NL-tijdzonecase. Een
met `scripts/find_tpc.py --save-fixture` opgenomen live-capture
(`tests/fixtures/tpc_live.json`, buiten git) wordt automatisch extra gevalideerd.

## Licentie

[MIT](LICENSE). Onofficieel project; niet gelieerd aan OVapi, Qbuzz of R-net.
