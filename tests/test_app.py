"""Grundtests: Ingress-Schutz und Startseite (laufen ohne Supervisor im Entwicklungsmodus)."""
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


def test_startseite(client):
    c, _ = client
    assert c.get("/", headers=HEADERS).status_code == 200


def test_nur_ingress_ausserhalb_dev(client):
    c, mod = client
    mod.DEV_MODE = False
    assert c.get("/").status_code == 403


@pytest.mark.parametrize("pfad", ["/test", "/api/db", "/api/log", "/ocr", "/ocr_status"])
def test_technik_test_und_fotoerkennung_entfernt(client, pfad):
    c, _ = client
    assert c.get(pfad, headers=HEADERS).status_code in (404, 405)
