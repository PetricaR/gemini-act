import React, { useMemo, useState } from 'react';
import {
  Compass,
  ExternalLink,
  Footprints,
  Home,
  Info,
  MapPin,
  Star,
} from 'lucide-react';
import { orderedCategories } from '../lib/categories.js';
import { radiusToPercent, toPercent } from '../lib/mercator.js';
import { distance, num, scoreTone, walkTime } from '../lib/format.js';
import ProvenanceBadge from './ProvenanceBadge.jsx';

/**
 * The property's 500 m walkable radius, drawn over a real Google base map.
 *
 * The map image itself is a plain roadmap with no markers baked in: every pin
 * here is ours, positioned by reprojecting the POI's real coordinates with the
 * same Web Mercator math the server used to request the image. That is what
 * buys the category icon, the colour coding, the hover card and the ability to
 * filter a category out of the picture — none of which a Static Maps `markers`
 * parameter can do.
 */
export default function LocationMap({ locatie, adresa }) {
  const [activeCategory, setActiveCategory] = useState(null);
  const [hovered, setHovered] = useState(null);
  const [mapFailed, setMapFailed] = useState(false);

  const harta = locatie?.harta;
  const categories = useMemo(
    () => orderedCategories(locatie?.facilitati, locatie?.meta_categorii),
    [locatie],
  );

  const pins = useMemo(() => {
    if (!harta || !locatie?.lat) return [];
    const center = { lat: locatie.lat, lon: locatie.lon };
    const out = [];
    categories.forEach((category) => {
      category.items.forEach((item, index) => {
        if (typeof item.lat !== 'number' || typeof item.lon !== 'number') return;
        const position = toPercent(item, center, harta.zoom, harta.latime, harta.inaltime);
        if (!position.inside) return;
        out.push({ ...position, item, category, order: out.length, rank: index });
      });
    });
    return out;
  }, [categories, harta, locatie]);

  if (!locatie || locatie.status !== 'success') {
    return (
      <section id="locatie" className="card card-pad mb-6">
        <div className="flex items-start gap-3">
          <div className="icon-tile bg-slate-50 border-slate-200 text-slate-500">
            <MapPin className="h-5 w-5" />
          </div>
          <div>
            <h3 className="section-title">Hartă facilități pe o rază de 500 m</h3>
            <p className="section-sub">
              {locatie?.motiv ||
                'Datele de localizare nu au putut fi obținute pentru această adresă.'}
            </p>
          </div>
        </div>
      </section>
    );
  }

  const visible = activeCategory ? pins.filter((p) => p.category.key === activeCategory) : pins;
  const circleSize = radiusToPercent(harta.raza_m, locatie.lat, harta.zoom, harta.latime);
  const tone = scoreTone(locatie.scor_accesibilitate);

  return (
    <section id="locatie" className="card card-pad mb-6">
      <div className="card-head">
        <div className="flex items-start gap-3">
          <div className="icon-tile bg-emerald-50 border-emerald-200 text-emerald-600">
            <Compass className="h-5 w-5" />
          </div>
          <div>
            <div className="flex flex-wrap items-center gap-2">
              <h3 className="section-title">
                Facilități în raza de {num(harta.raza_m)} m — hartă cartografiată
              </h3>
              <ProvenanceBadge
                provenance="masurat"
                detail="Google Places &amp; Routes"
              />
            </div>
            <p className="section-sub">
              {locatie.total_facilitati} puncte de interes reale, preluate din Google Places și
              poziționate pe hartă după coordonatele lor. Timpul de mers pentru cea mai apropiată
              facilitate din fiecare categorie este calculat pe traseu pietonal real.
            </p>
          </div>
        </div>

        {typeof locatie.scor_accesibilitate === 'number' && (
          <div className={`rounded-xl border px-4 py-2.5 text-right ${tone.bg} ${tone.border}`}>
            <div className="label">Scor accesibilitate</div>
            <div className={`text-lg font-extrabold ${tone.text} tabular-nums`}>
              {locatie.scor_accesibilitate}
              <span className="text-xs font-semibold text-slate-500"> / 10</span>
            </div>
            <div className="mt-0.5 text-[10px] text-slate-500">formulă internă ponderată</div>
          </div>
        )}
      </div>

      {/* Address strip */}
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2 mb-5 text-xs">
        <span className="inline-flex items-center gap-1.5 font-semibold text-slate-700">
          <MapPin className="h-3.5 w-3.5 text-rose-500" />
          {locatie.adresa_formatata || adresa}
        </span>
        <span className="text-slate-400">
          {locatie.lat.toFixed(5)}, {locatie.lon.toFixed(5)}
        </span>
        <span
          className={`pill ${
            locatie.precizie === 'adresa'
              ? 'bg-emerald-50 text-emerald-700 border-emerald-200'
              : 'bg-amber-50 text-amber-700 border-amber-200'
          }`}
        >
          {locatie.precizie === 'adresa'
            ? 'Geocodare exactă la adresă'
            : 'Geocodare aproximativă la nivel de zonă'}
        </span>
        <a
          href={locatie.google_maps_url}
          target="_blank"
          rel="noopener noreferrer"
          className="inline-flex items-center gap-1 font-semibold text-sky-700 hover:text-sky-800"
        >
          Deschide în Google Maps
          <ExternalLink className="h-3 w-3" />
        </a>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-[minmax(0,1.35fr)_minmax(0,1fr)] gap-5">
        {/* ---------------------------------------------------------------- */}
        {/* Map + overlay                                                     */}
        {/* ---------------------------------------------------------------- */}
        <div>
          <div
            className="relative overflow-hidden rounded-2xl border border-slate-200 bg-slate-100"
            style={{ aspectRatio: `${harta.latime} / ${harta.inaltime}` }}
          >
            {mapFailed ? (
              <div className="absolute inset-0 grid place-content-center text-center px-6">
                <MapPin className="h-7 w-7 text-slate-300 mx-auto mb-2" />
                <p className="text-xs text-slate-500">
                  Harta de bază nu a putut fi încărcată de la Google Maps.
                </p>
              </div>
            ) : (
              <img
                src={harta.url}
                alt={`Hartă a zonei ${locatie.adresa_formatata || adresa}`}
                className="absolute inset-0 h-full w-full object-cover"
                loading="lazy"
                onError={() => setMapFailed(true)}
              />
            )}

            {/* The 500 m walking radius */}
            <div
              className="absolute rounded-full border-2 border-sky-500/70 bg-sky-400/10 pointer-events-none"
              style={{
                width: `${circleSize}%`,
                aspectRatio: '1 / 1',
                left: '50%',
                top: '50%',
                transform: 'translate(-50%, -50%)',
              }}
            />
            <div
              className="absolute pointer-events-none text-[10px] font-bold uppercase tracking-wider
                         text-sky-800 bg-white/85 px-1.5 py-0.5 rounded"
              style={{
                left: '50%',
                top: `calc(50% - ${circleSize / 2}%)`,
                transform: 'translate(-50%, -140%)',
              }}
            >
              Rază {num(harta.raza_m)} m
            </div>

            {/* Facility pins */}
            {visible.map((pin) => {
              const { Icon, color } = pin.category;
              const isHovered = hovered === pin.order;
              // The nearest of each category is drawn a size up: in a dense
              // radius it is the one that actually matters, and it is the one
              // whose walking time was measured rather than estimated.
              const isNearest = pin.rank === 0;
              return (
                <button
                  key={`${pin.category.key}-${pin.item.nume}-${pin.order}`}
                  type="button"
                  className="map-pin absolute z-10 focus:outline-none"
                  style={{
                    left: `${pin.left}%`,
                    top: `${pin.top}%`,
                    transform: 'translate(-50%, -100%)',
                    animationDelay: `${Math.min(pin.order * 22, 700)}ms`,
                    zIndex: isHovered ? 40 : 10 + (20 - Math.min(pin.rank, 20)),
                  }}
                  onMouseEnter={() => setHovered(pin.order)}
                  onMouseLeave={() => setHovered(null)}
                  onFocus={() => setHovered(pin.order)}
                  onBlur={() => setHovered(null)}
                  aria-label={`${pin.category.label}: ${pin.item.nume}, ${distance(
                    pin.item.distanta_m,
                  )}`}
                >
                  <span
                    className={`flex items-center justify-center rounded-full border-2 border-white
                                shadow-lift ring-1 ring-black/10 transition-transform hover:scale-125
                                ${isNearest ? 'h-7 w-7' : 'h-5 w-5'}`}
                    style={{ backgroundColor: color }}
                  >
                    <Icon
                      className={isNearest ? 'h-3.5 w-3.5 text-white' : 'h-2.5 w-2.5 text-white'}
                      strokeWidth={2.6}
                    />
                  </span>

                  {isHovered && (
                    <span
                      className="absolute left-1/2 bottom-full mb-1.5 -translate-x-1/2 w-max
                                 max-w-[190px] rounded-lg bg-slate-900 px-2.5 py-1.5 text-left
                                 shadow-lift"
                    >
                      <span className="block text-[11px] font-bold text-white leading-tight">
                        {pin.item.nume}
                      </span>
                      <span className="block text-[10px] text-slate-300 mt-0.5">
                        {pin.category.label} · {distance(pin.item.distanta_m)} ·{' '}
                        {walkTime(pin.item.minute_mers, pin.item.minute_estimate)}
                      </span>
                      {typeof pin.item.rating === 'number' && (
                        <span className="mt-0.5 flex items-center gap-1 text-[10px] text-amber-300">
                          <Star className="h-2.5 w-2.5 fill-amber-300 text-amber-300" />
                          {pin.item.rating.toFixed(1)}
                          {pin.item.numar_recenzii ? ` (${pin.item.numar_recenzii})` : ''}
                        </span>
                      )}
                    </span>
                  )}
                </button>
              );
            })}

            {/* The property itself, always on top */}
            <div
              className="absolute z-50"
              style={{ left: '50%', top: '50%', transform: 'translate(-50%, -100%)' }}
            >
              <span
                className="flex h-9 w-9 items-center justify-center rounded-full bg-rose-600
                           border-[3px] border-white shadow-lift"
              >
                <Home className="h-4 w-4 text-white" strokeWidth={2.6} />
              </span>
            </div>

            <span
              className="absolute bottom-1.5 right-2 text-[9px] font-medium text-slate-700
                         bg-white/80 px-1.5 py-0.5 rounded"
            >
              {harta.atribuire}
            </span>
          </div>

          <p className="mt-2 flex items-start gap-1.5 text-[11px] text-slate-500">
            <Info className="h-3.5 w-3.5 flex-shrink-0 mt-px text-slate-400" />
            Fiecare pin este poziționat după coordonatele reale ale locului. Apasă o categorie din
            legendă pentru a izola facilitățile de acel tip.
          </p>
        </div>

        {/* ---------------------------------------------------------------- */}
        {/* Legend + list                                                     */}
        {/* ---------------------------------------------------------------- */}
        <div>
          <div className="flex items-center justify-between mb-2">
            <span className="label">Legendă & facilități</span>
            {activeCategory && (
              <button
                type="button"
                onClick={() => setActiveCategory(null)}
                className="text-[11px] font-semibold text-sky-700 hover:text-sky-800"
              >
                Arată toate
              </button>
            )}
          </div>

          <div className="flex flex-wrap gap-1.5 mb-4">
            {categories.map((category) => {
              const { Icon, color, key, label, items } = category;
              const isActive = activeCategory === key;
              return (
                <button
                  key={key}
                  type="button"
                  onClick={() => setActiveCategory(isActive ? null : key)}
                  className={`pill transition-colors ${
                    isActive
                      ? 'text-white border-transparent'
                      : 'bg-white text-slate-600 border-slate-200 hover:border-slate-300'
                  }`}
                  style={isActive ? { backgroundColor: color } : undefined}
                >
                  <Icon
                    className="h-3.5 w-3.5"
                    style={{ color: isActive ? '#fff' : color }}
                    strokeWidth={2.4}
                  />
                  {label}
                  <span
                    className={`ml-0.5 tabular-nums ${isActive ? 'text-white/80' : 'text-slate-400'}`}
                  >
                    {items.length}
                  </span>
                </button>
              );
            })}
          </div>

          <div className="max-h-[420px] overflow-y-auto pr-1 space-y-3">
            {categories
              .filter((category) => !activeCategory || category.key === activeCategory)
              .map((category) => {
                const { Icon, color, key, label, items } = category;
                return (
                  <div key={key} className="rounded-xl border border-slate-200 overflow-hidden">
                    <div className="flex items-center gap-2 px-3 py-2 bg-slate-50 border-b border-slate-200">
                      <Icon className="h-3.5 w-3.5" style={{ color }} strokeWidth={2.4} />
                      <span className="text-xs font-bold text-slate-800">{label}</span>
                      <span className="ml-auto text-[11px] text-slate-500 tabular-nums">
                        cel mai apropiat la {distance(items[0]?.distanta_m)}
                      </span>
                    </div>
                    <ul className="divide-y divide-slate-100">
                      {items.map((item) => (
                        <li
                          key={`${key}-${item.nume}-${item.distanta_m}`}
                          className="flex items-start justify-between gap-3 px-3 py-2 hover:bg-slate-50"
                        >
                          <div className="min-w-0">
                            <div className="text-xs font-semibold text-slate-800 truncate">
                              {item.nume}
                            </div>
                            <div className="flex flex-wrap items-center gap-x-2 text-[11px] text-slate-500">
                              {item.detaliu && <span className="truncate">{item.detaliu}</span>}
                              {typeof item.rating === 'number' && (
                                <span className="inline-flex items-center gap-0.5 text-amber-600">
                                  <Star className="h-2.5 w-2.5 fill-amber-500 text-amber-500" />
                                  {item.rating.toFixed(1)}
                                  {item.numar_recenzii ? ` (${item.numar_recenzii})` : ''}
                                </span>
                              )}
                            </div>
                          </div>
                          <div className="text-right flex-shrink-0">
                            <div className="text-xs font-bold text-slate-800 tabular-nums">
                              {distance(item.distanta_m)}
                            </div>
                            <div className="inline-flex items-center gap-1 text-[11px] text-slate-500">
                              <Footprints className="h-3 w-3 text-slate-400" />
                              {walkTime(item.minute_mers, item.minute_estimate)}
                            </div>
                          </div>
                        </li>
                      ))}
                    </ul>
                  </div>
                );
              })}
          </div>

          <p className="mt-2 text-[11px] text-slate-400">
            „~” marchează un timp estimat din distanța în linie dreaptă; celelalte provin din Google
            Routes, pe traseu pietonal.
          </p>
        </div>
      </div>
    </section>
  );
}
