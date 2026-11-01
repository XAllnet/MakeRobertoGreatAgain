# Roberto Zones 0.6.3 – Fahrweg aus der echten Roborock-Rohkarte ausschließen

**Wichtige Fehlerkorrektur:** In 0.6.2 wurde angenommen, dass \`MapData.image.data\` eine unveränderte Kartenebene sei. Das stimmt nicht. Der Xiaomi Cloud Map Extractor zeichnet bereits beim Parsen die Route, den Roboter, die Ladestation und weitere Symbole in diese Bilddaten. Deshalb waren sie in der vermeintlich fahrspurfreien Referenz weiterhin sichtbar.

Ab 0.6.3 werden **nicht** die bemalten \`image.data\`-Pixel zur Kartenregistrierung verwendet. Roberto Zones liest stattdessen den ursprünglichen **Roborock IMAGE-Block (Typ 2)** aus der bereits in Home Assistant vom Map Extractor gespeicherten komprimierten Rohkarte \`map_data_raw\`. Der Fahrweg liegt in einem **anderen Block (Typ 3)** und wird nicht verarbeitet.

Die Analyse behält ausschließlich belegte Wand- und Hinderniszellen. Boden-, Scan- und Zimmerflächen bleiben ebenfalls außen vor. So ist der Karten-Fingerprint unabhängig davon, welche Strecke der Roboter zurückgelegt hat. Auf der Diagnosekarte werden daher nur noch Wandkonturen und keine Fahrspur oder Robotermarkierung angezeigt.

## Einmalige Einrichtung

1. Roberto Zones **v0.6.3** über Home Assistant Marketplace → Erneut herunterladen installieren und Home Assistant Core neu starten.
2. Roberto zuerst eine **vollständige Karte** erstellen lassen.
3. Die Aktion \`roberto_zones.capture_reference\` aufrufen. Sie speichert die unveränderte gerenderte Karte als \`reference.png\`, zusätzlich aber die neue Rohdaten-Wandmaske \`reference_geometry.png\` und ihre Kalibrierung in \`reference_geometry.json\` (Schema 3).
4. **Alte Kontrollpunkte werden beim Speichern der Referenz zurückgesetzt**. Die alten Referenzdateien werden überschrieben. Bei Bedarf vorher eine Home-Assistant-Sicherung erstellen.
5. Erst **danach** mit einer neuen Kartierung beginnen. Die Referenz während dieses Durchlaufs nicht erneut überschreiben.
6. Prüfen, dass im Sensor **Kartenstatus** folgende Attribute erscheinen:

\`\`\`yaml
geometry_source: cached_roborock_raw_image_block
geometry_only: true
tracks_included: false
robot_marker_included: false
scan_floor_included: false
\`\`\`

Für die Drehung sind weiterhin drei unterschiedliche, konsistente Änderungen der **Wandgeometrie** erforderlich. Die übrigen Diagnosewerte wie \`rotation_score\`, \`rotation_score_gap\` und \`temporal_visual_match\` bleiben vorhanden.

Wenn die Rohdaten unvollständig, die Kartenausrichtung noch unklar oder die Wandmenge zu gering ist, wird die Ausrichtung nicht bestätigt. Alte 0.6.2-Referenzen sind bewusst nicht kompatibel; die Referenz muss neu aufgenommen werden.

## Grenzen

- Der Rohdaten-Adapter unterstützt ausdrücklich das **Roborock-Gzip-IMAGE-Format**, wie es dein \`rockrobo.vacuum.v1\` verwendet. Für andere Modelle wird nicht auf ungeprüfte Pixelerkennung zurückgefallen.
- Das Lesen erfolgt aus dem vorhandenen Map-Extractor-Cache. **Keine zweite Cloud-Abfrage**, kein Container, kein permanenter Ticker.
- Die Drittanbieter-API ist intern und nicht offiziell stabil. Auf nicht unterstützten Versionen wird mit \`native_geometrie_nicht_verfuegbar\` gesperrt.
- Auch Wandzellen können sich beim Fortschreiten einer SLAM-Kartierung verändern. Die Erkennung benötigt keine 100-prozentige Pixelübereinstimmung.
- Die visuelle Stabilität ist **keine unabhängige Koordinatenverifikation**. Automatische Zielpunktfahrten und Software-No-Go-Zonen bleiben gesperrt.

Die bestehende **Xiaomi Vacuum Map Card** für Roberto Blanko bleibt unverändert. Deine Mehrpunkt-Steuerung über das separate Home-Assistant-Skript wird durch 0.6.3 nicht verändert.

Der neue Rohdatenfilter wurde mit synthetischen Roborock-Karten getestet. Ein Praxistest auf deiner Home-Assistant-VM steht weiterhin aus.
