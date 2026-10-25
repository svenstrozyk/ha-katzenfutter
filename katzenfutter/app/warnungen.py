"""Warn-Mitteilungen: Tierarzt-Hinweise, keine Futteraufnahme, Gewicht, Akzeptanz, Snack-Limit.

Jede Warnung wird einmal gesendet. Verschwindet sie, wird ihr Schlüssel gelöscht, damit ein erneutes
Auftreten wieder meldet. Zahlen im Text zählen nicht zum Schlüssel („2× Erbrechen“ = „3× Erbrechen“).
"""
import json
import re

import einstellungen
import heute
import snacks
import zeit

SCHLUESSEL_GESENDET = "gesendete_warnungen"


def _schluessel(katze_id, art, text):
    return f"{katze_id}|{art}|" + re.sub(r"\d+(?:[.,]\d+)?", "#", text)


def sammeln(con, katze):
    """Aktive Warnungen einer Katze: Liste von (schluessel, stufe, text); stufe 'tierarzt' oder 'hinweis'."""
    einst = einstellungen.laden(con)
    h = heute.zusammenfassung(con, katze, einst, heute.tagesbedarf(katze))
    liste = []
    if h["keine_aufnahme"]:
        text = f"Seit mehr als {h['keine_aufnahme_stunden']} Stunden keine Futteraufnahme erfasst."
        liste.append((_schluessel(katze["id"], "keine_aufnahme", ""), "tierarzt", text))
    for stufe, text in h["gesundheit"]:
        liste.append((_schluessel(katze["id"], "gesundheit", text), stufe, text))
    for text in h["gewicht_hinweise"]:
        liste.append((_schluessel(katze["id"], "gewicht", text), "hinweis", text))
    if h["viele_gaenge"]:
        liste.append((_schluessel(katze["id"], "toilette", ""), "hinweis", h["viele_gaenge"]))
    if h["akzeptanzeinbruch"]:
        liste.append((_schluessel(katze["id"], "akzeptanz", ""), "hinweis",
                      "Frisst seit einigen Tagen über alle Futter deutlich weniger als üblich."))
    stand = snacks.tagesstand(con, katze["id"], einst, heute.tagesbedarf(katze))
    if stand["limit_ueberschritten"]:
        tag = zeit.jetzt().astimezone(zeit.BERLIN).date().isoformat()
        liste.append((f"{katze['id']}|snack_limit|{tag}", "hinweis",
                      f"Snack-Limit der Kinder überschritten ({stand['kinder_stueck']:g} von {stand['limit']} Stück)."))
    return liste


def gesendet_laden(con):
    zeile = con.execute("SELECT wert FROM einstellung WHERE schluessel = ?", (SCHLUESSEL_GESENDET,)).fetchone()
    return json.loads(zeile[0]) if zeile and zeile[0] else {}


def gesendet_speichern(con, gesendet):
    with con:
        con.execute("INSERT INTO einstellung (schluessel, wert) VALUES (?, ?) "
                    "ON CONFLICT (schluessel) DO UPDATE SET wert = excluded.wert",
                    (SCHLUESSEL_GESENDET, json.dumps(gesendet, ensure_ascii=False)))


def nachricht(katze, stufe, text, panel_pfad, schluessel):
    daten = {"tag": "katzenfutter-warnung-" + re.sub(r"[^a-z0-9]+", "-", schluessel.lower())[:60],
             "group": "katzenfutter-warnung", "url": panel_pfad}
    if stufe == "tierarzt":
        # iOS: auch im Fokus-Modus zustellen
        daten["push"] = {"interruption-level": "time-sensitive"}
    titel = f"{katze['name']}: Tierarzt-Hinweis" if stufe == "tierarzt" else f"{katze['name']}: Hinweis"
    return {"title": titel, "message": text + " (Hinweis, keine Diagnose)", "data": daten}


def pruefen(con, senden, panel_pfad):
    """Sendet neue Warnungen über senden(payload) und pflegt die Liste der gesendeten. Rückgabe: Anzahl neu."""
    gesendet = gesendet_laden(con)
    aktiv = {}
    for katze in con.execute("SELECT * FROM katze WHERE aktiv = 1").fetchall():
        for schluessel, stufe, text in sammeln(con, katze):
            aktiv[schluessel] = (katze, stufe, text)
    neu = 0
    for schluessel, (katze, stufe, text) in aktiv.items():
        if schluessel in gesendet:
            continue
        if senden(nachricht(katze, stufe, text, panel_pfad, schluessel)):
            gesendet[schluessel] = zeit.iso(zeit.jetzt())
            neu += 1
    # erledigte Warnungen vergessen, damit ein erneutes Auftreten wieder meldet
    gesendet = {k: v for k, v in gesendet.items() if k in aktiv}
    gesendet_speichern(con, gesendet)
    return neu
