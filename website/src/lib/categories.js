/**
 * Amenity categories -> the glyph and colour their map pins are drawn with.
 *
 * The backend (`api/imagery.py: CATEGORY_META`) names an icon per category as a
 * kebab-case lucide name; this maps those names onto the actual components, so
 * adding a category server-side only needs a line here to become a real pin
 * rather than the generic fallback.
 */

import {
  Baby,
  Bus,
  Dumbbell,
  MapPin,
  Pill,
  School,
  ShoppingBag,
  ShoppingCart,
  Stethoscope,
  Store,
  ToyBrick,
  TrainFront,
  Trees,
} from 'lucide-react';

const ICONS = {
  'train-front': TrainFront,
  bus: Bus,
  school: School,
  baby: Baby,
  trees: Trees,
  'toy-brick': ToyBrick,
  'shopping-cart': ShoppingCart,
  'shopping-bag': ShoppingBag,
  store: Store,
  pill: Pill,
  stethoscope: Stethoscope,
  dumbbell: Dumbbell,
};

/** Used when the server sends a category this build has not been taught yet. */
const FALLBACK = { eticheta: 'Alte facilități', icon: 'map-pin', culoare: '#475569' };

export function categoryIcon(iconName) {
  return ICONS[iconName] || MapPin;
}

export function categoryMeta(key, metaFromServer) {
  const meta = (metaFromServer && metaFromServer[key]) || FALLBACK;
  return {
    key,
    label: meta.eticheta || key,
    color: meta.culoare || FALLBACK.culoare,
    Icon: categoryIcon(meta.icon),
  };
}

/**
 * Categories in a stable display order — nearest-first would reshuffle the
 * legend on every report, and a legend that moves is a legend nobody learns.
 */
export const CATEGORY_ORDER = [
  'metrou',
  'transport',
  'supermarket',
  'mall',
  'piata',
  'farmacii',
  'medical',
  'scoli',
  'gradinite',
  'parcuri',
  'joaca',
  'sport',
];

export function orderedCategories(facilities, metaFromServer) {
  const keys = Object.keys(facilities || {});
  keys.sort((a, b) => {
    const ia = CATEGORY_ORDER.indexOf(a);
    const ib = CATEGORY_ORDER.indexOf(b);
    return (ia === -1 ? 99 : ia) - (ib === -1 ? 99 : ib);
  });
  return keys.map((key) => ({
    ...categoryMeta(key, metaFromServer),
    items: facilities[key] || [],
  }));
}
