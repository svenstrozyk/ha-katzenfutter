# Anleitung

Einrichtung, Alltag und Pflege des Katzenfutter-Add-ons. Stand: Version 0.26.0.

---

## 1. Installation in Home Assistant

1. **Einstellungen → Add-ons → Add-on-Store**, Menü oben rechts (drei Punkte) → **Repositories**
2. `https://github.com/svenstrozyk/ha-katzenfutter` eintragen → **Hinzufügen** → Schließen
3. Seite neu laden, unten im Abschnitt „Katzenfutter Add-ons“ **Katzenfutter** öffnen → **Installieren**
   (das vorgebaute Image wird heruntergeladen, kein Build auf dem Gerät)
4. Reiter **Info**: **In Seitenleiste anzeigen** einschalten → **Starten**
5. Reiter **Protokoll**: Zeilen `Booting worker`, `MQTT verbunden` und `Warte auf Antworten aus Mitteilungen`
   zeigen, dass alles läuft

Voraussetzungen: Mosquitto-Broker (Add-on) für die Sensoren, HA-App auf den Handys für Mitteilungen.

## 2. Konfiguration (Reiter „Konfiguration“)

| Option | Vorgabe | Bedeutung |
| --- | --- | --- |
| `notify_services` | leer | Empfänger der Mitteilungen ohne `notify.`, z. B. `mobile_app_mein_handy`; leer = alle Handys mit HA-App |
| `rest_erinnerung_minuten` | 30 | Minuten nach dem Füttern bis zur Erinnerung, 0 = aus |
| `warn_mitteilungen` | an | Mitteilung bei Tierarzt-Hinweis, keiner Futteraufnahme, Gewicht, Akzeptanz, Snack-Limit |
| `online_produktdaten` | an | Produktdaten per EAN aus Open Pet Food Facts holen (nur die EAN wird übertragen) |
| `mqtt_host` … `mqtt_password` | leer | nur nötig, wenn der Broker nicht automatisch erkannt wird |

## 3. Erste Schritte im Panel

1. **Katze → Profil:** Name und aktuelles Gewicht eintragen (angelegt ist zunächst „Katze“) (Zielgewicht und BCS bleiben „offen“, bis der Tierarzt sie festlegt)
2. **Katze → Einstellungen:** Haushalt anlegen (Erwachsene, Kinder, ggf. HA-Benutzername), Snack-Limit der Kinder.
   Sobald Personen angelegt sind, ändern nur Erwachsene Profil, Futter, Bestand, Katzen, Wiegungen und Einstellungen
   und löschen Mahlzeiten. Kinder füttern, tragen Reste und Snacks ein, melden Gesundheit und sehen alles.
3. **Futter → Barcode scannen:** jede Sorte einmal scannen. Kennt Open Pet Food Facts die EAN, sind die Felder
   vorbelegt. Sonst die Deklaration per **Text einfügen (Live Text)** übernehmen: in Kamera oder Fotos den Block
   „Analytische Bestandteile“ markieren, kopieren, einfügen. **Preis je Packung** eintragen (für die Kosten).
4. Weitere Sorten derselben Linie: **Werte übernehmen von** einer vorhandenen Sorte.
5. Weitere Katze: **Katze → Weitere Katze**; umgeschaltet wird oben auf jeder Seite.
6. PetKit-Katzenklo (sobald eingerichtet): **Katze → Profil → PetKit**, Sensoren für letzten Toilettengang
   und Gewicht je Toilettengang auswählen (Vorschläge erscheinen beim Antippen des Felds).

## 4. Alltag

| Was | Wo | Tipps |
| --- | --- | --- |
| Füttern | Tab **Füttern** | Sorte (angebrochene steht oben), Menge per Schnellwahl, **Gefüttert**; Rückgängig bis 30 min |
| Rest | Füttern → **Rest eintragen** oder Mitteilung | Nichts / Wenig / Hälfte / Viel / Unberührt; „Wiegen …“ für gewogenen Rest oder „verweigert“ |
| Snack | Füttern → **Snack geben** | „Gegeben von“ wählen, wenn ein Kind über euer Handy gibt |
| Erbrechen, Durchfall … | Füttern → **… melden** | zwei Tipps; Blut, Apathie, Foto optional |
| Gewicht | Tab **Verlauf** | etwa wöchentlich, gleiche Tageszeit |
| Überblick | Tab **Heute** | Energie-Bilanz, verbleibende Menge, alle Hinweise |
| Kosten | Futter → **Kosten** | Preis je Packung bei jeder Sorte pflegen |
| Einkauf angekommen | Futter → **Bestand & Einkauf** | je Sorte +/− tippen, **Lieferung speichern** |
| Nachkaufen | Futter → **Bestand & Einkauf** oder Hinweis auf **Heute** | **Auf Einkaufsliste**; Liste in den Einstellungen wählen, optional automatisch |

Die Rest-Erinnerung kommt 30 Minuten nach einer Mahlzeit ohne Rest auf alle Empfänger; lang drücken zeigt die Knöpfe.

## 5. Sensoren in Home Assistant

Gerät **Katzenfutter <Name>** (je Katze eins), für eine Katze „Luna“ u. a. `sensor.luna_kcal_heute`,
`sensor.luna_kcal_verbleibend`, `sensor.luna_gewicht`, `sensor.luna_futterkosten_30_tage`,
`binary_sensor.luna_tierarzt_hinweis`, `binary_sensor.luna_keine_futteraufnahme`. Geeignet für eigene Automationen und Dashboards.

## 6. Updates

**Einstellungen → Add-ons → Katzenfutter → Aktualisieren.** Daten unter `/data` bleiben erhalten, Schemaänderungen
laufen automatisch. Erscheint ein angekündigtes Update nicht: Add-on-Store → Menü → **Nach Updates suchen**.

## 7. Daten und Backup

SQLite-Datenbank `/data/katzenfutter.db` und Fotos unter `/data/fotos` sind Teil jedes HA-Backups.
Dazu entsteht täglich eine vollständige Kopie der Datenbank (die letzten 7 Tage) im Konfigurationsordner des
Add-ons, erreichbar per Samba oder SSH unter `addon_configs/<kennung>_katzenfutter/sicherung/`.
Wiederherstellen: am einfachsten über ein HA-Backup (Teil-Backup nur dieses Add-ons). Eine einzelne Tageskopie
lässt sich als `katzenfutter.db` einspielen, indem man sie in diesem Ordner in `wiederherstellen.db` umbenennt und
das Add-on neu startet; die bisherige Datenbank wird vorher als `vor-wiederherstellung-<Zeit>.db` beiseitegelegt.
Nichts verlässt das Haus außer der EAN-Abfrage bei Open Pet Food Facts (abschaltbar).

---

## Fehlerbehebung

| Symptom | Ursache | Lösung |
| --- | --- | --- |
| Panel zeigt 403 | Aufruf nicht über Ingress | nur über die Seitenleiste öffnen, nicht über IP und Port |
| Familienmitglied sieht das Panel nicht | Seitenleiste aus oder Benutzer ohne Zugriff | „In Seitenleiste anzeigen“ prüfen; in der App ab- und wieder anmelden |
| Live-Kamera fehlt beim Barcode | Zugriff über `http://` im WLAN | Foto oder EAN-Eingabe nutzen; unterwegs (Nabu Casa, HTTPS) geht die Kamera |
| Update schlägt fehl („image not found“) | Image wird auf GitHub noch gebaut | einige Minuten warten, erneut aktualisieren |
| Keine Rest-Erinnerung | Empfänger falsch oder Option 0 | `notify_services` prüfen; Protokoll nach „Rest-Erinnerung“ durchsuchen |
| Sensoren „nicht verfügbar“ | Add-on gestoppt oder Broker weg | Add-on und Mosquitto prüfen; Protokoll „MQTT verbunden“ |
| Kosten leer | Preis oder Packungsgröße fehlt | in der Sorte nachtragen; die Kostenseite nennt die betroffenen Sorten |

## Entwicklung

Tests: `pytest` im Repo-Wurzelverzeichnis (laufen zusätzlich bei jedem Push in GitHub Actions).
Lokal starten: `DEV_MODE=1 DATA_DIR=/tmp/katzenfutter python3 katzenfutter/app/app.py` (Port 8099).
