# MakeRobertoGreatAgain — Roberto Zones v0.6.3

Experimental Home Assistant integration for the Xiaomi Mi Robot Vacuum V1. Its diagnostic map matching is **read-only**, and it does not enforce no-go zones or authorize automatic navigation.

## Correct raw map geometry, no path contamination

**Regression corrected:** 0.6.2 mistakenly treated \`MapData.image.data\` as a clean geometry source. The Roborock parser calls \`ImageGenerator.draw_map()\` before publishing that object, so route, vacuum marker, charger and overlays were already present.

0.6.3 uses the **original Roborock type-2 IMAGE block** from the existing Map Extractor coordinator's \`map_data_raw\` Gzip blob, rather than the decorated PNG. It ignores the separate type-3 PATH block and other transient blocks entirely. The diagnostic mask includes only occupied wall/obstacle cells; free, scan and room cells are excluded. A bounded Gzip decoder and strict metadata/dimension checks fail closed on unexpected data.

The saved reference geometry schema is now 3. **After upgrading, capture a new complete reference** with \`roberto_zones.capture_reference\`. Existing historical checkpoint baselines are invalidated when capturing a new reference.

Expected diagnostic attributes:

\`\`\`yaml
geometry_source: cached_roborock_raw_image_block
geometry_only: true
tracks_included: false
scan_floor_included: false
\`\`\`

Registration candidates and three-distinct-geometry-update stability checks remain diagnostic; they do not prove navigation coordinates or route safety. No new network traffic, container, timer or robot command is introduced. Your existing Xiaomi Vacuum Map Card remains the sole live-map controller.

See [README_DE.md](README_DE.md) for German installation and testing instructions.
