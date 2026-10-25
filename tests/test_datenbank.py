"""Tests für Migrationen und Grundschema."""
import os
import sqlite3
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "katzenfutter", "app")))
import datenbank  # noqa: E402

LETZTE_VERSION = datenbank.MIGRATIONEN[-1][0]


@pytest.fixture()
def pfad(tmp_path):
    return str(tmp_path / "katzenfutter.db")


def test_neue_datenbank_bekommt_alle_migrationen(pfad):
    assert datenbank.migrieren(pfad) == LETZTE_VERSION
    con = datenbank.verbinden(pfad)
    tabellen = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert {"katze", "produkt", "mahlzeit", "snack", "gewicht", "ereignis", "bestand",
            "einstellung", "testlog", "schema_version"} <= tabellen


def test_migration_ist_wiederholbar(pfad):
    datenbank.migrieren(pfad)
    assert datenbank.migrieren(pfad) == LETZTE_VERSION
    con = datenbank.verbinden(pfad)
    assert con.execute("SELECT COUNT(*) FROM schema_version").fetchone()[0] == len(datenbank.MIGRATIONEN)


def test_erste_katze_wird_genau_einmal_angelegt(pfad):
    datenbank.migrieren(pfad)
    datenbank.migrieren(pfad)
    con = datenbank.verbinden(pfad)
    katzen = con.execute("SELECT name, freigang, kastriert, aktivitaetsfaktor, gewicht_aktuell FROM katze").fetchall()
    assert [tuple(k) for k in katzen] == [("Katze", 1, 1, 1.4, None)]


def test_bestehendes_testprotokoll_aus_010_bleibt_erhalten(pfad):
    # Zustand nach Technik-Test 0.1.0: nur testlog, keine schema_version
    con = sqlite3.connect(pfad)
    con.execute("CREATE TABLE testlog (id INTEGER PRIMARY KEY, ts TEXT, user TEXT, test TEXT, ok INTEGER, detail TEXT)")
    con.execute("INSERT INTO testlog (ts, user, test, ok, detail) VALUES ('2026-10-25T12:37:49', 'Alex', 'db', 1, 'x')")
    con.commit()
    con.close()

    datenbank.migrieren(pfad)
    con = datenbank.verbinden(pfad)
    assert con.execute("SELECT COUNT(*) FROM testlog").fetchone()[0] == 1


def test_fehlerhafte_migration_wird_komplett_zurueckgerollt(pfad, monkeypatch):
    datenbank.migrieren(pfad)
    kaputt = datenbank.MIGRATIONEN + [
        (LETZTE_VERSION + 1, "kaputt", ["CREATE TABLE neu (id INTEGER)", "SELECT * FROM gibt_es_nicht"]),
    ]
    monkeypatch.setattr(datenbank, "MIGRATIONEN", kaputt)
    with pytest.raises(sqlite3.OperationalError):
        datenbank.migrieren(pfad)
    con = datenbank.verbinden(pfad)
    assert datenbank.schema_stand(con) == LETZTE_VERSION
    assert con.execute("SELECT COUNT(*) FROM sqlite_master WHERE name = 'neu'").fetchone()[0] == 0


def test_fremdschluessel_werden_geprueft(pfad):
    datenbank.migrieren(pfad)
    con = datenbank.verbinden(pfad)
    with pytest.raises(sqlite3.IntegrityError):
        con.execute(
            "INSERT INTO mahlzeit (katze_id, produkt_id, zeit, angeboten_g) VALUES (1, 999, '2026-10-25T10:00:00+00:00', 85)"
        )


def test_rest_groesser_als_angeboten_wird_abgelehnt(pfad):
    datenbank.migrieren(pfad)
    con = datenbank.verbinden(pfad)
    con.execute(
        "INSERT INTO produkt (id, marke, sorte, packung_g, erstellt) VALUES (1, 'Animonda', 'Pute', 85, '2026-10-25T10:00:00+00:00')"
    )
    with pytest.raises(sqlite3.IntegrityError):
        con.execute(
            "INSERT INTO mahlzeit (katze_id, produkt_id, zeit, angeboten_g, rest_g) VALUES (1, 1, '2026-10-25T10:00:00+00:00', 85, 90)"
        )


def test_ungueltige_futterart_wird_abgelehnt(pfad):
    datenbank.migrieren(pfad)
    con = datenbank.verbinden(pfad)
    with pytest.raises(sqlite3.IntegrityError):
        con.execute(
            "INSERT INTO produkt (marke, sorte, futterart, erstellt) VALUES ('X', 'Y', 'trocken', '2026-10-25T10:00:00+00:00')"
        )


def test_migration_10_fuellt_nur_fehlende_kcal(pfad):
    con = sqlite3.connect(pfad)
    con.close()
    # Stand vor Migration 10 herstellen
    stand = [m for m in datenbank.MIGRATIONEN if m[0] < 10]
    import unittest.mock as mock
    with mock.patch.object(datenbank, "MIGRATIONEN", stand):
        datenbank.migrieren(pfad)
    con = datenbank.verbinden(pfad)
    with con:
        con.execute("INSERT INTO produkt (id, marke, sorte, futterart, stueck_g, kcal_100g, erstellt) "
                    "VALUES (1, 'Z', 'S', 'snack', 1.5, 400, '2026-10-25T10:00:00+00:00')")
        con.execute("INSERT INTO snack (katze_id, produkt_id, zeit, stueck) VALUES (1, 1, '2026-10-25T10:00:00+00:00', 2)")
        con.execute("INSERT INTO snack (katze_id, produkt_id, zeit, stueck, menge_g, kcal) "
                    "VALUES (1, 1, '2026-10-25T11:00:00+00:00', 1, 5, 99)")
    datenbank.migrieren(pfad)
    werte = [tuple(r) for r in con.execute("SELECT menge_g, kcal FROM snack ORDER BY id")]
    assert werte == [(3.0, 12.0), (5.0, 99.0)]


def test_sicherung_ist_vollstaendige_kopie(pfad, tmp_path):
    import datetime
    datenbank.migrieren(pfad)
    ordner = str(tmp_path / "sicherung")
    ziel = datenbank.sicherung(pfad, ordner, datetime.date(2026, 10, 25))
    assert ziel.endswith("katzenfutter-2026-10-25.db")
    kopie = datenbank.verbinden(ziel)
    assert datenbank.schema_stand(kopie) == LETZTE_VERSION
    assert kopie.execute("SELECT name FROM katze").fetchone()[0] == "Katze"
    # gleicher Tag: keine zweite Kopie, nichts überschrieben
    assert datenbank.sicherung(pfad, ordner, datetime.date(2026, 10, 25)) is None
    assert not [n for n in os.listdir(ordner) if n.endswith(".tmp")]


def test_sicherung_behaelt_sieben_tage(pfad, tmp_path):
    import datetime
    datenbank.migrieren(pfad)
    ordner = str(tmp_path / "sicherung")
    os.makedirs(ordner)
    open(os.path.join(ordner, "notiz.txt"), "w").close()
    for tag in range(1, 11):
        datenbank.sicherung(pfad, ordner, datetime.date(2026, 10, tag))
    namen = sorted(os.listdir(ordner))
    assert namen == [f"katzenfutter-2026-10-{t:02d}.db" for t in range(4, 11)] + ["notiz.txt"]


def test_wiederherstellen_spielt_kopie_ein_und_legt_alte_beiseite(pfad, tmp_path):
    import datetime
    datenbank.migrieren(pfad)
    ordner = str(tmp_path / "sicherung")
    kopie = datenbank.sicherung(pfad, ordner, datetime.date(2026, 10, 24))
    con = datenbank.verbinden(pfad)
    with con:
        con.execute("UPDATE katze SET name = 'Neu'")
    con.close()
    assert datenbank.wiederherstellen(pfad, ordner, "20261025-120000") is None  # nichts angefordert
    os.rename(kopie, os.path.join(ordner, "wiederherstellen.db"))
    assert datenbank.wiederherstellen(pfad, ordner, "20261025-120000") == "eingespielt"
    assert datenbank.verbinden(pfad).execute("SELECT name FROM katze").fetchone()[0] == "Katze"
    alt = datenbank.verbinden(os.path.join(ordner, "vor-wiederherstellung-20261025-120000.db"))
    assert alt.execute("SELECT name FROM katze").fetchone()[0] == "Neu"
    assert not os.path.exists(os.path.join(ordner, "wiederherstellen.db"))


def test_wiederherstellen_lehnt_fremde_datei_ab(pfad, tmp_path):
    datenbank.migrieren(pfad)
    ordner = tmp_path / "sicherung"
    ordner.mkdir()
    (ordner / "wiederherstellen.db").write_bytes(b"kein sqlite")
    assert datenbank.wiederherstellen(pfad, str(ordner), "x") == "ungueltig"
    assert (ordner / "wiederherstellen-ungueltig.db").exists()
    assert datenbank.verbinden(pfad).execute("SELECT name FROM katze").fetchone()[0] == "Katze"
