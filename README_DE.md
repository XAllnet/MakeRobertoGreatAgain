# Roberto Zones 0.3.0 – Diagnose und Testfahrt

Die Integration läuft direkt in Home Assistant OS, ohne zusätzlichen Container, ohne Root und ohne Valetudo.

**Noch keine echten No-Go-Zonen.** Die Integration bewertet Kartenorientierungen und erlaubt nur einzelne, ausdrücklich bestätigte Fernsteuerungsschritte. Es werden niemals automatisch Fahr- oder Reinigungsbefehle gesendet.

## Installation

1. Home Assistant 2026.11 Marketplace öffnen.
2. Repository `https://github.com/XAllnet/MakeRobertoGreatAgain` als benutzerdefinierte **Integration** hinzufügen.
3. Roberto Zones installieren und Home Assistant Core neu starten.
4. Einstellungen → Geräte & Dienste → Integration hinzufügen → Roberto Zones (Diagnose).
5. Live-Kartenentität (beispielsweise `image.wohnzimmer_roberto_blanko_live_map`) und lokale Xiaomi-Miio-`vacuum`-Entität eintragen.

## Testfahrt ohne normalen Saugmodus (neu in 0.3.0)

1. Roberto auf eine **freie Bodenfläche** stellen; direkt daneben bleiben. Keine Kabel, Katzenutensilien oder Hindernisse in Reichweite.
2. Einstellungen → Werkzeuge → Aktionen → `roberto_zones.test_move_step`.
3. Richtung wählen (Vorwärts, Rückwärts, Links, Rechts).
4. Bei jeder Bewegung **Aufsicht und freie Fläche** bestätigen.
5. Aktion ausführen. Es wird nur ein kurzer Fernsteuerungsschritt ausgeführt; die Miio-Aktion hält am Ende automatisch an. Drei Sekunden Abstand zwischen Schritten.
6. Bei Problemen `roberto_zones.stop_test_drive` oder die physische Stopptaste verwenden.

Die Funktion akzeptiert ausschließlich die konfigurierte `xiaomi_miio`-Staubsaugerentität, und nur bei `idle` oder `docked`. Dies ist kein freier Kartenpunkt-Navigationsmodus und **keine No-Go-Zonen-Absicherung**. Auch bei ausgeschalteter Turbine können Räder/Bürsten Kabel erfassen. Remote-Control-Befehle brauchen ggf. einen Roboter außerhalb der Ladestation.

## Historisches Kartenbild direkt hochladen (neu in 0.2.0)

1. Einstellungen → Werkzeuge → Aktionen öffnen.
2. `roberto_zones.import_reference` auswählen.
3. Im Feld **Historische Wohnungskarte** einen vollständigen Screenshot aus der Xiaomi-Reinigungshistorie als JPG oder PNG hochladen (kein ZIP).
4. **Aktion ausführen**. Die App-Oberfläche und der dunkelblaue Hintergrund werden bei typischen Xiaomi-Screenshots automatisch entfernt.
5. Unter **Kartenstatus** prüfen, ob eine Diagnose ausgeführt wurde (`orientierung_unklar` ist bei einer unvollständigen Live-Karte normal).

Die Datei verbleibt auf Home Assistant; der Bild-Upload erzeugt außerdem einen Eintrag in der integrierten Home-Assistant-Bildverwaltung. Nur die lokale Referenzdatei unter `/config/roberto_zones/reference.png` wird von Roberto Zones eingelesen. Achtung: Ein historischer Screenshot hat **keine verifizierten Roboterkoordinaten**.

## Referenzkarte

Die Aktion `roberto_zones.capture_reference` speichert die **aktuelle** Karte unter `/config/roberto_zones/reference.png` direkt in Home Assistant. Sie überschreibt eine bestehende Referenz und darf nur auf einer vollständigen Karte ausgeführt werden. Das Paket enthält keine Wohnungskarte.

Die Aktion `roberto_zones.analyze_now` startet eine einzelne Diagnose. Automatische Analysen laufen ereignisgesteuert, ohne eigene Dauer-Polling-Schleife. Die Bildverarbeitung erfolgt außerhalb des Event-Loops.

## Sicherheitsgrenzen

Die Bildausrichtung ist **keine verifizierte Navigationskoordinate**. Da der Xiaomi V1 nach einem normalen Reinigungsstart neue Karten aufbaut und eigenständig durch Räume navigiert, lassen sich Kabelbereiche durch diese Integration nicht zuverlässig sperren. Unbeaufsichtigte Reinigung erst nach physischer Absicherung.

Die sieben beschrifteten Sperrzonen aus dem Projekt bleiben private Planungsdaten und werden nicht veröffentlicht.
