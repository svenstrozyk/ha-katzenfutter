"""Fütterung erfassen, Bestand fortschreiben, Fehleinträge zurücknehmen."""
import datetime

import fachlogik
import zeit

RUECKGAENGIG_MINUTEN = 30


def produkte_zum_fuettern(con):
    """Aktive Futter (ohne Snacks): angebrochene Packung zuerst, dann zuletzt gefüttert."""
    return con.execute(
        "SELECT p.*, b.packungen, b.angebrochen_g, "
        "(SELECT MAX(m.zeit) FROM mahlzeit m WHERE m.produkt_id = p.id) AS zuletzt "
        "FROM produkt p LEFT JOIN bestand b ON b.produkt_id = p.id "
        "WHERE p.status = 'aktiv' AND p.futterart != 'snack' "
        "ORDER BY COALESCE(b.angebrochen_g, 0) > 0 DESC, zuletzt IS NULL, zuletzt DESC, p.marke, p.sorte"
    ).fetchall()


OBEN_MAX = 4


def auswahl_aufteilen(auswahl, oben_max=OBEN_MAX):
    """Teilt die Futterliste: oben angebrochene und zuletzt gefütterte vorrätige Sorten (höchstens oben_max),
    der Rest als „weitere“ (je Eintrag mit Schlüssel vorraetig für die Sortierung innerhalb der Marke).

    Ist noch nichts gefüttert, stehen oben die ersten vorrätigen Sorten. Nicht vorrätige kommen nie nach oben,
    außer es gibt gar keine vorrätigen.
    """
    def vorraetig(p):
        return bool(p["packungen"] or p["angebrochen_g"])

    kandidaten = [p for p in auswahl if vorraetig(p)] or list(auswahl)
    oben = kandidaten[:oben_max]
    oben_ids = {p["id"] for p in oben}
    weitere = sorted((dict(p, vorraetig=vorraetig(p)) for p in auswahl if p["id"] not in oben_ids),
                     key=lambda p: ((p["marke"] or "").lower(), (p["sorte"] or "").lower()))
    return oben, weitere


def fuettern(con, katze_id, produkt, menge_g, zeitpunkt, person, erfasst_von=None):
    """Speichert eine Mahlzeit und schreibt den Bestand fort. Rückgabe: (mahlzeit_id, hinweise)."""
    hinweise = []
    aus_angebrochen = neue = None
    with con:
        bestand = con.execute("SELECT packungen, angebrochen_g FROM bestand WHERE produkt_id = ?",
                              (produkt["id"],)).fetchone()
        if not produkt["packung_g"]:
            hinweise.append("Packungsgröße fehlt – Bestand nicht fortgeschrieben.")
        else:
            packungen = bestand["packungen"] if bestand else 0
            angebrochen = (bestand["angebrochen_g"] if bestand else None) or 0.0
            plan = fachlogik.packungsplan(menge_g, produkt["packung_g"], angebrochen)
            aus_angebrochen = plan["aus_angebrochen_g"]
            neue = min(plan["neue_packungen"], packungen)
            if plan["neue_packungen"] > packungen:
                hinweise.append("Bestand war zu niedrig – bitte im Tab Futter korrigieren.")
            con.execute(
                "INSERT INTO bestand (produkt_id, packungen, angebrochen_g) VALUES (?, ?, ?) "
                "ON CONFLICT (produkt_id) DO UPDATE SET packungen = excluded.packungen, "
                "angebrochen_g = excluded.angebrochen_g",
                (produkt["id"], packungen - neue, plan["rest_angebrochen_g"] or None),
            )
        cur = con.execute(
            "INSERT INTO mahlzeit (katze_id, produkt_id, zeit, person, angeboten_g, aus_angebrochen_g, "
            "neue_packungen, erfasst, erfasst_von) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (katze_id, produkt["id"], zeit.iso(zeitpunkt), person, menge_g, aus_angebrochen, neue,
             zeit.iso(zeit.jetzt()), erfasst_von),
        )
    return cur.lastrowid, hinweise


def rueckgaengig_moeglich(con, mahlzeit):
    """Nur die jüngste Mahlzeit dieses Futters, ohne erfassten Rest, innerhalb von 30 Minuten."""
    if mahlzeit is None or mahlzeit["rest_g"] is not None or not mahlzeit["erfasst"]:
        return False
    alter = zeit.jetzt() - datetime.datetime.fromisoformat(mahlzeit["erfasst"])
    if alter > datetime.timedelta(minutes=RUECKGAENGIG_MINUTEN):
        return False
    juengste = con.execute(
        "SELECT id FROM mahlzeit WHERE produkt_id = ? ORDER BY erfasst DESC, id DESC LIMIT 1",
        (mahlzeit["produkt_id"],),
    ).fetchone()
    return juengste["id"] == mahlzeit["id"]


def rueckgaengig(con, mahlzeit_id):
    """Löscht einen Fehleintrag und stellt den Bestand wieder her. Rückgabe: True bei Erfolg."""
    mahlzeit = con.execute("SELECT * FROM mahlzeit WHERE id = ?", (mahlzeit_id,)).fetchone()
    if not rueckgaengig_moeglich(con, mahlzeit):
        return False
    with con:
        if mahlzeit["aus_angebrochen_g"] is not None:
            bestand = con.execute("SELECT packungen, angebrochen_g FROM bestand WHERE produkt_id = ?",
                                  (mahlzeit["produkt_id"],)).fetchone()
            if mahlzeit["neue_packungen"]:
                # angebrochene Packung war vollständig verbraucht, neue geöffnet
                angebrochen = mahlzeit["aus_angebrochen_g"]
            else:
                angebrochen = (bestand["angebrochen_g"] or 0) + mahlzeit["aus_angebrochen_g"]
            con.execute(
                "UPDATE bestand SET packungen = ?, angebrochen_g = ? WHERE produkt_id = ?",
                (bestand["packungen"] + (mahlzeit["neue_packungen"] or 0), angebrochen or None,
                 mahlzeit["produkt_id"]),
            )
        con.execute("DELETE FROM mahlzeit WHERE id = ?", (mahlzeit_id,))
    return True


def loeschen(con, mahlzeit_id):
    """Löscht eine Mahlzeit auch nach 30 Minuten. Rückgabe: 'mit_bestand', 'ohne_bestand' oder None.

    Ist sie die jüngste Mahlzeit ihres Futters, wird der Bestand wie bei „Rückgängig“ wiederhergestellt;
    sonst wäre die Rückrechnung unsicher, dann bleibt der Bestand unverändert.
    """
    mahlzeit = con.execute("SELECT * FROM mahlzeit WHERE id = ?", (mahlzeit_id,)).fetchone()
    if mahlzeit is None:
        return None
    juengste = con.execute("SELECT id FROM mahlzeit WHERE produkt_id = ? ORDER BY erfasst DESC, id DESC LIMIT 1",
                           (mahlzeit["produkt_id"],)).fetchone()
    mit_bestand = juengste["id"] == mahlzeit_id and mahlzeit["aus_angebrochen_g"] is not None
    with con:
        if mit_bestand:
            bestand = con.execute("SELECT packungen, angebrochen_g FROM bestand WHERE produkt_id = ?",
                                  (mahlzeit["produkt_id"],)).fetchone()
            if mahlzeit["neue_packungen"]:
                angebrochen = mahlzeit["aus_angebrochen_g"]
            else:
                angebrochen = (bestand["angebrochen_g"] or 0) + mahlzeit["aus_angebrochen_g"]
            con.execute("UPDATE bestand SET packungen = ?, angebrochen_g = ? WHERE produkt_id = ?",
                        (bestand["packungen"] + (mahlzeit["neue_packungen"] or 0), angebrochen or None,
                         mahlzeit["produkt_id"]))
        con.execute("UPDATE ereignis SET mahlzeit_id = NULL WHERE mahlzeit_id = ?", (mahlzeit_id,))
        con.execute("DELETE FROM mahlzeit WHERE id = ?", (mahlzeit_id,))
    return "mit_bestand" if mit_bestand else "ohne_bestand"


def heute(con, katze_id):
    return con.execute(
        "SELECT m.*, p.marke, p.linie, p.sorte FROM mahlzeit m JOIN produkt p ON p.id = m.produkt_id "
        "WHERE m.katze_id = ? AND m.zeit >= ? ORDER BY m.zeit DESC",
        (katze_id, zeit.tagesbeginn_utc()),
    ).fetchall()


OFFEN_STUNDEN = 48

STUFEN_TEXT = [
    ("nichts", "Nichts"),
    ("wenig", "Wenig"),
    ("haelfte", "Hälfte"),
    ("viel", "Viel"),
    ("unberuehrt", "Unberührt"),
]


def laden(con, mahlzeit_id):
    return con.execute(
        "SELECT m.*, p.marke, p.linie, p.sorte, p.kcal_100g, p.kcal_herkunft FROM mahlzeit m "
        "JOIN produkt p ON p.id = m.produkt_id WHERE m.id = ?",
        (mahlzeit_id,),
    ).fetchone()


def offene(con, katze_id):
    """Mahlzeiten ohne erfassten Rest aus den letzten 48 Stunden, älteste zuerst."""
    grenze = zeit.iso(zeit.jetzt() - datetime.timedelta(hours=OFFEN_STUNDEN))
    return con.execute(
        "SELECT m.*, p.marke, p.linie, p.sorte FROM mahlzeit m JOIN produkt p ON p.id = m.produkt_id "
        "WHERE m.katze_id = ? AND m.rest_g IS NULL AND m.zeit >= ? ORDER BY m.zeit",
        (katze_id, grenze),
    ).fetchall()


def rest_erfassen(con, mahlzeit_id, stufe=None, rest_gewogen=None, verweigert=False):
    """Speichert den Rest (Schätzstufe oder gewogen) samt gefressener Menge und kcal.

    Ein bereits erfasster Rest wird überschrieben (Korrektur). Rückgabe: Fehlermeldung oder None.
    """
    mahlzeit = laden(con, mahlzeit_id)
    if mahlzeit is None:
        return "Mahlzeit nicht gefunden."
    angeboten = mahlzeit["angeboten_g"]
    if rest_gewogen is not None:
        if not 0 <= rest_gewogen <= angeboten:
            return f"Rest bitte zwischen 0 und {angeboten:g} g angeben (ohne Napf)."
        rest, herkunft = rest_gewogen, "gewogen"
    elif stufe in fachlogik.REST_STUFEN:
        rest, herkunft = fachlogik.rest_aus_stufe(angeboten, stufe), "geschaetzt"
    else:
        return "Bitte eine Schätzstufe wählen oder den Rest wiegen."
    gefressen = fachlogik.gefressen_g(angeboten, rest)
    kcal = fachlogik.kcal_aus_menge(gefressen, mahlzeit["kcal_100g"]) if mahlzeit["kcal_100g"] is not None else None
    with con:
        con.execute(
            "UPDATE mahlzeit SET rest_g = ?, rest_herkunft = ?, gefressen_g = ?, kcal = ?, verweigert = ? WHERE id = ?",
            (rest, herkunft, gefressen, kcal, 1 if verweigert else 0, mahlzeit_id),
        )
    return None
