"""Tests für einstellbare Schwellen."""
import datetime
import importlib
import os
import sys

import pytest
from werkzeug.datastructures import MultiDict

ADDON_APP = os.path.join(os.path.dirname(__file__), "..", "katzenfutter", "app")
HEADERS = {"X-Ingress-Path": "/api/hassio_ingress/test", "X-Remote-User-Display-Name": "Alex"}
BASIS = [("name", "Alex"), ("rolle", "erwachsen"), ("ha_name", ""), ("snack_limit_kinder", "")]


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("DEV_MODE", "1")
    sys.path.insert(0, os.path.abspath(ADDON_APP))
    import app as app_module
    importlib.reload(app_module)
    yield app_module.app.test_client(), app_module
    sys.path.pop(0)


def speichern(c, **schwellen):
    return c.post("/einstellungen", headers=HEADERS,
                  data=MultiDict(BASIS + [("s_" + k, v) for k, v in schwellen.items()]))


def test_standard_ohne_einstellung(client):
    _, mod = client
    assert mod.schwellen.laden(mod.db()) == mod.schwellen.STANDARD


def test_abweichungen_speichern_und_leer_ist_standard(client):
    c, mod = client
    assert speichern(c, keine_aufnahme_stunden="36", gewicht_verlust_woche="1,5", liebling_n="5").status_code == 302
    s = mod.schwellen.laden(mod.db())
    assert s["keine_aufnahme_stunden"] == 36 and s["gewicht_verlust_woche"] == 1.5
    # gleich Standard → nicht als Abweichung gespeichert
    assert mod.schwellen.abweichungen(mod.db()) == {"keine_aufnahme_stunden": 36, "gewicht_verlust_woche": 1.5}
    html = c.get("/einstellungen", headers=HEADERS).get_data(as_text=True)
    assert 'value="36"' in html and 'value="1,50"' in html and "Standard 24" in html
    speichern(c)
    assert mod.schwellen.laden(mod.db()) == mod.schwellen.STANDARD


@pytest.mark.parametrize("feld, wert, meldung", [
    ("keine_aufnahme_stunden", "2", "zwischen 6 und 72"),
    ("liebling_n", "4,5", "ganze Zahl"),
    ("gewicht_verlust_woche", "viel", "Zahl"),
])
def test_ungueltige_schwellen(client, feld, wert, meldung):
    c, mod = client
    r = speichern(c, **{feld: wert})
    assert r.status_code == 400 and meldung in r.get_data(as_text=True)
    assert mod.schwellen.abweichungen(mod.db()) == {}


def test_kind_darf_schwellen_nicht_aendern(client):
    c, _ = client
    speichern(c)
    r = c.post("/einstellungen", headers={**HEADERS, "X-Remote-User-Display-Name": "Mia"},
               data=MultiDict(BASIS + [("s_liebling_n", "2")]))
    assert r.status_code == 403


def test_keine_aufnahme_schwelle_wirkt(client):
    c, mod = client
    c.post("/produkt", headers=HEADERS, data={"marke": "A", "sorte": "Pute", "packung_g": "100", "bestand_packungen": "5"})
    c.post("/fuettern", headers=HEADERS, data={"produkt_id": "1", "menge_g": "100"})
    c.post("/rest", headers=HEADERS, data={"id": "1", "stufe": "nichts"})
    alt = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=30)).isoformat(timespec="seconds")
    con = mod.db()
    with con:
        con.execute("UPDATE mahlzeit SET zeit = ?", (alt,))
    assert "Seit mehr als 24 Stunden" in c.get("/", headers=HEADERS).get_data(as_text=True)
    speichern(c, keine_aufnahme_stunden="36")
    assert "keine Futteraufnahme" not in c.get("/", headers=HEADERS).get_data(as_text=True)


def test_gewichtsschwelle_wirkt(client):
    _, mod = client
    heute = datetime.date(2026, 10, 25)
    trend = {heute - datetime.timedelta(days=7): 4.20, heute: 4.13}  # −1,7 %
    assert mod.verlauf_modul.gewichtshinweise(trend) == []
    s = dict(mod.schwellen.STANDARD, gewicht_verlust_woche=1.5)
    assert any("einer Woche" in h for h in mod.verlauf_modul.gewichtshinweise(trend, s=s))


def test_praeferenzschwelle_wirkt(client):
    _, mod = client
    p = mod.praeferenz
    assert p.einstufen(0.08, 6, 0) == "neutral"
    s = dict(mod.schwellen.STANDARD, liebling_score=0.05)
    assert p.einstufen(0.08, 6, 0, s) == "liebling"
    assert p.einstufen(-0.15, 3, 0, dict(mod.schwellen.STANDARD, abgelehnt_score=0.10)) == "abgelehnt"
