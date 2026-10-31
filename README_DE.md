# Roberto Zones 0.5.1 – Kartenüberlagerung und Positionsdiagnose

Die Integration nutzt die vorhandene Home-Assistant-Installation mit dem Xiaomi Cloud Map Extractor **3.0 alpha** und dem lokalen Xiaomi Miio. Kein zusätzlicher Container und keine Firmwareänderung.

**Keine automatische Punktnavigation und keine verlässlichen No-Go-Zonen.** Die bisherige beaufsichtigte Schrittsteuerung bleibt erhalten. Die in diesem Update erzeugte Überlagerung ist eine Diagnose, **keine Freigabe für Bewegungen**.

## 1. Aktualisieren

Marketplace → Roberto Zones → Version 0.5.1 installieren → Home Assistant Core neu starten. Die Integration muss nicht gelöscht und neu angelegt werden.

## 2. Positionssensoren des Map Extractors einschalten

Der Xiaomi Cloud Map Extractor 3.0-alpha-24 erzeugt separate, normalerweise **deaktivierte** Diagnose-Sensoren:

- **Vacuum position** (\`vacuum_position\`): aktuelle Position in Xiaomi-Koordinaten, falls die Karte diese Daten enthält
- **Charger position** (\`charger_position\`): Ladestation, falls vorhanden

Einstellungen → Geräte & Dienste → Xiaomi Cloud Map Extractor → Entitäten; deaktivierte Entitäten einblenden, **Vacuum position** und **Charger position** aktivieren. Namen können je nach Übersetzung abweichen.

Roberto Zones versucht automatisch, beide Sensoren der **gleichen Map-Extractor-Integration wie die Live-Bildentität** zu erkennen. Wenn das nicht klappt: Einstellungen → Geräte & Dienste → Roberto Zones → **Konfigurieren** → Entitätsnamen in **position_entity** und **charger_entity** eintragen (z. B. \`sensor.wohnzimmer_roberto_blanko_vacuum_position\`). Den tatsächlich angezeigten Namen verwenden, nicht raten.

Ein Wert \`unknown\`, \`unavailable\` oder \`null\` bedeutet **keine Positionsmessung**. Das kann vor oder kurz nach Kartierungsbeginn vorkommen.

## 3. Neue Bildentität: Referenz und Live-Karte

Unter Roberto Zones gibt es die neue Bildentität **Referenz und Live-Karte**.

**Fall A – Historischer Screenshot importiert:** Die Karte bleibt als Referenz sichtbar, aber wird **neben** der Live-Karte angezeigt. Historische Screenshots haben keine nachprüfbare Umrechnung zwischen Bildpunkten und Xiaomi-Koordinaten. Eine scheinbar ausgerichtete Überlagerung wäre irreführend. Status \`referenz_ohne_koordinaten\`.

**Fall B – Einmal eine vollständige Live-Karte mit Kalibrierung sichern:** Wenn Roberto einen vollständigen Grundriss erfasst hat, unter **Einstellungen → Werkzeuge → Aktionen** \`roberto_zones.capture_reference\` ausführen. Das speichert lokal:
- \`/config/roberto_zones/reference.png\` – Originalbild der Live-Karte
- \`/config/roberto_zones/reference_calibration.json\` – zu **genau diesem Bild** gehörige Kalibrierung (mit Hash-Prüfung)

Die Referenz darf nicht während einer unvollständigen Reinigung erstellt werden und überschreibt eine vorherige Referenz! Bei späteren Reinigungsläufen wird das aktuelle Bild über die ursprünglich gespeicherte Karte projiziert, **wenn beide Xiaomi-Kalibrierungen plausibel sind**. Grau = historische Referenzfläche; türkis = aktuell erkannte Fläche; gelb = gemeldete Roboterposition; grün = gemeldete Ladestation.

Eine neue importierte Screenshot-Referenz **entfernt die alte Kalibrierung**, damit niemals falsche Pixelkoordinaten mit einer anderen Karte verknüpft werden.

## 4. Woher kennen wir Robertos Position?

Nicht aus dem Bild geraten: Der Map Extractor liefert die aus Xiaomi-Kartendaten gewonnene \`vacuum_position\` (X und Y) über seinen separaten Diagnosesensor. Roberto Zones zeigt diese in **Roboterposition (Xiaomi-Koordinaten)** an, sofern vorhanden. \`calibration_points\` übersetzen Bildpixel in Xiaomi-Koordinaten. Der Dockpunkt liegt näherungsweise bei **(25500, 25500)**.

Das ist jedoch **noch keine unabhängige physische Positionsbestätigung**: Kalibrierung und Position stammen aus derselben Quelle. Um die Zuordnung wirklich zu prüfen:

1. Position am Dock ablesen und dokumentieren.
2. Roberto **unter Aufsicht** über eine bereits funktionierende Navigationskarte zu einem eindeutig erkennbaren freien Ziel schicken (vorerst außerhalb von Roberto Zones).
3. Beim Ankommen reale Position, Xiaomi-X/Y und Bildmarkierung vergleichen. Einen zweiten Test in einer **anderen Richtung** ausführen.
4. Stimmt beides mit plausibler Abweichung überein, können wir in der nächsten Entwicklungsstufe gezielt kalibrierte Ziele freischalten.

**Bei \`vacuum_position=null\`, fehlender Kalibrierung, wechselndem Dock, unklaren Teilkarten oder falschem Bildabgleich sind Koordinaten nicht freigegeben.**

## 5. Diagnose-Status

- \`referenz_fehlt\`: Noch keine Referenz
- \`referenz_ohne_koordinaten\`: Importierter Screenshot ohne Kalibrierung; sichere Seiten-an-Seiten-Ansicht
- \`live_kalibrierung_fehlt\`: Aktuelle Map-Extractor-Kalibrierung unvollständig
- \`ausrichtung_nicht_bestaetigt\`: Referenz und Live-Karte passen geometrisch noch nicht ausreichend
- \`position_nicht_verfuegbar\`: Keine aktuelle Xiaomi-Roboterposition geliefert
- \`ueberlagerung_plausibel_pruefung_offen\`: Bildvergleich plausibel, aber Position **noch nicht unabhängig bestätigt**

Die Bildberechnung läuft nur auf Bild- oder Positionsänderungen mit Debounce/Throttling und außerhalb des Home-Assistant-Event-Loops. Kein zusätzlicher Polling-Prozess.

## 6. Aktualisierungslatenz (0.5.1)

Roberto Zones übernimmt neue X-/Y-Werte unmittelbar nach einem Event des Map-Extractor-Positionssensors; die langsame Kartenbildanalyse blockiert die Positionsanzeige nicht mehr. Die Kartenüberlagerung behält die mindestens 15 Sekunden Abstand plus Debounce bei.

Die Position zeigt die Attribute `source_entity_last_updated` (Home-Assistant-Zeitstempel des zuletzt geänderten Quellenzustands) und `received_by_roberto_zones_at`. Das ist **keine garantierte Messzeit am Roboter**; die Xiaomi Cloud kann die Messung bereits früher erstellt haben. Die auf der Karte eingezeichnete Position stammt aus dem letzten Bildvergleich und kann deshalb älter als der Positionssensor sein.

**Nicht für laufende Lenkregelung, Kollisionsvermeidung oder laufende No-Go-Zonen-Korrektur benutzen.** Um einen Zielpunkt zu prüfen, Roberto anhalten lassen und anschließend auf ein stabiles Positionsupdate warten.

## 7. Achtung

Die Referenz ist **nur für Home Assistant**, nicht Robertos interne Karte. Der Xiaomi V1 beginnt normale Reinigungsläufe weiterhin ohne persistenten Grundriss. Er kann beliebige Wege zu Zielen wählen. Kabel/No-Go-Zonen lassen sich mit diesem Add-on bisher nicht zuverlässig schützen. Beim Bewegen können **Haupt- und Seitenbürsten mitlaufen**.

Das Update ist experimentell und noch nicht im echten Home Assistant des Nutzers getestet.
