"""Futterdatenbank: Formularprüfung, Speichern, Trockenmasse-Vergleich."""
import sqlite3

import datenbank
import fachlogik

FUTTERARTEN = [("allein", "Alleinfutter"), ("ergaenzung", "Ergänzungsfutter"), ("snack", "Snack")]
STATUS = [("aktiv", "aktiv"), ("gesperrt", "gesperrt"), ("archiviert", "archiviert")]
NAEHRSTOFFE = [
    ("rohprotein", "Rohprotein"),
    ("rohfett", "Rohfett"),
    ("rohasche", "Rohasche"),
    ("rohfaser", "Rohfaser"),
    ("feuchte", "Feuchte"),
]
TEXTFELDER = ["marke", "linie", "sorte", "packungstyp", "textur"]


def zahl(text):
    text = (text or "").strip().replace(",", ".")
    if not text:
        return None
    return float(text)


def ean_gueltig(ean):
    """Prüft EAN-8, UPC-A (12) und EAN-13 einschließlich Prüfziffer."""
    if not ean.isdigit() or len(ean) not in (8, 12, 13):
        return False
    ziffern = [int(z) for z in ean]
    pruef = ziffern.pop()
    # Gewichte 3,1,3,… von rechts beginnend
    summe = sum(z * (3 if i % 2 == 0 else 1) for i, z in enumerate(reversed(ziffern)))
    return (10 - summe % 10) % 10 == pruef


def ean_normalisieren(text):
    return "".join((text or "").split())


def suchen_ean(con, ean):
    """Sucht ein Produkt per EAN; UPC-A (12) und EAN-13 mit führender 0 gelten als gleich."""
    varianten = {ean}
    if len(ean) == 12:
        varianten.add("0" + ean)
    elif len(ean) == 13 and ean.startswith("0"):
        varianten.add(ean[1:])
    platzhalter = ", ".join("?" * len(varianten))
    return con.execute(f"SELECT * FROM produkt WHERE ean IN ({platzhalter}) ORDER BY id LIMIT 1",
                       sorted(varianten)).fetchone()


def _ja_nein(wert):
    return {"1": 1, "0": 0}.get(wert or "")


def aus_formular(form):
    """Liest und prüft das Produktformular. Rückgabe: (daten, bestand, fehler)."""
    daten = {feld: (form.get(feld) or "").strip() or None for feld in TEXTFELDER}
    if not daten["marke"] or not daten["sorte"]:
        return None, None, "Marke und Sorte sind Pflichtfelder."

    ean = ean_normalisieren(form.get("ean"))
    if ean and not ean_gueltig(ean):
        return None, None, "EAN ungültig (8, 12 oder 13 Ziffern mit korrekter Prüfziffer)."
    daten["ean"] = ean or None

    daten["futterart"] = form.get("futterart") or "allein"
    if daten["futterart"] not in dict(FUTTERARTEN):
        return None, None, "Unbekannte Futterart."
    daten["status"] = form.get("status") or "aktiv"
    if daten["status"] not in dict(STATUS):
        return None, None, "Unbekannter Status."

    proteine = [p.strip() for p in (form.get("proteine") or "").split(",") if p.strip()]
    daten["proteine"] = ", ".join(proteine) or None
    daten["getreidefrei"] = _ja_nein(form.get("getreidefrei"))
    daten["zuckerfrei"] = _ja_nein(form.get("zuckerfrei"))

    try:
        for feld, name in NAEHRSTOFFE + [("fleischanteil", "Fleischanteil")]:
            daten[feld] = zahl(form.get(feld))
            if daten[feld] is not None and not 0 <= daten[feld] <= 100:
                return None, None, f"{name} bitte in % zwischen 0 und 100 angeben."
        for feld, name in (("packung_g", "Packungsgröße"), ("stueck_g", "Stückgewicht")):
            daten[feld] = zahl(form.get(feld))
            if daten[feld] is not None and not 0 < daten[feld] <= 5000:
                return None, None, f"{name} bitte in g angeben."
        daten["preis"] = zahl(form.get("preis"))
        if daten["preis"] is not None and daten["preis"] < 0:
            return None, None, "Preis darf nicht negativ sein."
        kcal = zahl(form.get("kcal_100g"))
        packungen = zahl(form.get("bestand_packungen"))
        angebrochen = zahl(form.get("bestand_angebrochen_g"))
        mindest = zahl(form.get("mindestbestand"))
    except ValueError:
        return None, None, "Bitte Zahlen eingeben, z. B. 10,5."

    # Deklarierter Wert hat Vorrang; sonst aus vollständiger Deklaration berechnen
    if kcal is not None:
        if not 0 < kcal <= 700:
            return None, None, "Energie bitte in kcal/100 g zwischen 0 und 700 angeben."
        daten["kcal_100g"], daten["kcal_herkunft"] = kcal, "deklariert"
    elif all(daten[feld] is not None for feld, _ in NAEHRSTOFFE):
        try:
            daten["kcal_100g"] = fachlogik.kcal_100g_berechnet(*(daten[f] for f, _ in NAEHRSTOFFE))
        except ValueError as exc:
            return None, None, str(exc)
        daten["kcal_herkunft"] = "berechnet"
    else:
        daten["kcal_100g"], daten["kcal_herkunft"] = None, None

    if packungen is not None and (packungen < 0 or packungen != int(packungen)):
        return None, None, "Bestand bitte als ganze Zahl von Packungen angeben."
    if angebrochen is not None and angebrochen < 0:
        return None, None, "Angebrochene Menge darf nicht negativ sein."
    if angebrochen and daten["packung_g"] and angebrochen > daten["packung_g"]:
        return None, None, "Angebrochene Menge ist größer als eine Packung."
    if mindest is not None and (mindest < 0 or mindest != int(mindest) or mindest > 500):
        return None, None, "Mindestbestand bitte als ganze Zahl von Packungen angeben (leer = nach Reichweite)."
    daten["mindestbestand"] = int(mindest) if mindest is not None else None
    bestand = {"packungen": int(packungen or 0), "angebrochen_g": angebrochen}
    return daten, bestand, None


def speichern(con, daten, bestand, produkt_id=None):
    """Legt ein Produkt an oder ändert es. Rückgabe: (id, fehler)."""
    felder = list(daten)
    try:
        with con:
            if produkt_id:
                con.execute(
                    f"UPDATE produkt SET {', '.join(f + ' = ?' for f in felder)}, geaendert = ? WHERE id = ?",
                    [daten[f] for f in felder] + [datenbank.jetzt_utc(), produkt_id],
                )
            else:
                cur = con.execute(
                    f"INSERT INTO produkt ({', '.join(felder)}, erstellt) VALUES ({', '.join('?' * len(felder))}, ?)",
                    [daten[f] for f in felder] + [datenbank.jetzt_utc()],
                )
                produkt_id = cur.lastrowid
            con.execute(
                "INSERT INTO bestand (produkt_id, packungen, angebrochen_g) VALUES (?, ?, ?) "
                "ON CONFLICT (produkt_id) DO UPDATE SET packungen = excluded.packungen, "
                "angebrochen_g = excluded.angebrochen_g",
                (produkt_id, bestand["packungen"], bestand["angebrochen_g"]),
            )
    except sqlite3.IntegrityError as exc:
        if "ean" in str(exc):
            return None, "Diese EAN ist bereits einem anderen Futter zugeordnet."
        raise
    return produkt_id, None


def neu_berechnen(con, produkt_id, vorher):
    """Nach geänderten kcal/100 g oder Stückgewicht: kcal der Mahlzeiten und Snacks dieses Futters neu.

    Bei Snacks wird die Menge nur neu bestimmt, wenn sie aus Stück × altem Stückgewicht stammte oder fehlte;
    von Hand eingetragene Gramm bleiben. Rückgabe: Anzahl geänderter Einträge.
    """
    p = laden(con, produkt_id)
    if vorher is not None and vorher["kcal_100g"] == p["kcal_100g"] and vorher["stueck_g"] == p["stueck_g"]:
        return 0
    geaendert = 0
    with con:
        for m in con.execute("SELECT id, gefressen_g, kcal FROM mahlzeit WHERE produkt_id = ? AND gefressen_g IS NOT NULL",
                             (produkt_id,)).fetchall():
            kcal = m["gefressen_g"] * p["kcal_100g"] / 100 if p["kcal_100g"] is not None else None
            if kcal != m["kcal"]:
                con.execute("UPDATE mahlzeit SET kcal = ? WHERE id = ?", (kcal, m["id"]))
                geaendert += 1
        alt_stueck = vorher["stueck_g"] if vorher is not None else None
        for s in con.execute("SELECT id, stueck, menge_g, kcal FROM snack WHERE produkt_id = ?", (produkt_id,)).fetchall():
            menge = s["menge_g"]
            abgeleitet = s["stueck"] and (menge is None or (alt_stueck and abs(menge - s["stueck"] * alt_stueck) < 1e-9))
            if abgeleitet:
                menge = s["stueck"] * p["stueck_g"] if p["stueck_g"] else None
            kcal = menge * p["kcal_100g"] / 100 if menge is not None and p["kcal_100g"] is not None else None
            if kcal != s["kcal"] or menge != s["menge_g"]:
                con.execute("UPDATE snack SET menge_g = ?, kcal = ? WHERE id = ?", (menge, kcal, s["id"]))
                geaendert += 1
    return geaendert


def liste(con):
    return con.execute(
        "SELECT p.*, b.packungen, b.angebrochen_g FROM produkt p LEFT JOIN bestand b ON b.produkt_id = p.id "
        "ORDER BY p.status = 'aktiv' DESC, p.marke, p.linie, p.sorte"
    ).fetchall()


def laden(con, produkt_id):
    return con.execute(
        "SELECT p.*, b.packungen, b.angebrochen_g FROM produkt p LEFT JOIN bestand b ON b.produkt_id = p.id "
        "WHERE p.id = ?",
        (produkt_id,),
    ).fetchone()


def trockenmasse(produkt):
    """Nährwerte auf Trockenmasse in %; None, wenn die Feuchte fehlt."""
    feuchte = produkt["feuchte"]
    if feuchte is None or feuchte >= 100:
        return None
    werte = {}
    for feld in ("rohprotein", "rohfett", "rohasche", "rohfaser"):
        if produkt[feld] is not None:
            werte[feld] = fachlogik.trockenmasse(produkt[feld], feuchte)
    if all(produkt[f] is not None for f, _ in NAEHRSTOFFE):
        try:
            werte["nfe"] = fachlogik.trockenmasse(fachlogik.nfe(*(produkt[f] for f, _ in NAEHRSTOFFE)), feuchte)
        except ValueError:
            pass
    if produkt["kcal_100g"] is not None:
        werte["kcal_100g"] = produkt["kcal_100g"] / (100 - feuchte) * 100
    return werte


def bezeichnung(produkt):
    return " ".join(t for t in (produkt["marke"], produkt["linie"], produkt["sorte"]) if t)
