"""Gesundheitsereignisse: Erfassung, Zuordnung zur Mahlzeit, Hinweise (keine Diagnosen)."""
import datetime
import os
import uuid

import zeit

TYPEN = [
    ("erbrechen", "Erbrechen"),
    ("haarballen", "Haarballen"),
    ("durchfall", "Durchfall"),
    ("weicher_kot", "Weicher Kot"),
]
TYP_TEXT = dict(TYPEN)
ZUORDNUNG_STUNDEN = 12
LOESCHEN_MINUTEN = 30
FOTO_ENDUNGEN = {"image/jpeg": ".jpg", "image/png": ".png", "image/heic": ".heic", "image/webp": ".webp"}


def zuordnen(con, katze_id, zeitpunkt):
    """Letzte Mahlzeit innerhalb von 12 h vor dem Ereignis oder None."""
    von = zeit.iso(zeitpunkt - datetime.timedelta(hours=ZUORDNUNG_STUNDEN))
    zeile = con.execute(
        "SELECT id FROM mahlzeit WHERE katze_id = ? AND zeit <= ? AND zeit >= ? ORDER BY zeit DESC LIMIT 1",
        (katze_id, zeit.iso(zeitpunkt), von),
    ).fetchone()
    return zeile["id"] if zeile else None


def foto_speichern(datei, foto_ordner):
    """Speichert ein hochgeladenes Foto unter zufälligem Namen. Rückgabe: Dateiname oder None."""
    if not datei or not datei.filename:
        return None
    endung = FOTO_ENDUNGEN.get(datei.mimetype)
    if endung is None:
        raise ValueError("Foto bitte als JPEG, PNG, HEIC oder WebP.")
    os.makedirs(foto_ordner, exist_ok=True)
    name = uuid.uuid4().hex + endung
    datei.save(os.path.join(foto_ordner, name))
    return name


def erfassen(con, katze_id, typ, zeitpunkt, person, erfasst_von, blut=False, apathie=False, notiz=None, foto=None):
    if typ not in TYP_TEXT:
        raise ValueError("Unbekannter Ereignistyp.")
    # Haarballen gehören nicht in die Futterauswertung
    mahlzeit_id = None if typ == "haarballen" else zuordnen(con, katze_id, zeitpunkt)
    with con:
        cur = con.execute(
            "INSERT INTO ereignis (katze_id, zeit, typ, quelle, person, notiz, foto, mahlzeit_id, blut, apathie, "
            "erfasst, erfasst_von) VALUES (?, ?, ?, 'manuell', ?, ?, ?, ?, ?, ?, ?, ?)",
            (katze_id, zeit.iso(zeitpunkt), typ, person, notiz, foto, mahlzeit_id, int(blut), int(apathie),
             zeit.iso(zeit.jetzt()), erfasst_von),
        )
    return cur.lastrowid


def liste(con, katze_id, tage=30):
    grenze = zeit.iso(zeit.jetzt() - datetime.timedelta(days=tage))
    return con.execute(
        "SELECT e.*, m.zeit AS mahlzeit_zeit, p.sorte, p.proteine FROM ereignis e "
        "LEFT JOIN mahlzeit m ON m.id = e.mahlzeit_id LEFT JOIN produkt p ON p.id = m.produkt_id "
        "WHERE e.katze_id = ? AND e.zeit >= ? AND e.typ IN ('erbrechen', 'haarballen', 'durchfall', 'weicher_kot') "
        "ORDER BY e.zeit DESC",
        (katze_id, grenze),
    ).fetchall()


def loeschen_moeglich(ereignis):
    if ereignis is None or not ereignis["erfasst"]:
        return False
    alter = zeit.jetzt() - datetime.datetime.fromisoformat(ereignis["erfasst"])
    return alter <= datetime.timedelta(minutes=LOESCHEN_MINUTEN)


def loeschen(con, ereignis_id, foto_ordner):
    ereignis = con.execute("SELECT * FROM ereignis WHERE id = ?", (ereignis_id,)).fetchone()
    if not loeschen_moeglich(ereignis):
        return False
    with con:
        con.execute("DELETE FROM ereignis WHERE id = ?", (ereignis_id,))
    if ereignis["foto"]:
        try:
            os.remove(os.path.join(foto_ordner, ereignis["foto"]))
        except OSError:
            pass
    return True


def _durchfall_dauer(ereignisse, jetzt):
    """Dauer der aktuellen Durchfall-Serie (Abstände ≤ 24 h, letztes Ereignis ≤ 24 h her)."""
    zeiten = sorted(datetime.datetime.fromisoformat(e["zeit"]) for e in ereignisse if e["typ"] == "durchfall")
    if not zeiten or jetzt - zeiten[-1] > datetime.timedelta(hours=24):
        return None
    beginn = zeiten[-1]
    for frueher in reversed(zeiten[:-1]):
        if beginn - frueher > datetime.timedelta(hours=24):
            break
        beginn = frueher
    return zeiten[-1] - beginn


def hinweise(con, katze_id):
    """Liste von (stufe, text); stufe 'tierarzt' oder 'hinweis'. Keine Diagnosen."""
    jetzt = zeit.jetzt()
    ereignisse = liste(con, katze_id)
    ergebnis = []

    def seit(stunden):
        grenze = jetzt - datetime.timedelta(hours=stunden)
        return [e for e in ereignisse if datetime.datetime.fromisoformat(e["zeit"]) >= grenze]

    letzte_24h = seit(24)
    if any(e["blut"] for e in letzte_24h):
        ergebnis.append(("tierarzt", "Blut bemerkt – bitte umgehend Tierarzt kontaktieren."))
    if any(e["apathie"] for e in letzte_24h):
        ergebnis.append(("tierarzt", "Apathie bemerkt – bitte umgehend Tierarzt kontaktieren."))
    erbrechen = sum(1 for e in letzte_24h if e["typ"] == "erbrechen")
    if erbrechen >= 2:
        ergebnis.append(("tierarzt", f"{erbrechen}× Erbrechen in 24 Stunden – bitte Tierarzt kontaktieren."))
    dauer = _durchfall_dauer(ereignisse, jetzt)
    if dauer is not None and dauer > datetime.timedelta(hours=48):
        ergebnis.append(("tierarzt", "Durchfall seit mehr als 48 Stunden – bitte Tierarzt kontaktieren."))

    # Futterverweigerung: in 24 h Reste erfasst, aber nichts gefressen
    mahlzeiten = con.execute(
        "SELECT gefressen_g FROM mahlzeit WHERE katze_id = ? AND zeit >= ? AND rest_g IS NOT NULL",
        (katze_id, zeit.iso(jetzt - datetime.timedelta(hours=24))),
    ).fetchall()
    if mahlzeiten and all((m["gefressen_g"] or 0) == 0 for m in mahlzeiten):
        ergebnis.append(("tierarzt", "In den letzten 24 Stunden nichts gefressen – bei Futterverweigerung Tierarzt kontaktieren."))

    ohne_haarballen = [e for e in seit(24 * 7) if e["typ"] != "haarballen"]
    if len(ohne_haarballen) >= 2:
        ergebnis.append(("hinweis", f"{len(ohne_haarballen)} Ereignisse in 7 Tagen (ohne Haarballen) – beobachten."))

    # Häufung: Ereignisse nach mindestens zwei verschiedenen Mahlzeiten mit demselben Protein
    mahlzeiten_je_protein = {}
    for e in ereignisse:
        if e["typ"] == "haarballen" or not e["proteine"]:
            continue
        for protein in {p.strip().lower() for p in e["proteine"].split(",") if p.strip()}:
            mahlzeiten_je_protein.setdefault(protein, set()).add(e["mahlzeit_id"])
    for protein, mahlzeit_ids in sorted(mahlzeiten_je_protein.items()):
        anzahl = len(mahlzeit_ids)
        if anzahl >= 2:
            ergebnis.append(("hinweis", f"Ereignisse nach {anzahl} Mahlzeiten mit {protein.capitalize()} (30 Tage) – "
                                         "Unverträglichkeit möglich, mit Tierarzt besprechen."))
    return ergebnis
