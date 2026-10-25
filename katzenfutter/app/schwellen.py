"""Einstellbare Schwellen für Hinweise (Tabelle einstellung, Schlüssel „schwellen“).

Gespeichert werden nur Abweichungen vom Standard. Tierarzt-Regeln und die 10-%-Snackgrenze
sind fachliche Vorgaben und bleiben fest.
"""
import json

# (Schlüssel, Bezeichnung, Einheit, Standard, Minimum, Maximum, ganzzahlig)
DEFINITIONEN = [
    ("keine_aufnahme_stunden", "Keine Futteraufnahme seit", "h", 24, 6, 72, True),
    ("gewicht_verlust_woche", "Gewichtsverlust in einer Woche ab", "%", 2.0, 0.5, 10, False),
    ("gewicht_verlust_4wochen", "Gewichtsverlust in 4 Wochen ab", "%", 5.0, 1, 20, False),
    ("gewicht_zunahme_4wochen", "Gewichtszunahme in 4 Wochen ab", "%", 5.0, 1, 20, False),
    ("akzeptanz_einbruch", "Akzeptanzeinbruch über alle Futter ab", "Prozentpunkte", 25, 5, 80, True),
    ("liebling_score", "Lieblingsfutter ab Score", "", 0.10, 0.02, 0.5, False),
    ("liebling_n", "Lieblingsfutter ab Mahlzeiten", "", 5, 2, 30, True),
    ("abgelehnt_score", "„Wird nicht gemocht“ ab Score −", "", 0.20, 0.02, 0.8, False),
    ("abgelehnt_n", "„Wird nicht gemocht“ ab Mahlzeiten", "", 3, 2, 30, True),
    ("abgelehnt_verweigert", "„Wird nicht gemocht“ ab Verweigerungen", "", 2, 1, 10, True),
    ("nachkaufen_tage", "Nachkaufen, wenn der Bestand reicht unter", "Tage", 7, 1, 60, True),
]
STANDARD = {d[0]: d[3] for d in DEFINITIONEN}


def laden(con):
    """Alle Schwellen: Standard, überschrieben durch gespeicherte Abweichungen."""
    zeile = con.execute("SELECT wert FROM einstellung WHERE schluessel = 'schwellen'").fetchone()
    gespeichert = json.loads(zeile[0]) if zeile and zeile[0] else {}
    return {**STANDARD, **{k: v for k, v in gespeichert.items() if k in STANDARD}}


def abweichungen(con):
    zeile = con.execute("SELECT wert FROM einstellung WHERE schluessel = 'schwellen'").fetchone()
    return json.loads(zeile[0]) if zeile and zeile[0] else {}


def aus_formular(form):
    """(abweichungen, fehler); leeres Feld = Standard."""
    ergebnis = {}
    for schluessel, name, einheit, standard, minimum, maximum, ganz in DEFINITIONEN:
        text = (form.get("s_" + schluessel) or "").strip().replace(",", ".")
        if not text:
            continue
        try:
            wert = float(text)
        except ValueError:
            return None, f"{name}: bitte eine Zahl eingeben."
        if ganz and wert != int(wert):
            return None, f"{name}: bitte eine ganze Zahl eingeben."
        if not minimum <= wert <= maximum:
            return None, f"{name}: bitte zwischen {minimum:g} und {maximum:g} {einheit}".replace(".", ",").strip() + "."
        wert = int(wert) if ganz else wert
        if wert != standard:
            ergebnis[schluessel] = wert
    return ergebnis, None


def speichern(con, abweichungen_neu):
    with con:
        con.execute(
            "INSERT INTO einstellung (schluessel, wert) VALUES ('schwellen', ?) "
            "ON CONFLICT (schluessel) DO UPDATE SET wert = excluded.wert",
            (json.dumps(abweichungen_neu),),
        )
