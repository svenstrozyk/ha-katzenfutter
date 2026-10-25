"""Tests für die Auswertung erkannter Deklarationstexte (Beispieltexte, keine echten Etiketten)."""
import importlib
import os
import sys

import pytest

ADDON_APP = os.path.join(os.path.dirname(__file__), "..", "katzenfutter", "app")
HEADERS = {"X-Ingress-Path": "/api/hassio_ingress/test", "X-Remote-User-Display-Name": "Alex"}

ETIKETT = """Alleinfuttermittel für Katzen
Zusammensetzung: Fleisch und tierische Nebenerzeugnisse (Rind 25 %, Pute 20 %, Herz),
Mineralstoffe. Ohne Getreide, ohne Zuckerzusatz.
Analytische Bestandteile: Protein 10,5 %, Fettgehalt 5,5 %, Rohasche 2,0 %,
Rohfaser 0,5 %, Feuchtigkeit 80,0 %.
Energie: 95 kcal/100 g"""

OCR_FEHLER = """ZUSAMMENSETZUNG Fleisch (Huhn 30%), Lachs 4%
Analytische Bestandteile Rohprotein 11 . 0 % Rohfett 6,0°/o Rohasche 2,5 %
Rohfaser 0,3 % Feuchte 79 %
Brennwert 1050 kcal/kg"""


@pytest.fixture()
def mod(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("DEV_MODE", "1")
    sys.path.insert(0, os.path.abspath(ADDON_APP))
    import app as app_module
    importlib.reload(app_module)
    yield app_module
    sys.path.pop(0)


def test_typisches_etikett(mod):
    w = mod.texterkennung.auswerten(ETIKETT)
    assert w == {"rohprotein": 10.5, "rohfett": 5.5, "rohasche": 2.0, "rohfaser": 0.5, "feuchte": 80.0,
                 "kcal_100g": 95.0, "proteine": "Rind, Pute", "getreidefrei": 1, "zuckerfrei": 1}


def test_typische_lesefehler(mod):
    w = mod.texterkennung.auswerten(OCR_FEHLER)
    assert w["rohprotein"] == 11.0 and w["rohfett"] == 6.0 and w["rohasche"] == 2.5
    assert w["rohfaser"] == 0.3 and w["feuchte"] == 79
    assert w["kcal_100g"] == 105  # 1050 kcal/kg
    assert w["proteine"] == "Huhn, Lachs"
    assert "getreidefrei" not in w


def test_fett_in_fettsaeuren_vor_dem_abschnitt_zaehlt_nicht(mod):
    text = "Mit Omega-3-Fettsäuren 2 %. Analytische Bestandteile: Rohfett 4,5 %, Feuchtigkeit 81 %"
    w = mod.texterkennung.auswerten(text)
    assert w["rohfett"] == 4.5 and w["feuchte"] == 81


def test_unplausible_werte_werden_verworfen(mod):
    w = mod.texterkennung.auswerten("Analytische Bestandteile: Protein 105 %, Energie 9000 kcal")
    assert "rohprotein" not in w and "kcal_100g" not in w


def test_leerer_text(mod):
    assert mod.texterkennung.auswerten("") == {}


def test_echtes_etikett_animonda_senior(mod):
    """Erkannter Text eines echten Etiketts (mehrsprachig, mit Lesefehlern), 2026-10-25."""
    pfad = os.path.join(os.path.dirname(__file__), "daten", "ocr_animonda_senior.txt")
    with open(pfad, encoding="utf-8") as datei:
        werte, zweifel = mod.texterkennung.analysieren(datei.read())
    assert werte == {"rohprotein": 10.0, "rohfaser": 0.4, "feuchte": 82.0, "proteine": "Geflügel, Schwein, Rind"}
    # „4 ‚ %“ (Nachkommastelle verloren) und „] 4 %“ (verlesene 1) nicht eintragen, sondern melden
    assert set(zweifel) == {"rohfett", "rohasche"}
    assert zweifel["rohfett"].endswith("4 ‚ %")


def test_lucke_mit_anderer_bezeichnung_wird_nicht_ueberbrueckt(mod):
    werte, _ = mod.texterkennung.analysieren("Analytische Bestandteile: Protein / Fettgehalt 5 %, Feuchtigkeit 80 %")
    assert "rohprotein" not in werte and werte["rohfett"] == 5


# Synthetischer Text im Format von Live Text; Fett 4,5 % und Asche 1,4 % sind angenommen, nicht abgelesen
LIVE_TEXT = """Analytische Bestandteile/Constituants analytiques/Analytische bestanddelen/Componenti analitici:
Protein/Protéine/Eiwit/Proteine 10 % • Fettgehalt/Teneur en matières grasses/Vetgehalte/Tenore in materia
grassa 4,5 % • Rohfaser/Cellulose brute/Ruwe celstof/Cellulosa grezza 0,4 % • Rohasche/Cendres brutes/Ruwe as/
Ceneri grezze 1,4 % • Feuchtigkeit/Humidité/Vocht/Umidità 82 %."""


def test_eingefuegter_live_text(mod):
    r = mod.app.test_client().post("/text_auswerten", headers=HEADERS, data={"text": LIVE_TEXT})
    assert r.status_code == 200
    assert r.json["werte"] == {"rohprotein": 10, "rohfett": 4.5, "rohfaser": 0.4, "rohasche": 1.4, "feuchte": 82}
    assert r.json["zweifel"] == {}
    assert mod.db().execute("SELECT COUNT(*) FROM produkt").fetchone()[0] == 0


def test_eingefuegter_text_leer(mod):
    r = mod.app.test_client().post("/text_auswerten", headers=HEADERS, data={"text": "  "})
    assert r.status_code == 400


def test_formular_hat_einfuegen(mod):
    html = mod.app.test_client().get("/produkt", headers=HEADERS).get_data(as_text=True)
    assert "Deklaration einfügen (Live Text" in html and "fetch('text_auswerten'" in html


def test_route_meldet_zweifel(mod):
    r = mod.app.test_client().post("/text_auswerten", headers=HEADERS,
                                   data={"text": "Analytische Bestandteile: Protein 10 %, Fettgehalt 4 , %"})
    assert r.json["werte"] == {"rohprotein": 10} and "rohfett" in r.json["zweifel"]


def test_formular_ohne_fotoerkennung(mod):
    html = mod.app.test_client().get("/produkt", headers=HEADERS).get_data(as_text=True)
    assert "Deklaration fotografieren" not in html and "fetch('ocr'" not in html
    assert "Deklaration einfügen (Live Text" in html
