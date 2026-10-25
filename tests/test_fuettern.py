"""Tests für die Fütterung und die Bestandsfortschreibung."""
import datetime
import importlib
import os
import sys

import pytest

ADDON_APP = os.path.join(os.path.dirname(__file__), "..", "katzenfutter", "app")
HEADERS = {"X-Ingress-Path": "/api/hassio_ingress/test", "X-Remote-User-Display-Name": "Sam"}


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("DEV_MODE", "1")
    sys.path.insert(0, os.path.abspath(ADDON_APP))
    import app as app_module
    importlib.reload(app_module)
    yield app_module.app.test_client(), app_module
    sys.path.pop(0)


def futter(c, sorte="Pute", packungen="10", angebrochen="", packung="85", **extra):
    daten = {"marke": "Animonda", "sorte": sorte, "packung_g": packung, "bestand_packungen": packungen,
             "bestand_angebrochen_g": angebrochen}
    daten.update(extra)
    assert c.post("/produkt", headers=HEADERS, data=daten).status_code == 302


def bestand(mod, produkt_id=1):
    return tuple(mod.db().execute("SELECT packungen, angebrochen_g FROM bestand WHERE produkt_id = ?",
                                  (produkt_id,)).fetchone())


def fuettern(c, produkt_id=1, menge="85", uhrzeit=""):
    return c.post("/fuettern", headers=HEADERS, data={"produkt_id": produkt_id, "menge_g": menge, "uhrzeit": uhrzeit})


def test_ganze_packung_oeffnet_neue(client):
    c, mod = client
    futter(c)
    r = fuettern(c)
    assert r.status_code == 302 and "gespeichert=1" in r.headers["Location"]
    m = mod.db().execute("SELECT * FROM mahlzeit").fetchone()
    assert (m["angeboten_g"], m["person"], m["neue_packungen"], m["gefressen_g"], m["kcal"]) == (85, "Sam", 1, None, None)
    assert bestand(mod) == (9, None)


def test_halbe_packung_hinterlaesst_angebrochene(client):
    c, mod = client
    futter(c)
    fuettern(c, menge="42,5")
    assert bestand(mod) == (9, 42.5)
    # zweite Hälfte kommt aus der angebrochenen Packung
    fuettern(c, menge="42,5")
    assert bestand(mod) == (9, None)


def test_angebrochene_zuerst_dann_neue(client):
    c, mod = client
    futter(c, angebrochen="30")
    fuettern(c, menge="50")
    # 30 g aus der angebrochenen, eine neue geöffnet, 65 g bleiben angebrochen
    assert bestand(mod) == (9, 65)


def test_zu_wenig_bestand_wird_gemeldet(client):
    c, mod = client
    futter(c, packungen="0")
    r = fuettern(c)
    assert "Bestand+war+zu+niedrig" in r.headers["Location"] or "Bestand%20war" in r.headers["Location"]
    assert bestand(mod) == (0, None)


def test_ohne_packungsgroesse_bleibt_bestand(client):
    c, mod = client
    futter(c, packung="")
    fuettern(c, menge="60")
    assert bestand(mod) == (10, None)
    assert mod.db().execute("SELECT COUNT(*) FROM mahlzeit").fetchone()[0] == 1


def test_rueckgaengig_stellt_bestand_wieder_her(client):
    c, mod = client
    futter(c, angebrochen="30")
    fuettern(c, menge="50")
    html = c.get("/fuettern?gespeichert=1", headers=HEADERS).get_data(as_text=True)
    assert "Rückgängig" in html
    r = c.post("/rueckgaengig", headers=HEADERS, data={"mahlzeit_id": "1"})
    assert "zurueckgenommen=1" in r.headers["Location"]
    assert bestand(mod) == (10, 30)
    assert mod.db().execute("SELECT COUNT(*) FROM mahlzeit").fetchone()[0] == 0


def test_rueckgaengig_ohne_neue_packung(client):
    c, mod = client
    futter(c, angebrochen="60")
    fuettern(c, menge="20")
    assert bestand(mod) == (10, 40)
    c.post("/rueckgaengig", headers=HEADERS, data={"mahlzeit_id": "1"})
    assert bestand(mod) == (10, 60)


def test_rueckgaengig_nur_fuer_juengste_mahlzeit(client):
    c, mod = client
    futter(c)
    fuettern(c, menge="40")
    fuettern(c, menge="40")
    r = c.post("/rueckgaengig", headers=HEADERS, data={"mahlzeit_id": "1"})
    assert "zurueckgenommen=0" in r.headers["Location"]
    assert mod.db().execute("SELECT COUNT(*) FROM mahlzeit").fetchone()[0] == 2


def test_rueckgaengig_nach_30_minuten_nicht_mehr(client):
    c, mod = client
    futter(c)
    fuettern(c)
    alt = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=31)).isoformat(timespec="seconds")
    con = mod.db()
    with con:
        con.execute("UPDATE mahlzeit SET erfasst = ?", (alt,))
    r = c.post("/rueckgaengig", headers=HEADERS, data={"mahlzeit_id": "1"})
    assert "zurueckgenommen=0" in r.headers["Location"]


def test_uhrzeit_heute_wird_gespeichert(client):
    c, mod = client
    futter(c)
    fuettern(c, uhrzeit="00:01")
    m = mod.db().execute("SELECT zeit FROM mahlzeit").fetchone()
    assert mod.zeit.lokal(m["zeit"]).strftime("%H:%M") == "00:01"


@pytest.mark.parametrize("daten, meldung", [
    ({"menge_g": "85"}, "Bitte ein Futter wählen"),
    ({"produkt_id": "1", "menge_g": "0"}, "zwischen 1 und 2000"),
    ({"produkt_id": "1", "menge_g": "viel"}, "Menge bitte in g"),
    ({"produkt_id": "1", "menge_g": "85", "uhrzeit": "25:99"}, "HH:MM"),
])
def test_ungueltige_fuetterung(client, daten, meldung):
    c, mod = client
    futter(c)
    r = c.post("/fuettern", headers=HEADERS, data=daten)
    assert r.status_code == 400
    assert meldung in r.get_data(as_text=True)
    assert mod.db().execute("SELECT COUNT(*) FROM mahlzeit").fetchone()[0] == 0


def test_snacks_und_gesperrte_nicht_in_auswahl(client):
    c, _ = client
    futter(c, sorte="Pute")
    futter(c, sorte="Leckerli", futterart="snack")
    futter(c, sorte="Abgelehnt", status="gesperrt")
    html = c.get("/fuettern", headers=HEADERS).get_data(as_text=True)
    assert "Pute" in html and "Leckerli" not in html and "Abgelehnt" not in html
    r = fuettern(c, produkt_id=2)
    assert r.status_code == 400


def test_angebrochene_sorte_steht_oben_und_ist_gewaehlt(client):
    c, _ = client
    futter(c, sorte="Aaa Rind")
    futter(c, sorte="Zzz Pute", angebrochen="40")
    html = c.get("/fuettern", headers=HEADERS).get_data(as_text=True)
    assert html.index("Zzz Pute") < html.index("Aaa Rind")
    assert 'value="2" style' in html.split("checked")[0][-300:]


def test_heute_liste(client):
    c, _ = client
    futter(c)
    fuettern(c, menge="40")
    html = c.get("/fuettern", headers=HEADERS).get_data(as_text=True)
    assert "Sam" in html and "40 g" in html


def test_scan_aus_fuettern_waehlt_sorte(client):
    c, _ = client
    futter(c, ean="96385074")
    r = c.get("/scan?ziel=fuettern&ean=96385074", headers=HEADERS)
    assert r.headers["Location"].endswith("/fuettern?produkt_id=1")
    html = c.get("/scan?ziel=fuettern", headers=HEADERS).get_data(as_text=True)
    assert 'name="ziel" value="fuettern"' in html


def test_lange_liste_wird_aufgeteilt(client):
    c, mod = client
    for i in range(8):
        futter(c, sorte=f"Sorte {i}", marke="Animonda" if i < 5 else "Carny")
    futter(c, sorte="Leer", packungen="0")
    fuettern(c, produkt_id=3, menge="40")  # angebrochen → oben zuerst
    oben, weitere = mod.mahlzeiten.auswahl_aufteilen(mod.mahlzeiten.produkte_zum_fuettern(mod.db()))
    assert len(oben) == 4 and oben[0]["id"] == 3
    assert all(p["packungen"] or p["angebrochen_g"] for p in oben)
    assert len(weitere) == 5 and {p["sorte"] for p in weitere} >= {"Leer"}
    leer = next(p for p in weitere if p["sorte"] == "Leer")
    assert leer["vorraetig"] is False
    html = c.get("/fuettern", headers=HEADERS).get_data(as_text=True)
    assert "Weitere Sorten (5)" in html and 'id="suche"' not in html  # Suche erst ab 7 weiteren
    assert "nicht vorrätig" in html and "<h2>Carny</h2>" in html
    assert html.count('type="radio"') == 9 and html.count("checked>") == 1
    assert '<details class="weitere" open>' not in html  # gewählt ist eine Sorte von oben


def test_gewaehlte_weitere_sorte_klappt_auf(client):
    c, _ = client
    for i in range(6):
        futter(c, sorte=f"Sorte {i}")
    html = c.get("/fuettern?produkt_id=6", headers=HEADERS).get_data(as_text=True)
    assert '<details class="weitere" open>' in html


def test_ohne_vorrat_stehen_trotzdem_sorten_oben(client):
    c, mod = client
    futter(c, sorte="A", packungen="0")
    futter(c, sorte="B", packungen="0")
    oben, weitere = mod.mahlzeiten.auswahl_aufteilen(mod.mahlzeiten.produkte_zum_fuettern(mod.db()))
    assert len(oben) == 2 and weitere == []
