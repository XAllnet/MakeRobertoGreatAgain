# MakeRobertoGreatAgain — Roberto Zones 0.6.2

Home Assistant custom integration for Xiaomi Mi Robot Vacuum V1, with read-only map comparison and manually supervised, explicitly requested testing actions. **No automatic navigation and no enforced no-go zones.**

### Geometry-only map comparison (v0.6.2)

Previously, map alignment considered all contrasting pixels in rendered Map Extractor PNG images, including robot tracks and position icons. This made similarity and consensus dependent on the robot's route.

Version 0.6.2 accesses **existing, already-fetched parsed map data** from the Xiaomi Cloud Map Extractor v3.0.0-alpha-24 coordinator cache, specifically \`MapData.image.data\`. This raster contains the underlying wall/floor pixels before the map renderer applies the path, vacuum marker and other transient overlays. Geometry is assigned its own map pixel calibration, then compared for rotation/translation.

The previous reference is not silently reused: save a **complete current map** again with \`roberto_zones.capture_reference\`. This also resets any reference-landmark checkpoints tied to the old reference. The integration saves a private \`reference_geometry.png\` with SHA256-bound \`reference_geometry.json\` locally on Home Assistant. The original \`reference.png\` is retained.

The Map Extractor v3 cache is a *private, version-dependent API*. If unavailable or its map PNG does not match the image entity data, the integration fails closed with \`native_geometrie_nicht_verfuegbar\`, without a second cloud request or fallback to decorated-image matching.

The card \`image.wohnzimmer_roberto_blanko_live_map\` and user's Xiaomi Vacuum Map Card remain unchanged. The new diagnostic image presents geometry-only floor plans, with the old orientation-consensus gates. A visually aligned map is **not physical coordinate verification**. Manual checkpoint verification from 0.6.0 is still required.

The map extractor's 10-second cloud update delay remains. No permanent polling or new containers.

See [README_DE.md](README_DE.md) for full steps.
