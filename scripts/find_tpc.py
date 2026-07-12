#!/usr/bin/env python3
"""Determine which TimingPointCode serves a given line/destination.

Each stop direction has its own TPC, so picking the right TPC *is* picking
the direction. This script fetches one or more candidate TPCs from OVapi,
prints which lines/destinations each one serves, and reports the TPC that
matches the requested line + destination.

Example (Katwijk, Gemeentehuis — line 385 towards Den Haag CS):

    python scripts/find_tpc.py 54460130 54460131 --line 385 --dest "Den Haag"

Optionally save the raw response of the matching TPC as a test fixture:

    python scripts/find_tpc.py 54460130 54460131 --line 385 --dest "Den Haag" \
        --save-fixture tests/fixtures/tpc_live.json

Uses only the standard library, so it runs anywhere Python 3.9+ is available.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.request

BASE_URL = "https://v0.ovapi.nl"
USER_AGENT = "ovapi-departures-proxy-setup/1.0 (find_tpc.py; one-off stop lookup)"


def fetch_tpc(tpc: str) -> dict:
    request = urllib.request.Request(
        f"{BASE_URL}/tpc/{tpc}", headers={"User-Agent": USER_AGENT}
    )
    with urllib.request.urlopen(request, timeout=15) as response:
        return json.load(response)


def summarize(payload: dict, tpc: str) -> tuple[str, dict[tuple[str, str], int]]:
    entry = payload.get(tpc) or next(
        (v for v in payload.values() if isinstance(v, dict) and "Passes" in v), {}
    )
    stop_name = (entry.get("Stop") or {}).get("TimingPointName", "<onbekend>")
    services: dict[tuple[str, str], int] = {}
    for journey in (entry.get("Passes") or {}).values():
        key = (
            str(journey.get("LinePublicNumber", "?")),
            str(journey.get("DestinationName50", "?")),
        )
        services[key] = services.get(key, 0) + 1
    return stop_name, services


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("tpcs", nargs="+", help="Candidate TimingPointCodes")
    parser.add_argument("--line", default="385", help="LinePublicNumber to look for")
    parser.add_argument(
        "--dest", default="Den Haag", help="Substring of DestinationName50 to look for"
    )
    parser.add_argument(
        "--save-fixture",
        metavar="PATH",
        help="Save the raw JSON of the matching TPC to this path",
    )
    args = parser.parse_args()

    matches: list[str] = []
    payloads: dict[str, dict] = {}
    for tpc in args.tpcs:
        try:
            payload = fetch_tpc(tpc)
        except Exception as exc:  # noqa: BLE001 - report and continue with next TPC
            print(f"TPC {tpc}: ophalen mislukt: {exc}", file=sys.stderr)
            continue
        payloads[tpc] = payload
        stop_name, services = summarize(payload, tpc)
        print(f"\nTPC {tpc} — {stop_name}")
        if not services:
            print("  (geen passes op dit moment — probeer overdag opnieuw)")
        for (line, dest), count in sorted(services.items()):
            marker = ""
            if line == args.line and args.dest.lower() in dest.lower():
                marker = "   <== MATCH"
                if tpc not in matches:
                    matches.append(tpc)
            print(f"  lijn {line:>4} -> {dest} ({count}x){marker}")

    print()
    if len(matches) == 1:
        print(f"Gebruik OVAPI_TPC={matches[0]} (lijn {args.line} richting '{args.dest}').")
        if args.save_fixture:
            with open(args.save_fixture, "w", encoding="utf-8") as fh:
                json.dump(payloads[matches[0]], fh, indent=2, ensure_ascii=False)
            print(f"Fixture opgeslagen: {args.save_fixture}")
        return 0
    if not matches:
        print(
            "Geen match gevonden. Let op: 's nachts of bij een lege dienstregeling "
            "zijn er geen passes; probeer het overdag opnieuw."
        )
    else:
        print(f"Meerdere matches: {', '.join(matches)} — controleer handmatig.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
