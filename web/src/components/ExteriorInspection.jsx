import React, { useState } from 'react';
import {
  Camera,
  CameraOff,
  Car,
  CheckCircle2,
  Compass,
  Layers,
  Maximize2,
  Satellite,
  Zap,
} from 'lucide-react';
import { captureDate, scoreTone } from '../lib/format.js';

/**
 * The exterior the seller did not photograph.
 *
 * Street View is fetched at four headings around the geocoded point, so the
 * facade, both approaches down the street and the outlook are all visible; the
 * aerial frame shows the plot, the parking and what is actually built next door.
 * Both come through this app's own proxy — the Maps key stays server-side.
 */
export default function ExteriorInspection({ audit, locatie, adresa }) {
  const [lightbox, setLightbox] = useState(null);

  const streetView = locatie?.street_view;
  const angles = streetView?.unghiuri || [];
  const aerial = locatie?.satelit;
  const captured = captureDate(streetView?.data_captura);

  const findings = [
    { icon: CheckCircle2, label: 'Fațadă & finisaje exterioare', value: audit?.stare_fatada },
    { icon: Compass, label: 'Trotuare & căi de acces', value: audit?.trotuare_si_acces },
    { icon: Zap, label: 'Cabluri aeriene & utilități', value: audit?.cabluri_aeriene },
    { icon: Car, label: 'Parcare & căi rutiere', value: audit?.parcare_si_strazi },
    { icon: Layers, label: 'Acoperiș & terasă', value: audit?.acoperis_terasa },
  ].filter((item) => item.value);

  const score = audit?.scor_exterior ?? audit?.scor_fatada;
  const tone = scoreTone(score);
  const hasImagery = angles.length > 0 || Boolean(aerial?.url);

  if (!audit && !hasImagery) return null;

  return (
    <section id="exterior" className="card card-pad mb-6">
      <div className="card-head">
        <div className="flex items-start gap-3">
          <div className="icon-tile bg-sky-50 border-sky-200 text-sky-600">
            <Camera className="h-5 w-5" />
          </div>
          <div>
            <h3 className="section-title">
              Inspecție exterioară — Google Street View 360° & ortofotoplan
            </h3>
            <p className="section-sub">
              Fotografii reale ale clădirii și ale străzii, pe patru direcții, plus imaginea aeriană
              a incintei. Sunt singurele imagini din raport pe care vânzătorul nu le controlează.
            </p>
          </div>
        </div>

        {typeof score === 'number' && (
          <div className={`rounded-xl border px-4 py-2.5 text-right ${tone.bg} ${tone.border}`}>
            <div className="label">Scor infrastructură</div>
            <div className={`text-lg font-extrabold ${tone.text} tabular-nums`}>
              {score}
              <span className="text-xs font-semibold text-slate-500"> / 10</span>
            </div>
            {audit?.clasa_fatada && (
              <div className="text-[11px] text-slate-500 mt-0.5">{audit.clasa_fatada}</div>
            )}
          </div>
        )}
      </div>

      {/* Street View, four headings */}
      {angles.length > 0 ? (
        <>
          <div className="flex flex-wrap items-center justify-between gap-2 mb-2">
            <span className="label">Street View 360° · patru direcții din punctul imobilului</span>
            {captured && (
              <span className="text-[11px] text-slate-500">
                Imagini captate în {captured} · {streetView.copyright}
              </span>
            )}
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-3 mb-6">
            {angles.map((angle) => (
              <ImageTile
                key={angle.heading}
                src={angle.url}
                caption={`Direcția ${angle.eticheta} · ${angle.heading}°`}
                alt={`Street View spre ${angle.eticheta} din dreptul adresei ${adresa || ''}`}
                onOpen={() =>
                  setLightbox({
                    src: angle.url,
                    caption: `Google Street View · direcția ${angle.eticheta} (${angle.heading}°)`,
                  })
                }
              />
            ))}
          </div>
        </>
      ) : (
        <div className="mb-6 flex items-center gap-3 rounded-xl border border-slate-200 bg-slate-50 p-4">
          <CameraOff className="h-5 w-5 text-slate-400 flex-shrink-0" />
          <p className="text-xs text-slate-600">
            Google nu are acoperire Street View pentru acest punct, deci raportul nu afirmă nimic
            despre aspectul fațadei pe baza unei fotografii inexistente.
          </p>
        </div>
      )}

      {/* Aerial + findings */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
        {aerial?.url && (
          <div>
            <div className="flex items-center justify-between gap-2 mb-2">
              <span className="label inline-flex items-center gap-1.5">
                <Satellite className="h-3.5 w-3.5 text-slate-400" />
                Imagine aeriană a incintei
              </span>
            </div>
            <ImageTile
              src={aerial.url}
              alt={`Ortofotoplan al imobilului de la ${adresa || ''}`}
              caption={`Ortofotoplan © ${aerial.atribuire}`}
              tall
              onOpen={() =>
                setLightbox({
                  src: aerial.url,
                  caption: `Ortofotoplan © ${aerial.atribuire}`,
                })
              }
            />
          </div>
        )}

        {findings.length > 0 && (
          <div>
            <span className="label">Constatări din inspecția vizuală</span>
            <div className="mt-2 space-y-2">
              {findings.map(({ icon: Icon, label, value }) => (
                <div key={label} className="rounded-xl border border-slate-200 bg-slate-50/60 p-3">
                  <div className="flex items-center gap-2 text-xs font-bold text-slate-800">
                    <Icon className="h-3.5 w-3.5 text-emerald-600 flex-shrink-0" />
                    {label}
                  </div>
                  <p className="mt-1 text-xs text-slate-600 leading-relaxed">{value}</p>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>

      {lightbox && (
        <button
          type="button"
          className="fixed inset-0 z-[100] flex flex-col items-center justify-center gap-3
                     bg-slate-950/80 p-4 backdrop-blur-sm"
          onClick={() => setLightbox(null)}
          aria-label="Închide imaginea"
        >
          <img
            src={lightbox.src}
            alt={lightbox.caption}
            className="max-h-[80vh] max-w-full rounded-xl shadow-lift object-contain"
          />
          <span className="text-xs font-medium text-white/90">{lightbox.caption}</span>
        </button>
      )}
    </section>
  );
}

function ImageTile({ src, alt, caption, onOpen, tall = false }) {
  const [failed, setFailed] = useState(false);

  if (failed) {
    return (
      <div
        className={`grid place-content-center rounded-xl border border-slate-200 bg-slate-50
                    text-center px-4 ${tall ? 'aspect-[4/3]' : 'aspect-[16/10]'}`}
      >
        <CameraOff className="h-5 w-5 text-slate-300 mx-auto mb-1.5" />
        <span className="text-[11px] text-slate-500">Imaginea nu a putut fi încărcată.</span>
      </div>
    );
  }

  return (
    <button
      type="button"
      onClick={onOpen}
      className={`group relative block w-full overflow-hidden rounded-xl border border-slate-200
                  bg-slate-100 ${tall ? 'aspect-[4/3]' : 'aspect-[16/10]'}`}
    >
      <img
        src={src}
        alt={alt}
        loading="lazy"
        onError={() => setFailed(true)}
        className="absolute inset-0 h-full w-full object-cover transition-transform duration-500
                   group-hover:scale-105"
      />
      <span
        className="absolute inset-x-0 bottom-0 flex items-center justify-between gap-2
                   bg-gradient-to-t from-slate-950/80 to-transparent px-2.5 pt-6 pb-2
                   text-[11px] font-semibold text-white"
      >
        {caption}
        <Maximize2 className="h-3.5 w-3.5 opacity-0 transition-opacity group-hover:opacity-100" />
      </span>
    </button>
  );
}
