# Roberto Zones 0.1.1 – Diagnose

Die Integration läuft direkt in Home Assistant OS, ohne zusätzlichen Container, ohne Root und ohne Valetudo.

**Noch keine echten No-Go-Zonen.** Version 0.1.1 wertet nur die Live-Karte aus, schätzt mögliche Bildorientierungen und meldet Diagnosewerte. Es werden keine Befehle an den Roboter gesendet.

## Installation

1. Home Assistant 2026.11 Marketplace öffnen.
2. Repository `https://github.com/XAllnet/MakeRobertoGreatAgain` als benutzerdefinierte **Integration** hinzufügen.
3. Roberto Zones installieren und Home Assistant Core neu starten.
4. Einstellungen → Geräte & Dienste → Integration hinzufügen → Roberto Zones (Diagnose).
5. Live-Kartenentität (beispielsweise `image.wohnzimmer_roberto_blanko_live_map`) und lokale Xiaomi-Miio-`vacuum`-Entität eintragen.

## Referenzkarte

Die Aktion `roberto_zones.capture_reference` speichert die **aktuelle** Karte unter `/config/roberto_zones/reference.png` direkt in Home Assistant. Sie überschreibt eine bestehende Referenz und darf nur auf einer vollständigen Karte ausgeführt werden. Das Paket enthält keine Wohnungskarte.

Die Aktion `roberto_zones.analyze_now` startet eine einzelne Diagnose. Automatische Analysen laufen ereignisgesteuert, ohne eigene Dauer-Polling-Schleife. Die Bildverarbeitung erfolgt außerhalb des Event-Loops.

## Sicherheitsgrenzen

Die Bildausrichtung ist **keine verifizierte Navigationskoordinate**. Da der Xiaomi V1 nach einem normalen Reinigungsstart neue Karten aufbaut und eigenständig durch Räume navigiert, lassen sich Kabelbereiche durch diese Integration nicht zuverlässig sperren. Unbeaufsichtigte Reinigung erst nach physischer Absicherung.

Die sieben beschrifteten Sperrzonen aus dem Projekt bleiben private Planungsdaten und werden nicht veröffentlicht.
