"""PetKit-Katzenklo: Gewicht je Toilettengang und Toilettengänge aus HA-Sensoren übernehmen.

Abgleich über die HA-Verlaufs-API seit dem letzten Stand (nichts geht verloren, wenn das Add-on aus war).
Gewicht: Einheit umrechnen, Ausreißer > 5 % zum 7-Tage-Median verwerfen (gespeichert, aber markiert).
Toilettengänge: Ereignis „toilette“; Hinweis nur bei deutlich mehr Gängen als üblich (Freigang: wenige sind normal).
"""
import datetime
import logging
import statistics

import requests

import verlauf
import zeit

log = logging.getLogger("katzenfutter.petkit")

HA_API = "http://supervisor/core/api"
ERSTER_ABGLEICH_TAGE = 7
EINHEITEN = {"kg": 1.0, "g": 0.001, "lb": 0.45359237, "lbs": 0.45359237}
VIELE_GAENGE_FAKTOR = 2.0
VIELE_GAENGE_MINDESTENS = 6


def zeitpunkt(text):
    """ISO-Zeit aus HA (mit Zeitzone) als UTC-ISO-Text, sonst None."""
    try:
        wert = datetime.datetime.fromisoformat(str(text).replace("Z", "+00:00"))
    except ValueError:
        return None
    if wert.tzinfo is None:
        wert = wert.replace(tzinfo=zeit.BERLIN)
    return zeit.iso(wert)


def kilogramm(zustand):
    """Gewicht in kg aus einem HA-Zustand oder None (unbekannt, nicht numerisch, unplausibel)."""
    try:
        wert = float(zustand["state"])
    except (TypeError, ValueError, KeyError):
        return None
    einheit = (zustand.get("attributes") or {}).get("unit_of_measurement", "kg").strip().lower()
    faktor = EINHEITEN.get(einheit)
    if faktor is None:
        return None
    kg = wert * faktor
    return kg if 0.5 <= kg <= 15 else None


def gewicht_uebernehmen(con, katze_id, kg, zeit_text):
    """Speichert eine PetKit-Wiegung (doppelte ignoriert). Rückgabe: 'neu', 'verworfen' oder None."""
    if con.execute("SELECT 1 FROM gewicht WHERE katze_id = ? AND quelle = 'petkit' AND zeit = ?",
                   (katze_id, zeit_text)).fetchone():
        return None
    grenze = zeit.iso(datetime.datetime.fromisoformat(zeit_text) - datetime.timedelta(days=7))
    vorher = [r[0] for r in con.execute(
        "SELECT kg FROM gewicht WHERE katze_id = ? AND quelle = 'petkit' AND verworfen = 0 AND zeit >= ? AND zeit < ?",
        (katze_id, grenze, zeit_text))]
    verworfen = bool(vorher) and verlauf.ist_ausreisser(kg, statistics.median(vorher))
    with con:
        con.execute("INSERT INTO gewicht (katze_id, zeit, kg, quelle, verworfen) VALUES (?, ?, ?, 'petkit', ?)",
                    (katze_id, zeit_text, round(kg, 3), int(verworfen)))
        if not verworfen:
            juengste = con.execute("SELECT kg FROM gewicht WHERE katze_id = ? AND verworfen = 0 "
                                   "ORDER BY zeit DESC, id DESC LIMIT 1", (katze_id,)).fetchone()
            con.execute("UPDATE katze SET gewicht_aktuell = ? WHERE id = ?", (juengste[0], katze_id))
    return "verworfen" if verworfen else "neu"


def besuch_uebernehmen(con, katze_id, zeit_text):
    """Speichert einen Toilettengang (doppelte ignoriert). Rückgabe: True, wenn neu."""
    if con.execute("SELECT 1 FROM ereignis WHERE katze_id = ? AND typ = 'toilette' AND zeit = ?",
                   (katze_id, zeit_text)).fetchone():
        return False
    with con:
        con.execute("INSERT INTO ereignis (katze_id, zeit, typ, quelle, erfasst) VALUES (?, ?, 'toilette', 'petkit', ?)",
                    (katze_id, zeit_text, zeit.iso(zeit.jetzt())))
    return True


def verarbeiten(con, katze, verlauf_besuch, verlauf_gewicht):
    """Verarbeitet HA-Verlaufszustände (Listen von {state, attributes, last_changed}). Rückgabe: Zähler."""
    zaehler = {"besuche": 0, "gewichte": 0, "verworfen": 0}
    for z in verlauf_besuch:
        # Der Zustand ist der Zeitpunkt des Toilettengangs; ersatzweise die Änderungszeit
        zeit_text = zeitpunkt(z.get("state")) or (zeitpunkt(z.get("last_changed")) if z.get("state") not in
                                                   ("unknown", "unavailable", "Unknown", None, "") else None)
        if zeit_text and besuch_uebernehmen(con, katze["id"], zeit_text):
            zaehler["besuche"] += 1
    for z in verlauf_gewicht:
        kg = kilogramm(z)
        zeit_text = zeitpunkt(z.get("last_changed"))
        if kg is None or not zeit_text:
            continue
        ergebnis = gewicht_uebernehmen(con, katze["id"], kg, zeit_text)
        if ergebnis == "neu":
            zaehler["gewichte"] += 1
        elif ergebnis == "verworfen":
            zaehler["verworfen"] += 1
    return zaehler


def ha_verlauf(token, entity_id, seit):
    """Zustandsänderungen eines Sensors seit `seit` (UTC-ISO) aus der HA-Verlaufs-API."""
    antwort = requests.get(
        f"{HA_API}/history/period/{seit}",
        params={"filter_entity_id": entity_id},
        headers={"Authorization": f"Bearer {token}"}, timeout=20,
    )
    antwort.raise_for_status()
    daten = antwort.json()
    return daten[0] if daten else []


def abgleichen(con, token, abfragen=ha_verlauf):
    """Gleicht alle Katzen mit eingetragenen Sensoren ab. Rückgabe: {katze_id: zaehler}."""
    ergebnis = {}
    for katze in con.execute("SELECT * FROM katze WHERE aktiv = 1 AND (petkit_besuch_entity IS NOT NULL "
                             "OR petkit_gewicht_entity IS NOT NULL)").fetchall():
        jetzt = zeit.jetzt()
        seit = katze["petkit_abgleich"] or zeit.iso(jetzt - datetime.timedelta(days=ERSTER_ABGLEICH_TAGE))
        besuche = abfragen(token, katze["petkit_besuch_entity"], seit) if katze["petkit_besuch_entity"] else []
        gewichte = abfragen(token, katze["petkit_gewicht_entity"], seit) if katze["petkit_gewicht_entity"] else []
        ergebnis[katze["id"]] = verarbeiten(con, katze, besuche, gewichte)
        with con:
            # kleine Überlappung, damit an der Grenze nichts fehlt; Doppelte werden erkannt
            con.execute("UPDATE katze SET petkit_abgleich = ? WHERE id = ?",
                        (zeit.iso(jetzt - datetime.timedelta(minutes=10)), katze["id"]))
    return ergebnis


def toilettengaenge(con, katze_id, tage=1):
    grenze = zeit.iso(zeit.jetzt() - datetime.timedelta(days=tage))
    return con.execute("SELECT COUNT(*) FROM ereignis WHERE katze_id = ? AND typ = 'toilette' AND zeit >= ?",
                       (katze_id, grenze)).fetchone()[0]


def viele_gaenge(con, katze_id):
    """Hinweistext, wenn die letzten 24 h deutlich mehr Toilettengänge als im 14-Tage-Mittel hatten."""
    heute_anzahl = toilettengaenge(con, katze_id, 1)
    if heute_anzahl < VIELE_GAENGE_MINDESTENS:
        return None
    grenze_alt = zeit.iso(zeit.jetzt() - datetime.timedelta(days=15))
    grenze_neu = zeit.iso(zeit.jetzt() - datetime.timedelta(days=1))
    alt = con.execute("SELECT COUNT(*) FROM ereignis WHERE katze_id = ? AND typ = 'toilette' AND zeit >= ? AND zeit < ?",
                      (katze_id, grenze_alt, grenze_neu)).fetchone()[0]
    mittel = alt / 14
    if mittel > 0 and heute_anzahl >= VIELE_GAENGE_FAKTOR * mittel:
        return (f"{heute_anzahl} Toilettengänge in 24 Stunden, sonst etwa {mittel:.1f} – bei häufigem Absetzen kleiner "
                "Mengen oder Pressen bitte Tierarzt fragen.").replace(".", ",", 1)
    return None


def vorschlaege(token, katze_name):
    """Sensor-Vorschläge aus HA: (besuch, gewicht) als Listen von (entity_id, Name)."""
    if not token:
        return [], []
    try:
        antwort = requests.get(f"{HA_API}/states", headers={"Authorization": f"Bearer {token}"}, timeout=10)
        antwort.raise_for_status()
        zustaende = antwort.json()
    except (requests.RequestException, ValueError) as exc:
        log.warning("Sensorliste aus HA nicht abrufbar: %s", exc)
        return [], []
    import mqtt_sensoren  # nur für slug; eigene Sensoren des Add-ons ausblenden
    praefix = f"sensor.{mqtt_sensoren.slug(katze_name)}_"
    besuch, gewicht = [], []
    for z in zustaende:
        eid = z.get("entity_id", "")
        attr = z.get("attributes") or {}
        if not eid.startswith("sensor.") or attr.get("device_class") == "monetary":
            continue
        name = attr.get("friendly_name", eid)
        if name.startswith("Katzenfutter "):
            continue
        passend = eid.startswith(praefix) or "petkit" in eid
        if attr.get("device_class") == "weight" or attr.get("unit_of_measurement") in ("kg", "g", "lb"):
            if passend:
                gewicht.append((eid, name))
        elif passend and (attr.get("device_class") == "timestamp" or any(w in eid for w in ("benutzung", "use", "toilet"))):
            besuch.append((eid, name))
    return sorted(besuch), sorted(gewicht)
