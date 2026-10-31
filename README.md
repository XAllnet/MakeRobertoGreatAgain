# MakeRobertoGreatAgain – Roberto Zones

**Version 0.3.0** · Home Assistant custom integration · event-driven map diagnostics and supervised manual step tests

This project explores resource-efficient map alignment for the Xiaomi Mi Robot Vacuum V1 (`rockrobo.vacuum.v1`) in Home Assistant.

**Safety:** This version sends no automatic vacuum commands. The only possible motion is an explicit, short remote-control step with per-step confirmation and idle-state checks. It does not enforce No-Go zones. Map orientation is only a candidate, not a validated navigation coordinate transform. Do not use its output to authorize unattended cleaning.

## Install via Home Assistant Marketplace (2026.11 beta or later)

1. Open **Settings → Marketplace** in Home Assistant.
2. Use **Add custom repository / Add by link** and provide: https://github.com/XAllnet/MakeRobertoGreatAgain
3. Choose **Integration** and install **Roberto Zones**.
4. Restart Home Assistant Core.
5. Open **Settings → Devices & services → Add integration → Roberto Zones (Diagnose)**.
6. Set the live image entity (for example `image.wohnzimmer_roberto_blanko_live_map`) and your **local Xiaomi Miio** vacuum entity.

Until a reference is available the status is `referenz_fehlt`.
**New in 0.2.0: import a historical map screenshot through the web UI.** Open **Settings → Tools → Actions**, select `roberto_zones.import_reference`, and upload a PNG/JPG via the image field. The image is held by Home Assistant's image-upload store and normalized into a private PNG reference at `/config/roberto_zones/reference.png`. It overwrites the old reference. A screenshot is not an original Xiaomi navigation map and does not provide trustworthy navigation coordinates.

Alternatively, when a **complete** current map is available, run action `roberto_zones.capture_reference` to store a private reference at `/config/roberto_zones/reference.png`. The action replaces an existing reference. To analyze immediately, run `roberto_zones.analyze_now`.

The image is processed only on relevant map state changes while cleaning, with throttling and debounce; the integration has no polling timer. Map analysis runs in Home Assistant's executor.

## Supervised steering tests (0.3.0)

In **Settings → Tools → Actions**, choose `roberto_zones.test_move_step`. Select a direction and explicitly confirm supervision and a fully clear floor. Each action triggers **one** small movement using `xiaomi_miio.vacuum_remote_control_move_step`; the Miio service enters remote-control mode, performs the step and stops. No fan speed or cleaning actions are issued. The robot must have the **local Xiaomi Miio** entity (domain `xiaomi_miio`) configured and be `idle` or `docked`. Test on a completely clear open floor under direct supervision.

`roberto_zones.stop_test_drive` attempts `vacuum.stop` plus remote-control stop. If connection is lost, press the robot's physical stop button.

**No map target navigation in this version.** A current screenshot cannot yet be trusted for navigation. The 7 no-go reference zones are not enforced and cables remain dangerous.

## Updates

For this early version the Marketplace can install directly from the repository's default branch, even without a GitHub release. Later tagged releases can provide versioned update notifications. Home Assistant Core may need a restart after updating.

## Privacy

No apartment screenshots, cleaning history, coordinate lists, tokens or cloud credentials are committed. The private reference is created on the Home Assistant machine and remains outside the installed integration folder.

## Limitations

This is an experimental proof of concept not yet validated on the user's Home Assistant VM, not yet validated on the user's Home Assistant VM. The original Xiaomi V1 resets its map during new whole-house cleaning sessions. Image rotation alone cannot verify the robot's navigation coordinate system. External software cannot guarantee the robot will avoid cables; dangerous areas require physical protection.

See [German notes](README_DE.md).

Licensed under the repository's GPL-3.0 license.
