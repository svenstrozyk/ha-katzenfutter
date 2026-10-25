"""Tests für die Rechte: Stammdaten ändern nur Erwachsene, Kinder erfassen und sehen."""
import importlib
import os
import sys

import pytest
from werkzeug.datastructures import MultiDict

ADDON_APP = os.path.join(os.path.dirname(__file__), "..", "katzenfutter", "app")


def kopf(name):
    return {"X-Ingress-Path": "/api/hassio_ingress/test", "X-Remote-User-Display-Name": name}


ALEX, KIND, FREMD = kopf("Alex"), kopf("Mia"), kopf("Gast")

# Namen der Kinder sind Platzhalter
HAUSHALT = MultiDict([
    ("name", "Alex"), ("rolle", "erwachsen"), ("ha_name", ""),
    ("name", "Mia"), ("rolle", "kind"), ("ha_name", ""),
])


def laden(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("DEV_MODE", "1")
    sys.path.insert(0, os.path.abspath(ADDON_APP))
    import app as app_module
    importlib.reload(app_module)
    return app_module


@pytest.fixture()
def client(tmp_path, monkeypatch):
    mod = laden(tmp_path, monkeypatch)
    c = mod.app.test_client()
    c.post("/katze", headers=ALEX, data={"name": "Mimi", "gewicht_aktuell": "4,2", "aktivitaetsfaktor": "1.4"})
    c.post("/produkt", headers=ALEX, data={"marke": "Animonda", "sorte": "Pute", "futterart": "allein",
                                           "packung_g": "85", "kcal_100g": "100"})
    assert c.post("/einstellungen", headers=ALEX, data=HAUSHALT).status_code == 302
    yield c, mod
    sys.path.pop(0)


@pytest.mark.parametrize("pfad, daten", [
    ("/katze", {"name": "Mimi", "gewicht_aktuell": "9"}),
    ("/katze_neu", {"name": "Luna"}),
    ("/katze_entfernen", {"id": "1"}),
    ("/produkt", {"id": "1", "marke": "X", "sorte": "Y", "futterart": "allein"}),
    ("/sperren", {"id": "1"}),
    ("/verlauf", {"kg": "3,0"}),
    ("/wiegung_umschalten", {"id": "1"}),
    ("/mahlzeit_loeschen", {"id": "1"}),
])
def test_kind_darf_stammdaten_nicht_aendern(client, pfad, daten):
    c, mod = client
    assert c.post(pfad, headers=KIND, data=daten).status_code == 403
    assert mod.db().execute("SELECT gewicht_aktuell FROM katze WHERE id = 1").fetchone()[0] == 4.2


@pytest.mark.parametrize("kopfzeilen", [KIND, FREMD])
def test_kinder_und_unbekannte_sind_gesperrt(client, kopfzeilen):
    c, _ = client
    assert c.post("/katze_neu", headers=kopfzeilen, data={"name": "Luna"}).status_code == 403


def test_erwachsene_duerfen_aendern(client):
    c, mod = client
    assert c.post("/katze_neu", headers=ALEX, data={"name": "Luna"}).status_code == 302
    assert mod.db().execute("SELECT COUNT(*) FROM katze WHERE aktiv = 1").fetchone()[0] == 2


def test_kind_darf_erfassen(client):
    c, mod = client
    assert c.post("/fuettern", headers=KIND, data={"produkt_id": "1", "menge_g": "85"}).status_code == 302
    assert c.post("/gesundheit", headers=KIND, data={"typ": "erbrechen"},
                  content_type="multipart/form-data").status_code == 302
    assert mod.db().execute("SELECT COUNT(*) FROM mahlzeit").fetchone()[0] == 1
    assert mod.db().execute("SELECT COUNT(*) FROM ereignis").fetchone()[0] == 1


def test_kind_sieht_alles_ohne_bearbeiten(client):
    c, _ = client
    for pfad in ["/", "/katze", "/futter", "/verlauf", "/produkt?id=1"]:
        assert c.get(pfad, headers=KIND).status_code == 200, pfad
    text = c.get("/katze", headers=KIND).get_data(as_text=True)
    assert "Nur Erwachsene" in text and 'action="katze_neu"' not in text
    assert "ohne Barcode anlegen" not in c.get("/futter", headers=KIND).get_data(as_text=True)
    assert "Gewicht eintragen" not in c.get("/verlauf", headers=KIND).get_data(as_text=True)
    assert "ohne Barcode anlegen" in c.get("/futter", headers=ALEX).get_data(as_text=True)


def test_ohne_personen_darf_jeder_aendern(tmp_path, monkeypatch):
    mod = laden(tmp_path, monkeypatch)
    try:
        c = mod.app.test_client()
        assert c.post("/katze_neu", headers=FREMD, data={"name": "Luna"}).status_code == 302
    finally:
        sys.path.pop(0)
