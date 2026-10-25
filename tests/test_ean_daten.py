"""Tests für Produktdaten per EAN (Open Pet Food Facts, ohne Netzwerk)."""
import importlib
import json
import os
import sys

import pytest

ADDON_APP = os.path.join(os.path.dirname(__file__), "..", "katzenfutter", "app")
HEADERS = {"X-Ingress-Path": "/api/hassio_ingress/test", "X-Remote-User-Display-Name": "Alex"}

# Auszug im Format der OFF-API (Werte wie in Open Pet Food Facts für Animonda Carny Rind+Huhn, 2026-10-25)
CARNY = {"status": 1, "product": {
    "product_name": "Carny Adult Rind+Huhn", "brands": "Animonda", "quantity": "400g",
    "ingredients_text_de": "35 % Rind (Rinderlunge, Rinderherz), 30 % Huhn (Huhnleber), Calciumcarbonat",
    "categories": "Katzennassfutter", "labels": "Hergestellt in Deutschland",
    "nutriments": {"crude-protein_100g": 10.5, "crude-fat_100g": 6.5, "crude-ash_100g": 2.1,
                   "crude-fibre_100g": 0.5, "moisture_100g": 79, "fat_100g": 0.65, "proteins_100g": 1.15}}}


class Antwort:
    def __init__(self, status_code, daten=None):
        self.status_code, self._daten = status_code, daten

    def raise_for_status(self):
        if self.status_code >= 400:
            raise mod_requests.HTTPError(str(self.status_code))

    def json(self):
        return self._daten


mod_requests = None


@pytest.fixture()
def mod(tmp_path, monkeypatch):
    global mod_requests
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("DEV_MODE", "1")
    sys.path.insert(0, os.path.abspath(ADDON_APP))
    import app as app_module
    importlib.reload(app_module)
    mod_requests = app_module.ean_daten.requests
    yield app_module
    sys.path.pop(0)


def test_zuordnung_carny(mod):
    w = mod.ean_daten.zuordnen(CARNY["product"])
    assert w == {"marke": "Animonda", "sorte": "Carny Adult Rind+Huhn", "packung_g": 400.0, "rohprotein": 10.5,
                 "rohfett": 6.5, "rohasche": 2.1, "rohfaser": 0.5, "feuchte": 79.0, "proteine": "Rind, Huhn"}


@pytest.mark.parametrize("menge, gramm", [("400g", 400), ("85 g", 85), ("12 x 85 g", 85), ("6×100g", 100),
                                          ("0,4 kg", 400), ("", None), ("Dose", None)])
def test_packungsgroesse(mod, menge, gramm):
    assert mod.ean_daten.packungsgroesse({"quantity": menge}) == gramm


def test_marke_im_namen_wird_entfernt_und_snack_erkannt(mod):
    w = mod.ean_daten.zuordnen({"product_name": "Dreamies Huhn", "brands": "Dreamies, Mars", "categories": "Katzensnacks"})
    assert w == {"marke": "Dreamies", "sorte": "Huhn", "futterart": "snack"}


def test_ersatzquelle_bei_404(mod, monkeypatch):
    aufrufe = []

    def get(url, **kw):
        aufrufe.append(url)
        return Antwort(404) if "openpetfoodfacts" in url else Antwort(200, CARNY)

    monkeypatch.setattr(mod.ean_daten.requests, "get", get)
    quelle, werte = mod.ean_daten.abfragen("4017721837194")
    assert quelle == "Open Food Facts" and werte["rohprotein"] == 10.5 and len(aufrufe) == 2
    # nur die EAN wird übertragen
    assert all(u.endswith("/4017721837194.json") for u in aufrufe)


def test_unbekannt_und_netzfehler(mod, monkeypatch):
    def get(url, **kw):
        if "openpetfoodfacts" in url:
            raise mod.ean_daten.requests.ConnectionError("offline")
        return Antwort(200, {"status": 0})

    monkeypatch.setattr(mod.ean_daten.requests, "get", get)
    assert mod.ean_daten.abfragen("4017721834056") == (None, {})


def test_route(mod, monkeypatch):
    monkeypatch.setattr(mod.ean_daten.requests, "get", lambda url, **kw: Antwort(200, CARNY))
    c = mod.app.test_client()
    r = c.get("/ean_daten?ean=4017721837194", headers=HEADERS)
    assert r.json["ok"] and r.json["quelle"] == "Open Pet Food Facts" and r.json["werte"]["feuchte"] == 79
    assert c.get("/ean_daten?ean=123", headers=HEADERS).status_code == 400
    # nichts gespeichert
    assert mod.db().execute("SELECT COUNT(*) FROM produkt").fetchone()[0] == 0


def test_route_abgeschaltet(mod, monkeypatch, tmp_path):
    (tmp_path / "options.json").write_text(json.dumps({"online_produktdaten": False}))
    monkeypatch.setattr(mod.ean_daten.requests, "get", lambda *a, **k: pytest.fail("darf nicht abfragen"))
    r = mod.app.test_client().get("/ean_daten?ean=4017721837194", headers=HEADERS)
    assert r.status_code == 403


def test_formular_fragt_nach_scan_automatisch(mod):
    c = mod.app.test_client()
    assert "eanDaten(true);" in c.get("/produkt?ean=4017721837194", headers=HEADERS).get_data(as_text=True)
    assert "eanDaten(true);" not in c.get("/produkt", headers=HEADERS).get_data(as_text=True)
    assert "Daten zur EAN suchen" in c.get("/produkt", headers=HEADERS).get_data(as_text=True)
