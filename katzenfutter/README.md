# Katzenfutter

Futter- und Ernährungstracking für die Katze, als Panel in der Home-Assistant-Seitenleiste.
Alle Haushaltsmitglieder mit HA-Benutzer können es nutzen (auch ohne Admin-Rechte).

## Funktionen (Stand 0.22.0)

- **Heute:** Energie-Bilanz des Tages, verbleibende Menge, Wasser aus Futter, alle Hinweise
- **Verlauf:** Gewicht mit 7-Tage-Trend und Hinweisen, kcal je Tag, Tabelle; Gewicht eintragen
- **Katze:** Profil (Gewicht, Zielgewicht und BCS „offen“, Aktivitätsfaktor), Gewichtshistorie,
  Rechner für Tagesbedarf, Snack-Obergrenze, Wasser-Richtwert und Futtermenge in g und Packungen
- **Futter:** Futterdatenbank mit Deklaration, kcal laut Hersteller oder berechnet (Atwater),
  Vergleich auf Trockenmasse, EAN mit Prüfziffer, Bestand mit angebrochener Packung,
  Daten per EAN aus Open Pet Food Facts, Deklaration per Live Text einfügen (Werte werden nur vorbelegt)
- **Vorlieben:** Lieblingsfutter und „wird nicht gemocht“ je Sorte, Marke, Textur, Hauptprotein
- **Kosten:** je Tag, Monat und Sorte, Preisvergleich je 100 kcal
- **Füttern:** Sorte und Menge in wenigen Tipps, Bestand wird fortgeschrieben, Rückgängig bis 30 Minuten
- **Rest:** geschätzt mit einem Tipp oder gewogen, „verweigert“; geschätzte Werte sind gekennzeichnet
- **Snacks:** Stück oder Gramm, Obergrenze 10 % des Tagesbedarfs, Tageslimit der Kinder
- **Gesundheit:** Erbrechen, Haarballen, Durchfall, weicher Kot; Zuordnung zur Mahlzeit, Tierarzt-Hinweise
- **Mehrere Katzen:** anlegen im Tab Katze, Umschalter oben auf jeder Seite
- **Einstellungen:** Haushalt (Erwachsene, Kinder, HA-Benutzer), Snack-Limit, Schwellen für Hinweise
- **Rechte:** Kinder füttern, tragen Reste und Snacks ein, melden Gesundheit und sehen alles; Profil, Futter und
  Bestand, Katzen, Wiegungen, Mahlzeiten löschen und Einstellungen nur Erwachsene (ohne angelegte Personen: alle)
- **Rest-Erinnerung:** Mitteilung mit Aktionen nach dem Füttern, Antwort trägt den Rest ein
- **Warn-Mitteilungen:** Tierarzt-Hinweis, keine Futteraufnahme, Gewicht, Akzeptanz, Snack-Limit
- **Sensoren:** per MQTT-Discovery am Mosquitto-Broker (kcal, Futter, Gewicht, Bestand, Kosten, Hinweise)
- **Barcode:** Live-Kamera (HTTPS), Foto oder EAN-Eingabe; Erkennung im Browser (ZXing, mitgeliefert)

PetKit-Katzenklo: Sensoren im Profil der Katze wählen (Gewicht je Toilettengang, Toilettengänge). Trinkbrunnen folgt.

## Konfiguration

| Option | Bedeutung |
| --- | --- |
| `notify_services` | Empfänger der Mitteilungen ohne `notify.`, z. B. `mobile_app_mein_handy`; leer = alle Handys mit HA-App |
| `warn_mitteilungen` | Mitteilung bei Tierarzt-Hinweis, keiner Futteraufnahme, Gewicht, Akzeptanz, Snack-Limit |
| `online_produktdaten` | Produktdaten per EAN aus Open Pet Food Facts holen (nur die EAN wird übertragen) |
| `rest_erinnerung_minuten` | Minuten nach dem Füttern bis zur Erinnerung, 0 = aus (Vorgabe 30) |
| `mqtt_host`, `mqtt_port`, `mqtt_user`, `mqtt_password` | nur nötig, wenn der Broker nicht automatisch erkannt wird |

## Daten

SQLite unter `/data/katzenfutter.db`, Fotos unter `/data/fotos`, Bestandteil jedes HA-Backups.
Zusätzlich legt das Add-on täglich eine vollständige Kopie unter `addon_configs/<kennung>_katzenfutter/sicherung/` an
(per Samba oder SSH erreichbar) und behält die letzten 7. Einspielen: Kopie dort in `wiederherstellen.db`
umbenennen und das Add-on neu starten. Schemaänderungen laufen als
versionierte Migrationen beim Start; vorhandene Daten bleiben erhalten.

## Hinweise

- Live-Kamera (Barcode) braucht HTTPS, z. B. über Nabu Casa. Über `http://` im WLAN bleiben Foto und EAN-Eingabe.
- Das Panel antwortet nur über Ingress; ein direkter Aufruf über IP und Port liefert 403.
- Hinweise des Add-ons sind keine Diagnosen. Bei Auffälligkeiten Tierarzt fragen.

## Drittsoftware

`app/static/zxing/`: @zxing/library 0.23.0, Apache-2.0 (Lizenz und Herkunft im Ordner).
