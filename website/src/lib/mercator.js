/**
 * Web Mercator projection, mirroring `gemini_act/api/imagery.py`.
 *
 * The backend returns a Static Maps image plus the exact `zoom`, `latime` and
 * `inaltime` it asked Google for. Reprojecting the POI coordinates here with the
 * same math is what lets us draw our own pins — with a category icon, a colour
 * and a hover card — instead of the flat, uncustomisable markers the Static Maps
 * `markers` parameter bakes into the image.
 *
 * Any change to the projection here has to be mirrored there, and vice versa.
 */

const TILE_PX = 256;
const MAX_LAT = 85.05112878;

export function worldSize(zoom) {
  return TILE_PX * 2 ** zoom;
}

/** Lat/lon -> absolute pixel coordinates at `zoom`. */
export function project(lat, lon, zoom) {
  const size = worldSize(zoom);
  const clamped = Math.max(Math.min(lat, MAX_LAT), -MAX_LAT);
  const sinLat = Math.sin((clamped * Math.PI) / 180);
  return {
    x: ((lon + 180) / 360) * size,
    y: (0.5 - Math.log((1 + sinLat) / (1 - sinLat)) / (4 * Math.PI)) * size,
  };
}

export function metersPerPixel(lat, zoom) {
  return (156543.03392 * Math.cos((lat * Math.PI) / 180)) / 2 ** zoom;
}

/**
 * Where a point sits on the rendered map, as percentages of its box.
 *
 * Percentages rather than pixels because the <img> is fluid: the map is
 * requested at a fixed 640x480 but displayed at whatever width the column is,
 * and a percentage survives that scaling untouched.
 */
export function toPercent({ lat, lon }, center, zoom, width, height) {
  const point = project(lat, lon, zoom);
  const origin = project(center.lat, center.lon, zoom);
  const dx = point.x - origin.x;
  const dy = point.y - origin.y;
  return {
    left: (0.5 + dx / width) * 100,
    top: (0.5 + dy / height) * 100,
    // Anything beyond the frame would be drawn clamped to an edge, which reads
    // as a real location it is not — the caller drops those instead.
    inside: Math.abs(dx) <= width / 2 - 6 && Math.abs(dy) <= height / 2 - 6,
  };
}

/** Diameter of a `radiusM` circle, as a percentage of the map's width. */
export function radiusToPercent(radiusM, lat, zoom, width) {
  const px = radiusM / metersPerPixel(lat, zoom);
  return ((px * 2) / width) * 100;
}
