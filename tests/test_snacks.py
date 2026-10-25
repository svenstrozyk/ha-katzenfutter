"""Tests für Einstellungen (Haushalt, Snack-Limit), Snacks und „gegeben von“."""
import importlib
import os
import sys

import pytest
from werkzeug.datastructures import MultiDict

ADDON_APP = os.path.join(os.path.dirname(__file__), "..", "katzenfutter", "app")


def kopf(name):
    return {"X-Ingress-Path": "/api/hassio_ingress/test", "X-Remote-User-Display-Name": name}


ALEX, SAM, KIND = kopf("Alex"), kopf("Sam"), kopf("Mia")

# Namen der Kinder sind Platzhalter
HAUSHALT = MultiDict([
    ("name", "Alex"), ("rolle", "erwachsen"), ("ha_name", ""),
    ("name", "Sam"), ("rolle", "erwachsen"), ("ha_name", ""),
    ("name", "Mia"), ("rolle", "kind"), ("ha_name", ""),
    ("name", "Ben"), ("rolle", "kind"), ("ha_name", "ben.kids"),
    ("name", ""), ("rolle", "kind"), ("ha_name", ""),
    ("snack_limit_kinder", "2"),
])


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("DEV_MODE", "1")
    sys.path.insert(0, os.path.abspath(ADDON_APP))
    import app as app_module
    importlib.reload(app_module)
    c = app_module.app.test_client()
    # Mimi 4,2 kg → MER ≈ 287,5 kcal, 10 % ≈ 28,8 kcal
    c.post("/katze", headers=ALEX, data={"name": "Mimi", "gewicht_aktuell": "4,2", "aktivitaetsfaktor": "1.4"})
    # Snack: 400 kcal/100 g, 2 g je Stück → 8 kcal je Stück
    c.post("/produkt", headers=ALEX, data={"marke": "Leckerli", "sorte": "Huhn", "futterart": "snack",
                                           "kcal_100g": "400", "stueck_g": "2"})
    yield c, app_module
    sys.path.pop(0)


def haushalt(c, daten=HAUSHALT, kopfzeilen=ALEX):
    return c.post("/einstellungen", headers=kopfzeilen, data=daten)


def snack(c, kopfzeilen, person=None, stueck="1", **extra):
    daten = {"produkt_id": "1", "stueck": stueck}
    if person:
        daten["person"] = person
    daten.update(extra)
    return c.post("/snack", headers=kopfzeilen, data=daten)


def test_einstellungen_speichern(client):
    c, mod = client
    assert haushalt(c).status_code == 302
    einst = mod.einstellungen.laden(mod.db())
    assert [p["name"] for p in einst["personen"]] == ["Alex", "Sam", "Mia", "Ben"]
    assert einst["snack_limit_kinder"] == 2


def test_nur_erwachsene_duerfen_aendern(client):
    c, _ = client
    haushalt(c)
    html = c.get("/einstellungen", headers=KIND).get_data(as_text=True)
    assert "Nur Erwachsene" in html and "disabled" in html
    assert haushalt(c, kopfzeilen=KIND).status_code == 403
    assert haushalt(c, kopfzeilen=kopf("ben.kids")).status_code == 403
    assert haushalt(c, kopfzeilen=SAM).status_code == 302


def test_selbst_aussperren_verhindert(client):
    c, _ = client
    daten = MultiDict([("name", "Sam"), ("rolle", "erwachsen"), ("ha_name", ""), ("snack_limit_kinder", "")])
    r = haushalt(c, daten, kopfzeilen=ALEX)
    assert r.status_code == 400 and "aussperren" in r.get_data(as_text=True)


@pytest.mark.parametrize("daten, meldung", [
    (MultiDict([("name", "Mia"), ("rolle", "kind"), ("ha_name", "")]), "erwachsen"),
    (MultiDict([("name", "Alex"), ("rolle", "erwachsen"), ("ha_name", ""),
                ("name", "alex"), ("rolle", "kind"), ("ha_name", "")]), "doppelt"),
    (MultiDict([("name", "Alex"), ("rolle", "erwachsen"), ("ha_name", ""), ("snack_limit_kinder", "zwei")]), "ganze Zahl"),
])
def test_ungueltige_einstellungen(client, daten, meldung):
    c, _ = client
    r = haushalt(c, daten)
    assert r.status_code == 400 and meldung in r.get_data(as_text=True)


def test_snack_kcal_und_person(client):
    c, mod = client
    haushalt(c)
    r = snack(c, KIND, stueck="2")
    assert r.status_code == 302
    s = mod.db().execute("SELECT person, erfasst_von, stueck, menge_g, kcal FROM snack").fetchone()
    assert tuple(s) == ("Mia", "Mia", 2, 4, 16)


def test_kind_ueber_handy_der_eltern(client):
    c, mod = client
    haushalt(c)
    snack(c, ALEX, person="Ben")
    s = mod.db().execute("SELECT person, erfasst_von FROM snack").fetchone()
    assert tuple(s) == ("Ben", "Alex")
    html = c.get("/snack", headers=ALEX).get_data(as_text=True)
    assert "Ben (Kind)" in html and "eingetragen von Alex" in html


def test_kind_mit_eigenem_ha_namen_wird_erkannt(client):
    c, mod = client
    haushalt(c)
    html = c.get("/snack", headers=kopf("ben.kids")).get_data(as_text=True)
    assert '<option value="Ben" selected>' in html


def test_limit_der_kinder_zusammen(client):
    c, mod = client
    haushalt(c)
    snack(c, KIND)
    snack(c, ALEX, person="Ben")
    snack(c, ALEX)  # Erwachsene zählen nicht zum Kinderlimit
    html = c.get("/snack", headers=KIND).get_data(as_text=True)
    assert "2 von 2 Stück" in html and "Limit erreicht" in html
    # über dem Limit wird trotzdem gespeichert
    assert snack(c, KIND).status_code == 302
    assert mod.db().execute("SELECT COUNT(*) FROM snack").fetchone()[0] == 4


def test_zehn_prozent_warnung(client):
    c, _ = client
    snack(c, ALEX, stueck="3")  # 24 kcal < 28,8
    assert "10 % des Tagesbedarfs erreicht" not in c.get("/snack", headers=ALEX).get_data(as_text=True)
    snack(c, ALEX, stueck="1")  # 32 kcal
    assert "10 % des Tagesbedarfs erreicht" in c.get("/snack", headers=ALEX).get_data(as_text=True)


def test_snacks_werden_vom_hauptfutter_abgezogen(client):
    c, _ = client
    c.post("/produkt", headers=ALEX, data={"marke": "Animonda", "sorte": "Pute", "kcal_100g": "95", "packung_g": "85"})
    snack(c, ALEX, stueck="2")  # 16 kcal
    html = c.get("/katze?produkt_id=2", headers=ALEX).get_data(as_text=True)
    # (287,5 − 16) / 95 × 100 ≈ 286 g statt 303 g
    assert "− 16 kcal" in html and "286 g" in html


def test_snack_rueckgaengig(client):
    c, mod = client
    snack(c, ALEX)
    r = c.post("/snack_rueckgaengig", headers=ALEX, data={"snack_id": "1"})
    assert "zurueckgenommen=1" in r.headers["Location"]
    assert mod.db().execute("SELECT COUNT(*) FROM snack").fetchone()[0] == 0


def test_hauptfutter_nicht_als_snack(client):
    c, _ = client
    c.post("/produkt", headers=ALEX, data={"marke": "Animonda", "sorte": "Pute", "kcal_100g": "95"})
    r = snack(c, ALEX, produkt_id="2")
    assert r.status_code == 400


def test_snack_ohne_stueckgewicht_mit_menge(client):
    c, mod = client
    c.post("/produkt", headers=ALEX, data={"marke": "Pute", "sorte": "getrocknet", "futterart": "snack", "kcal_100g": "300"})
    snack(c, ALEX, produkt_id="2", menge_g="3")
    snack(c, ALEX, produkt_id="2")
    kcal = [r[0] for r in mod.db().execute("SELECT kcal FROM snack ORDER BY id")]
    assert kcal == [9, None]
    assert "Bei mindestens einem Snack fehlen kcal" in c.get("/snack", headers=ALEX).get_data(as_text=True)


def test_fuettern_mit_person(client):
    c, mod = client
    haushalt(c)
    c.post("/produkt", headers=ALEX, data={"marke": "Animonda", "sorte": "Pute", "packung_g": "85", "bestand_packungen": "3"})
    c.post("/fuettern", headers=SAM, data={"produkt_id": "2", "menge_g": "85", "person": "Mia"})
    m = mod.db().execute("SELECT person, erfasst_von FROM mahlzeit").fetchone()
    assert tuple(m) == ("Mia", "Sam")


def test_kcal_nachtraeglich_ergaenzt_wird_neu_berechnet(client):
    c, mod = client
    # Snack ohne Stückgewicht und kcal erfasst
    c.post("/produkt", headers=ALEX, data={"marke": "Z", "sorte": "Schleckies", "futterart": "snack"})
    snack(c, ALEX, produkt_id="2", stueck="2")
    assert mod.db().execute("SELECT kcal FROM snack WHERE produkt_id = 2").fetchone()[0] is None
    # Werte im Futter ergänzt → Snack wird neu berechnet (2 × 1,5 g × 400 kcal/100 g = 12 kcal)
    r = c.post("/produkt", headers=ALEX, data={"id": "2", "marke": "Z", "sorte": "Schleckies", "futterart": "snack",
                                               "kcal_100g": "400", "stueck_g": "1,5"})
    assert "neu_berechnet=1" in r.headers["Location"]
    s = mod.db().execute("SELECT menge_g, kcal FROM snack WHERE produkt_id = 2").fetchone()
    assert tuple(s) == (3.0, 12.0)
    assert "12 kcal" in c.get("/snack", headers=ALEX).get_data(as_text=True)
    # Stückgewicht korrigiert: abgeleitete Menge folgt
    c.post("/produkt", headers=ALEX, data={"id": "2", "marke": "Z", "sorte": "Schleckies", "futterart": "snack",
                                           "kcal_100g": "400", "stueck_g": "2"})
    assert tuple(mod.db().execute("SELECT menge_g, kcal FROM snack WHERE produkt_id = 2").fetchone()) == (4.0, 16.0)


def test_von_hand_eingetragene_gramm_bleiben(client):
    c, mod = client
    snack(c, ALEX, stueck="1", menge_g="5")  # 5 g statt 1 × 2 g
    c.post("/produkt", headers=ALEX, data={"id": "1", "marke": "Leckerli", "sorte": "Huhn", "futterart": "snack",
                                           "kcal_100g": "300", "stueck_g": "2"})
    assert tuple(mod.db().execute("SELECT menge_g, kcal FROM snack").fetchone()) == (5.0, 15.0)


def test_mahlzeit_kcal_folgt_korrektur(client):
    c, mod = client
    c.post("/produkt", headers=ALEX, data={"marke": "A", "sorte": "Pute", "packung_g": "100", "bestand_packungen": "3"})
    c.post("/fuettern", headers=ALEX, data={"produkt_id": "2", "menge_g": "100"})
    c.post("/rest", headers=ALEX, data={"id": "1", "stufe": "wenig"})
    assert mod.db().execute("SELECT kcal FROM mahlzeit").fetchone()[0] is None
    c.post("/produkt", headers=ALEX, data={"id": "2", "marke": "A", "sorte": "Pute", "packung_g": "100",
                                           "bestand_packungen": "2", "kcal_100g": "90"})
    assert mod.db().execute("SELECT kcal FROM mahlzeit").fetchone()[0] == pytest.approx(81)


def test_unveraendertes_futter_rechnet_nicht(client):
    c, mod = client
    snack(c, ALEX)
    r = c.post("/produkt", headers=ALEX, data={"id": "1", "marke": "Leckerli", "sorte": "Huhn neu", "futterart": "snack",
                                               "kcal_100g": "400", "stueck_g": "2"})
    assert "neu_berechnet" not in r.headers["Location"]
