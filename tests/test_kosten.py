"""Tests für die Kostenauswertung (Beträge von Hand gerechnet)."""
import datetime
import importlib
import os
import sys

import pytest

ADDON_APP = os.path.join(os.path.dirname(__file__), "..", "katzenfutter", "app")
HEADERS = {"X-Ingress-Path": "/api/hassio_ingress/test", "X-Remote-User-Display-Name": "Alex"}


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("DEV_MODE", "1")
    sys.path.insert(0, os.path.abspath(ADDON_APP))
    import app as app_module
    importlib.reload(app_module)
    c = app_module.app.test_client()
    # Sorte 1: 100 g für 1,00 € (1 ct/g), 100 kcal/100 g → 1,00 € je 100 kcal
    c.post("/produkt", headers=HEADERS, data={"marke": "A", "sorte": "Pute", "packung_g": "100", "preis": "1,00",
                                              "kcal_100g": "100", "bestand_packungen": "20"})
    # Sorte 2: 85 g für 0,85 €, 80 kcal/100 g → 1,25 € je 100 kcal
    c.post("/produkt", headers=HEADERS, data={"marke": "A", "sorte": "Rind", "packung_g": "85", "preis": "0,85",
                                              "kcal_100g": "80", "bestand_packungen": "20"})
    # Sorte 3: ohne Preis
    c.post("/produkt", headers=HEADERS, data={"marke": "B", "sorte": "Huhn", "packung_g": "100", "bestand_packungen": "5"})
    # Snack: 60 g für 3,00 € (5 ct/g), 2 g je Stück
    c.post("/produkt", headers=HEADERS, data={"marke": "D", "sorte": "Leckerli", "futterart": "snack", "packung_g": "60",
                                              "preis": "3", "stueck_g": "2", "kcal_100g": "400"})
    yield c, app_module
    sys.path.pop(0)


def test_kosten_mit_rest_snack_und_fehlendem_preis(client):
    c, mod = client
    c.post("/fuettern", headers=HEADERS, data={"produkt_id": "1", "menge_g": "100"})   # 1,00 €
    c.post("/rest", headers=HEADERS, data={"id": "1", "stufe": "wenig"})               # 10 g übrig = 0,10 €
    c.post("/fuettern", headers=HEADERS, data={"produkt_id": "2", "menge_g": "42,5"})  # 0,425 €
    c.post("/fuettern", headers=HEADERS, data={"produkt_id": "3", "menge_g": "50"})    # ohne Preis
    c.post("/snack", headers=HEADERS, data={"produkt_id": "4", "stueck": "3"})         # 6 g = 0,30 €
    k = mod.kosten_modul.auswerten(mod.db(), 1, 30)
    assert k["gesamt"] == pytest.approx(1.725)
    assert k["weggeworfen"] == pytest.approx(0.10)
    assert k["tage_mit_daten"] == 1 and k["je_tag"] == pytest.approx(1.725)
    assert k["je_monat"] == pytest.approx(1.725 * 30.44)
    assert [e["produkt"]["sorte"] for e in k["sorten"]] == ["Pute", "Rind", "Leckerli"]
    assert [p["sorte"] for p in k["ohne_preis"]] == ["Huhn"]
    html = c.get("/kosten", headers=HEADERS).get_data(as_text=True)
    assert "1,73 €" in html and "0,10 €" in html and "Huhn" in html and "Snack" in html


def test_tagesschnitt_ueber_tage_mit_daten(client):
    c, mod = client
    c.post("/fuettern", headers=HEADERS, data={"produkt_id": "1", "menge_g": "100"})
    c.post("/fuettern", headers=HEADERS, data={"produkt_id": "1", "menge_g": "100"})
    vor_4_tagen = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=4)
    con = mod.db()
    with con:
        con.execute("UPDATE mahlzeit SET zeit = ? WHERE id = 1", (vor_4_tagen.isoformat(timespec="seconds"),))
    k = mod.kosten_modul.auswerten(con, 1, 30)
    assert k["tage_mit_daten"] == 5 and k["je_tag"] == pytest.approx(2.0 / 5)


def test_preisvergleich_je_100_kcal(client):
    _, mod = client
    v = mod.kosten_modul.preisvergleich(mod.db())
    werte = {e["produkt"]["sorte"]: e for e in v}
    assert werte["Pute"]["je_100kcal"] == pytest.approx(1.00)
    assert werte["Rind"]["je_100kcal"] == pytest.approx(1.25)
    assert werte["Huhn"]["je_100kcal"] is None and werte["Huhn"]["je_100g"] is None
    assert [e["produkt"]["sorte"] for e in v][:2] == ["Pute", "Rind"]  # günstigste je kcal zuerst, ohne Preis am Ende
    assert v[-1]["je_100kcal"] is None


def test_leerer_zeitraum_und_auswahl(client):
    c, _ = client
    html = c.get("/kosten?tage=999", headers=HEADERS).get_data(as_text=True)
    assert "Noch keine Mahlzeiten" in html and 'href="kosten?tage=30" aria-pressed="true"' in html
    assert 'href="/' not in html


def test_kosten_sensor(client):
    c, mod = client
    c.post("/fuettern", headers=HEADERS, data={"produkt_id": "1", "menge_g": "100"})
    con = mod.db()
    z = mod.mqtt_sensoren.zustand(con, mod.aktive_katze(con))
    assert z["futterkosten_30_tage"] == 1.0
    eintraege = dict(mod.mqtt_sensoren.discovery(mod.aktive_katze(con)))
    k = eintraege["homeassistant/sensor/katzenfutter_1/futterkosten_30_tage/config"]
    assert k["device_class"] == "monetary" and k["unit_of_measurement"] == "EUR"
