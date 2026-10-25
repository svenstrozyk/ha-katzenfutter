"""Produktdaten per EAN aus Open Pet Food Facts (Ersatz: Open Food Facts).

Übertragen wird nur die EAN. Ergebnisse sind Vorschläge für das Formular; die Abdeckung ist lückenhaft.
"""
import logging
import re

import requests

import texterkennung

log = logging.getLogger("katzenfutter.ean")

QUELLEN = [
    ("Open Pet Food Facts", "https://world.openpetfoodfacts.org/api/v2/product/{ean}.json"),
    ("Open Food Facts", "https://world.openfoodfacts.org/api/v2/product/{ean}.json"),
]
# Bitte der Betreiber: aussagekräftiger User-Agent mit Kontakt
KENNUNG = "ha-katzenfutter/1 (https://github.com/svenstrozyk/ha-katzenfutter)"
ZEITLIMIT_SEKUNDEN = 8
NAEHRWERTE = {
    "crude-protein_100g": "rohprotein",
    "crude-fat_100g": "rohfett",
    "crude-ash_100g": "rohasche",
    "crude-fibre_100g": "rohfaser",
    "moisture_100g": "feuchte",
}


def packungsgroesse(produkt):
    """Gramm je Einzelpackung aus „400g“, „85 g“ oder „12 x 85 g“."""
    text = (produkt.get("quantity") or "").lower().replace(",", ".")
    mehrfach = re.search(r"\d+\s*[x×]\s*(\d+(?:\.\d+)?)\s*g\b", text)
    einzeln = re.search(r"(\d+(?:\.\d+)?)\s*(kg|g)\b", text)
    if mehrfach:
        return float(mehrfach.group(1))
    if einzeln:
        return float(einzeln.group(1)) * (1000 if einzeln.group(2) == "kg" else 1)
    return None


def zuordnen(produkt):
    """Felder des Formulars aus einem OFF-Produkt; nur plausible Werte."""
    werte = {}
    marke = (produkt.get("brands") or "").split(",")[0].strip()
    name = (produkt.get("product_name_de") or produkt.get("product_name") or "").strip()
    if marke:
        werte["marke"] = marke
        # Markenname vorne im Produktnamen nicht doppeln
        if name.lower().startswith(marke.lower()):
            name = name[len(marke):].strip(" -–")
    if name:
        werte["sorte"] = name
    gramm = packungsgroesse(produkt)
    if gramm and 0 < gramm <= 5000:
        werte["packung_g"] = gramm
    naehrwerte = produkt.get("nutriments") or {}
    for schluessel, feld in NAEHRWERTE.items():
        wert = naehrwerte.get(schluessel)
        if isinstance(wert, (int, float)) and 0 <= wert <= 100:
            werte[feld] = float(wert)
    kcal = naehrwerte.get("energy-kcal_100g")
    if isinstance(kcal, (int, float)) and 0 < kcal <= 700:
        werte["kcal_100g"] = float(kcal)
    zutaten = produkt.get("ingredients_text_de") or produkt.get("ingredients_text") or ""
    if zutaten:
        proteine = texterkennung.analysieren("Zusammensetzung: " + zutaten)[0].get("proteine")
        if proteine:
            werte["proteine"] = proteine
    kategorien = " ".join([produkt.get("categories") or "", produkt.get("labels") or ""]).lower()
    if re.search(r"snack|leckerli|treat", kategorien):
        werte["futterart"] = "snack"
    if re.search(r"getreidefrei|grain[- ]free|ohne getreide", kategorien):
        werte["getreidefrei"] = 1
    return werte


def abfragen(ean):
    """(quelle, werte) für die erste Quelle mit Treffer, sonst (None, {})."""
    for name, url in QUELLEN:
        try:
            antwort = requests.get(url.format(ean=ean), headers={"User-Agent": KENNUNG}, timeout=ZEITLIMIT_SEKUNDEN)
            if antwort.status_code == 404:
                continue  # EAN dort nicht erfasst
            antwort.raise_for_status()
            daten = antwort.json()
        except (requests.RequestException, ValueError) as exc:
            log.warning("%s nicht erreichbar: %s", name, exc)
            continue
        if daten.get("status") == 1 and daten.get("product"):
            werte = zuordnen(daten["product"])
            if werte:
                return name, werte
    return None, {}
