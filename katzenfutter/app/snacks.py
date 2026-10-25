"""Snacks erfassen; Snack-kcal werden vom Hauptfutter-Budget abgezogen."""
import datetime

import einstellungen
import fachlogik
import zeit

RUECKGAENGIG_MINUTEN = 30


def snack_produkte(con):
    return con.execute(
        "SELECT * FROM produkt WHERE status = 'aktiv' AND futterart = 'snack' ORDER BY marke, sorte"
    ).fetchall()


def kcal_berechnen(produkt, stueck, menge_g):
    """kcal aus Menge (g) oder Stück × Stückgewicht; None, wenn kcal/100 g oder Gewicht fehlen."""
    if produkt["kcal_100g"] is None:
        return None
    if menge_g is None and stueck and produkt["stueck_g"]:
        menge_g = stueck * produkt["stueck_g"]
    if menge_g is None:
        return None
    return fachlogik.kcal_aus_menge(menge_g, produkt["kcal_100g"])


def erfassen(con, katze_id, produkt, stueck, menge_g, person, erfasst_von):
    kcal = kcal_berechnen(produkt, stueck, menge_g)
    if menge_g is None and stueck and produkt["stueck_g"]:
        menge_g = stueck * produkt["stueck_g"]
    jetzt = zeit.iso(zeit.jetzt())
    with con:
        cur = con.execute(
            "INSERT INTO snack (katze_id, produkt_id, zeit, person, stueck, menge_g, kcal, erfasst, erfasst_von) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (katze_id, produkt["id"], jetzt, person, stueck, menge_g, kcal, jetzt, erfasst_von),
        )
    return cur.lastrowid


def heute(con, katze_id):
    return con.execute(
        "SELECT s.*, p.marke, p.sorte FROM snack s JOIN produkt p ON p.id = s.produkt_id "
        "WHERE s.katze_id = ? AND s.zeit >= ? ORDER BY s.zeit DESC",
        (katze_id, zeit.tagesbeginn_utc()),
    ).fetchall()


def tagesstand(con, katze_id, einst, mer_kcal):
    """Snack-Stand heute: kcal, Anteil am Tagesbedarf, Stück der Kinder, Limit."""
    liste = heute(con, katze_id)
    kcal = sum(s["kcal"] or 0 for s in liste)
    kinder_stueck = sum((s["stueck"] or 1) for s in liste if einstellungen.ist_kind(einst, s["person"]))
    limit = einst["snack_limit_kinder"]
    return {
        "liste": liste,
        "kcal": kcal,
        "kcal_unbekannt": any(s["kcal"] is None for s in liste),
        "anteil": fachlogik.snack_anteil(kcal, mer_kcal) if mer_kcal else None,
        "warnung": fachlogik.snack_warnung(kcal, mer_kcal) if mer_kcal else False,
        "max_kcal": mer_kcal * fachlogik.SNACK_ANTEIL_MAX if mer_kcal else None,
        "kinder_stueck": kinder_stueck,
        "limit": limit,
        "limit_erreicht": limit is not None and kinder_stueck >= limit,
        "limit_ueberschritten": limit is not None and kinder_stueck > limit,
    }


def rueckgaengig(con, snack_id):
    snack = con.execute("SELECT * FROM snack WHERE id = ?", (snack_id,)).fetchone()
    if snack is None or not snack["erfasst"]:
        return False
    if zeit.jetzt() - datetime.datetime.fromisoformat(snack["erfasst"]) > datetime.timedelta(minutes=RUECKGAENGIG_MINUTEN):
        return False
    with con:
        con.execute("DELETE FROM snack WHERE id = ?", (snack_id,))
    return True
