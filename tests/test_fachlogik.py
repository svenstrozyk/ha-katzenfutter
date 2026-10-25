"""Tests für die Fachlogik (Referenzwerte von Hand gerechnet)."""
import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "katzenfutter", "app")))
import fachlogik as f  # noqa: E402

# Beispiel-Nassfutter: Rohprotein 11, Rohfett 6, Rohasche 2, Rohfaser 0,5, Feuchte 79
DEKLARATION = dict(rohprotein=11, rohfett=6, rohasche=2, rohfaser=0.5, feuchte=79)


def test_rer_und_mer():
    assert f.rer(4) == pytest.approx(197.99, abs=0.01)
    assert f.mer(4, 1.4) == pytest.approx(277.19, abs=0.01)


def test_rer_ohne_gewicht_wird_abgelehnt():
    with pytest.raises(ValueError):
        f.rer(None)
    with pytest.raises(ValueError):
        f.rer(0)


def test_reduktion_nur_auf_zielgewicht():
    assert f.tagesbedarf_kcal(5, 0.8, zielgewicht_kg=4) == pytest.approx(f.rer(4) * 0.8)
    with pytest.raises(ValueError, match="Zielgewicht"):
        f.tagesbedarf_kcal(5, 0.8)
    assert f.tagesbedarf_kcal(4, 1.4) == pytest.approx(f.mer(4, 1.4))


def test_kcal_nach_atwater():
    assert f.nfe(**DEKLARATION) == pytest.approx(1.5)
    # 3,5 × 11 + 8,5 × 6 + 3,5 × 1,5 = 94,75
    assert f.kcal_100g_berechnet(**DEKLARATION) == pytest.approx(94.75)


def test_nfe_rundungsdifferenz_wird_null():
    assert f.nfe(rohprotein=12, rohfett=6, rohasche=2.5, rohfaser=0.3, feuchte=79.5) == 0.0


def test_nfe_ueber_100_prozent_wird_abgelehnt():
    with pytest.raises(ValueError, match="100 %"):
        f.nfe(rohprotein=15, rohfett=8, rohasche=3, rohfaser=1, feuchte=80)


def test_trockenmasse():
    assert f.trockenmasse(11, 79) == pytest.approx(52.38, abs=0.01)
    with pytest.raises(ValueError):
        f.trockenmasse(11, 100)


def test_tagesmenge_mit_snacks():
    # (277,19 − 20) / 94,75 × 100 = 271,44 g
    assert f.tagesmenge_g(277.19, 20, 94.75) == pytest.approx(271.44, abs=0.01)
    assert f.tagesmenge_g(277.19, 0, 94.75, anteil=0.5) == pytest.approx(146.28, abs=0.01)


def test_tagesmenge_nie_negativ():
    assert f.tagesmenge_g(100, 150, 90) == 0.0


def test_packungsplan_mit_angebrochener_packung():
    plan = f.packungsplan(100, 85, angebrochen_g=30)
    assert plan == {"aus_angebrochen_g": 30, "neue_packungen": 1, "rest_angebrochen_g": 15}


def test_packungsplan_angebrochene_reicht():
    plan = f.packungsplan(40, 85, angebrochen_g=50)
    assert plan == {"aus_angebrochen_g": 40, "neue_packungen": 0, "rest_angebrochen_g": 10}


def test_packungsplan_ohne_angebrochene():
    plan = f.packungsplan(170, 85)
    assert plan == {"aus_angebrochen_g": 0, "neue_packungen": 2, "rest_angebrochen_g": 0}


@pytest.mark.parametrize("stufe, rest", [
    ("nichts", 0), ("wenig", 8.5), ("haelfte", 42.5), ("viel", 63.75), ("unberuehrt", 85),
])
def test_rest_stufen(stufe, rest):
    assert f.rest_aus_stufe(85, stufe) == pytest.approx(rest)


def test_unbekannte_stufe():
    with pytest.raises(ValueError):
        f.rest_aus_stufe(85, "ein_bisschen")


def test_gefressen():
    assert f.gefressen_g(85, 8.5) == pytest.approx(76.5)
    with pytest.raises(ValueError):
        f.gefressen_g(85, 90)


def test_kcal_aus_menge():
    assert f.kcal_aus_menge(76.5, 94.75) == pytest.approx(72.48, abs=0.01)


def test_snack_warnung_ab_10_prozent():
    assert f.snack_warnung(27, 280) is False
    assert f.snack_warnung(28, 280) is True


def test_wasserbilanz_ohne_trinkbrunnen():
    futterwasser = f.futterwasser_ml(250, 79)
    assert futterwasser == pytest.approx(197.5)
    bilanz = f.wasserbilanz(4, futterwasser)
    assert bilanz["richtwert_min_ml"] == 160 and bilanz["richtwert_max_ml"] == 240
    assert bilanz["getrunken_bekannt"] is False
    assert bilanz["unter_richtwert"] is False


def test_wasserbilanz_mit_getrunkenem():
    bilanz = f.wasserbilanz(4, 100, getrunken_ml=30)
    assert bilanz["gesamt_ml"] == 130
    assert bilanz["unter_richtwert"] is True
