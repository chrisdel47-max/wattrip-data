#!/usr/bin/env python3
"""
Pipeline trafic Wattrip — DATEX II (Bison Futé / DIR) -> GeoJSON compact.

Pourquoi ce pipeline (architecture « B », validée par Christophe le 2026-07-18) :
le flux officiel des événements routiers est un XML DATEX II de ~2,8 Mo mis à
jour toutes les heures (agrégation nationale, réseau non concédé). Impensable
à télécharger et parser sur le téléphone à chaque calcul. Ce script — lancé
par une GitHub Action programmée — le réduit à un GeoJSON compact de quelques
dizaines de Ko que l'appli récupère et filtre le long de l'itinéraire.

Fidèle à la doctrine « fichiers statiques, 0 € de serveur » : la sortie est un
fichier statique hébergé (GitHub), l'appli ne fait qu'un GET.

Découverte du spike (2026-07-18) : chaque événement porte ses coordonnées
lat/lon directement (TPEG pointCoordinates) — le matching à la route se réduit
à « ce point est-il à moins de X m du tracé ? », aucun décodage ALERT-C requis.

Source : https://transport.data.gouv.fr/datasets/evenements-routiers-sur-le-reseau-routier-national-non-concede
Licence Ouverte 2.0. Sans authentification.
"""
from __future__ import annotations

import json
import sys
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

FEED_URL = (
    "https://transport.data.gouv.fr/resources/79174/download"  # agrégation horaire
)

DATEX = "http://datex2.eu/schema/2/2_0"
XSI = "http://www.w3.org/2001/XMLSchema-instance"

# xsi:type du situationRecord -> catégorie Wattrip. 4 familles lisibles, pas
# les 12 types DATEX II. L'ordre encode une priorité (accident > fermeture >
# bouchon > travaux) quand un enregistrement pourrait tomber dans deux seaux.
TYPE_TO_CATEGORY = {
    "Accident": "accident",
    "VehicleObstruction": "accident",
    "GeneralObstruction": "accident",
    "InfrastructureDamageObstruction": "accident",
    "EnvironmentalObstruction": "accident",
    "AnimalPresenceObstruction": "accident",
    "GeneralNetworkManagement": "fermeture",
    "RoadOrCarriagewayOrLaneManagement": "fermeture",
    "ReroutingManagement": "fermeture",
    "AbnormalTraffic": "bouchon",
    "MaintenanceWorks": "travaux",
    "ConstructionWorks": "travaux",
    "SpeedManagement": "travaux",
}
CATEGORY_PRIORITY = {"accident": 0, "fermeture": 1, "bouchon": 2, "travaux": 3}


def q(tag: str) -> str:
    return f"{{{DATEX}}}{tag}"


def local_xsi_type(el: ET.Element) -> str | None:
    raw = el.get(f"{{{XSI}}}type")
    if not raw:
        return None
    return raw.split(":")[-1]  # "ns2:MaintenanceWorks" -> "MaintenanceWorks"


def french_value(comment: ET.Element) -> str | None:
    for value in comment.iter(q("value")):
        if value.get("lang", "fr") == "fr" and value.text:
            return value.text.strip()
    return None


def first_point(record: ET.Element) -> tuple[float, float] | None:
    """Retourne (lon, lat) du premier pointCoordinates trouvé, ou None."""
    for pc in record.iter(q("pointCoordinates")):
        lat = pc.findtext(q("latitude"))
        lon = pc.findtext(q("longitude"))
        if lat and lon:
            try:
                return (float(lon), float(lat))
            except ValueError:
                continue
    return None


def is_ended(record: ET.Element) -> bool:
    for end in record.iter(q("end")):
        if (end.text or "").strip().lower() == "true":
            return True
    return False


def description(record: ET.Element) -> str | None:
    """Le commentaire 'description' en français ; sinon le locationDescriptor."""
    location_desc = None
    for c in record.iter(q("generalPublicComment")):
        ctype = c.findtext(q("commentType"))
        val = french_value(c)
        if not val:
            continue
        if ctype == "description":
            return val
        if ctype == "locationDescriptor" and location_desc is None:
            location_desc = val
    return location_desc


def road_number(record: ET.Element) -> str | None:
    rn = record.findtext(f".//{q('roadNumber')}")
    if not rn:
        return None
    # "N0165" -> "N165" (zéros de tête entre lettre et chiffres, plus lisible)
    import re

    m = re.match(r"([A-Za-z]+)0*(\d+)", rn)
    return f"{m.group(1)}{m.group(2)}" if m else rn


def parse(xml_bytes: bytes) -> list[dict]:
    root = ET.fromstring(xml_bytes)
    features: list[dict] = []
    seen: set[str] = set()
    for situation in root.iter(q("situation")):
        severity = situation.findtext(q("overallSeverity")) or "unknown"
        for record in situation.findall(q("situationRecord")):
            xtype = local_xsi_type(record)
            category = TYPE_TO_CATEGORY.get(xtype or "")
            if category is None:
                continue  # type non pertinent pour l'automobiliste (messages, etc.)
            if is_ended(record):
                continue
            point = first_point(record)
            if point is None:
                continue  # pas de coordonnées exploitables -> on ne peut pas placer
            rid = record.get("id") or situation.get("id") or f"{point}"
            if rid in seen:
                continue
            seen.add(rid)
            props = {"cat": category, "sev": severity}
            road = road_number(record)
            if road:
                props["road"] = road
            desc = description(record)
            if desc:
                props["desc"] = desc[:140]
            features.append(
                {
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [round(point[0], 5), round(point[1], 5)]},
                    "properties": props,
                }
            )
    features.sort(key=lambda f: CATEGORY_PRIORITY.get(f["properties"]["cat"], 9))
    return features


def main() -> int:
    src = sys.argv[1] if len(sys.argv) > 1 else FEED_URL
    if src.startswith("http"):
        req = urllib.request.Request(src, headers={"User-Agent": "Wattrip/traffic-pipeline"})
        with urllib.request.urlopen(req, timeout=60) as resp:
            xml_bytes = resp.read()
    else:
        with open(src, "rb") as fh:
            xml_bytes = fh.read()

    features = parse(xml_bytes)
    fc = {
        "type": "FeatureCollection",
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": "Bison Futé / DIR (DATEX II) — Licence Ouverte 2.0",
        "features": features,
    }
    out = sys.argv[2] if len(sys.argv) > 2 else "traffic.geojson"
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(fc, fh, ensure_ascii=False, separators=(",", ":"))
    counts: dict[str, int] = {}
    for f in features:
        counts[f["properties"]["cat"]] = counts.get(f["properties"]["cat"], 0) + 1
    print(f"{len(features)} événements -> {out}", file=sys.stderr)
    print(f"  par catégorie : {counts}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
