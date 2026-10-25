"""Tests für die Barcode-Erfassung (Serverseite; Dekodierung läuft im Browser)."""
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
    yield app_module.app.test_client(), app_module
    sys.path.pop(0)


def anlegen(c, ean):
    return c.post("/produkt", headers=HEADERS, data={"marke": "Animonda", "sorte": "Pute", "ean": ean})


def test_scan_seite_laedt_zxing_relativ(client):
    c, _ = client
    html = c.get("/scan", headers=HEADERS).get_data(as_text=True)
    assert 'src="static/zxing/zxing-library-0.23.0.min.js"' in html
    assert 'href="/' not in html and 'src="/' not in html


def test_zxing_wird_ausgeliefert(client):
    c, _ = client
    r = c.get("/static/zxing/zxing-library-0.23.0.min.js", headers=HEADERS)
    assert r.status_code == 200
    assert b"ZXing" in r.data[:1000]


def test_bekannte_ean_oeffnet_futter(client):
    c, _ = client
    anlegen(c, "96385074")
    r = c.get("/scan?ean=96385074", headers=HEADERS)
    assert r.status_code == 302
    assert r.headers["Location"].endswith("/api/hassio_ingress/test/produkt?id=1")


def test_unbekannte_ean_legt_neues_futter_an(client):
    c, _ = client
    r = c.get("/scan?ean=96385074", headers=HEADERS)
    assert r.status_code == 302
    assert r.headers["Location"].endswith("/api/hassio_ingress/test/produkt?ean=96385074")


def test_upc_a_und_ean13_mit_null_sind_gleich(client):
    c, _ = client
    anlegen(c, "036000291452")
    r = c.get("/scan?ean=0036000291452", headers=HEADERS)
    assert r.headers["Location"].endswith("produkt?id=1")


def test_ungueltige_ean(client):
    c, _ = client
    r = c.get("/scan?ean=4006040000001", headers=HEADERS)
    assert r.status_code == 400
    assert "keine gültige EAN" in r.get_data(as_text=True)


def test_leerzeichen_in_ean_werden_entfernt(client):
    c, _ = client
    r = c.get("/scan?ean=9638%205074", headers=HEADERS)
    assert r.headers["Location"].endswith("produkt?ean=96385074")
