import React, { useState } from 'react';
import {
  AlertTriangle,
  Calendar,
  CheckCircle2,
  Download,
  ExternalLink,
  ImageOff,
  Layers,
  MapPin,
  TrendingDown,
  TrendingUp,
} from 'lucide-react';
import {
  eur,
  eurPerSqm,
  num,
  percent,
  priceDelta,
  priceGap,
  scoreTone,
  sqm,
} from '../lib/format.js';

/**
 * The first screen of the report: what the property is, what it costs, what we
 * think it is worth, and the one number that summarises the technical audit.
 *
 * Everything below in the page elaborates on one of these four figures, so they
 * are stated once, here, and never recomputed differently further down.
 */
export default function PropertySummary({ data, pdfUrl }) {
  if (!data) return null;

  const score = data.scor_general;
  const tone = scoreTone(score);
  const price = data.pret_total || 0;
  const surface = data.suprafata_utila || 0;
  const pricePerSqm = surface > 0 ? Math.round(price / surface) : null;

  const valuation = data.evaluare_anevar || {};
  const isValuationAvailable =
    valuation.status !== 'indisponibil' &&
    valuation.disponibil !== false &&
    valuation.valoare_estimata_piata != null &&
    (valuation.comparabile_utilizate || []).length >= 3;
  const marketValue = isValuationAvailable ? valuation.valoare_estimata_piata : null;
  const delta = isValuationAvailable ? priceDelta(price, marketValue, valuation.ajustare_recomandata_procent) : null;
  const margin = isValuationAvailable ? priceGap(price, marketValue, valuation.marja_negociere_eur) : null;
  const overpriced = delta != null && delta > 0;

  return (
    <section id="sinteza" className="card card-pad mb-6">
      <div className="flex flex-col gap-6 border-b border-slate-200 pb-6 lg:flex-row lg:items-start lg:justify-between">
        <div className="min-w-0 flex-1 space-y-2.5">
          <div className="flex flex-wrap items-center gap-2">
            {data.complex_name && (
              <span className="pill border-sky-200 bg-sky-50 text-sky-700">
                {data.complex_name}
              </span>
            )}
            {data.an_constructie && (
              <span className="pill border-slate-200 bg-slate-50 text-slate-600">
                <Calendar className="h-3 w-3 text-slate-400" />
                An construire {data.an_constructie}
              </span>
            )}
            {data.etaj && (
              <span className="pill border-slate-200 bg-slate-50 text-slate-600">
                <Layers className="h-3 w-3 text-slate-400" />
                {data.etaj}
              </span>
            )}
            {data.camere && (
              <span className="pill border-slate-200 bg-slate-50 text-slate-600">
                {data.camere} camere
              </span>
            )}
          </div>

          <h2 className="text-xl font-bold tracking-tight text-slate-900 sm:text-2xl">
            {data.titlu || 'Proprietate rezidențială'}
          </h2>

          <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-slate-500">
            <span className="inline-flex items-center gap-1.5">
              <MapPin className="h-3.5 w-3.5 flex-shrink-0 text-rose-500" />
              {data.adresa || '—'}
            </span>
            {data.url && (
              <a
                href={data.url}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-1 font-semibold text-sky-700 hover:text-sky-800"
              >
                Anunțul original
                <ExternalLink className="h-3 w-3" />
              </a>
            )}
          </div>
        </div>

        {/* The headline score */}
        <div
          className={`flex flex-shrink-0 items-center gap-4 self-start rounded-2xl border px-5 py-4
                      ${tone.bg} ${tone.border}`}
        >
          <div
            className={`flex h-20 w-20 flex-col items-center justify-center rounded-full border-4
                        bg-white ${tone.ring}`}
          >
            <span className={`text-2xl font-extrabold leading-none ${tone.text}`}>
              {typeof score === 'number' ? num(score, 1) : '—'}
            </span>
            <span className="mt-0.5 text-[10px] font-bold uppercase text-slate-400">din 10</span>
          </div>
          <div>
            <div className="label">Scor tehnic &amp; risc</div>
            <div className={`mt-0.5 flex items-center gap-1.5 text-sm font-extrabold ${tone.text}`}>
              {tone.key === 'excellent' || tone.key === 'good' ? (
                <CheckCircle2 className="h-4 w-4" />
              ) : (
                <AlertTriangle className="h-4 w-4" />
              )}
              {data.calificativ_general || tone.label}
            </div>
            <div className="mt-1 max-w-[190px] text-[11px] leading-snug text-slate-500">
              Compus din starea finisajelor, defectele detectate, infrastructura exterioară și
              bonitatea dezvoltatorului.
            </div>
          </div>
        </div>
      </div>

      {/* Key figures */}
      <div className="grid grid-cols-2 gap-3 pt-6 sm:gap-4 lg:grid-cols-4">
        <div className="stat">
          <div className="label">Preț solicitat</div>
          <div className="stat-value">{eur(price)}</div>
          <div className="stat-note">{pricePerSqm ? eurPerSqm(pricePerSqm) : '—'} util</div>
        </div>

        {isValuationAvailable ? (
          <div className="stat border-sky-200 bg-sky-50/70">
            <div className="label text-sky-700">Valoare de piață estimată</div>
            <div className="stat-value text-sky-700">{eur(marketValue)}</div>
            <div className="stat-note">
              {valuation.pret_pe_mp_estimat ? eurPerSqm(valuation.pret_pe_mp_estimat) : 'GEV 630'}
            </div>
          </div>
        ) : (
          <div className="stat border-slate-200 bg-slate-50/70">
            <div className="label text-slate-500">Valoare de piață estimată</div>
            <div className="stat-value text-base font-semibold text-slate-500">Indisponibil</div>
            <div className="stat-note">&lt; 3 comparabile ANEVAR</div>
          </div>
        )}

        {isValuationAvailable ? (
          <div className={`stat ${overpriced ? 'border-rose-200 bg-rose-50/70' : 'border-emerald-200 bg-emerald-50/70'}`}>
            <div className="label">Ecart față de piață</div>
            <div
              className={`stat-value flex items-center gap-1 ${
                overpriced ? 'text-rose-700' : 'text-emerald-700'
              }`}
            >
              {overpriced ? (
                <TrendingUp className="h-4 w-4" />
              ) : (
                <TrendingDown className="h-4 w-4" />
              )}
              {percent(delta, { signed: true })}
            </div>
            <div className="stat-note">marjă de negociere ~{eur(margin)}</div>
          </div>
        ) : (
          <div className="stat border-slate-200 bg-slate-50/70">
            <div className="label text-slate-500">Ecart față de piață</div>
            <div className="stat-value text-base font-semibold text-slate-400">—</div>
            <div className="stat-note">eșantion insuficient</div>
          </div>
        )}

        <div className="stat">
          <div className="label">Suprafață utilă</div>
          <div className="stat-value">{sqm(surface)}</div>
          <div className="stat-note">
            {data.camere ? `${data.camere} camere` : '—'}
            {data.etaj ? ` · ${data.etaj}` : ''}
          </div>
        </div>
      </div>

      {data.rezumat_executiv && (
        <div className="mt-6 rounded-xl border border-slate-200 bg-slate-50/70 p-4">
          <div className="label mb-1.5">Rezumat executiv</div>
          <p className="text-sm leading-relaxed text-slate-700">{data.rezumat_executiv}</p>
        </div>
      )}

      <StrengthsAndWeaknesses strengths={data.puncte_forte} weaknesses={data.puncte_slabe} />

      <Gallery images={data.imagini} title={data.titlu} />

      {pdfUrl && (
        <div className="no-print mt-6 flex flex-col items-start justify-between gap-3 rounded-xl border border-sky-200 bg-sky-50/60 p-4 sm:flex-row sm:items-center">
          <div>
            <div className="text-xs font-bold uppercase tracking-wider text-slate-800">
              Dosar tehnic complet, în format tipăribil
            </div>
            <div className="mt-0.5 text-xs text-slate-600">
              Aceleași capitole ca mai jos, exportate ca raport PDF pentru dosarul de achiziție.
            </div>
          </div>
          <a
            href={pdfUrl}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex w-full flex-shrink-0 items-center justify-center gap-2 rounded-xl
                       bg-slate-900 px-5 py-2.5 text-xs font-bold text-white shadow-card
                       transition-colors hover:bg-slate-800 sm:w-auto"
          >
            <Download className="h-4 w-4" />
            Descarcă raportul PDF
          </a>
        </div>
      )}
    </section>
  );
}

function StrengthsAndWeaknesses({ strengths, weaknesses }) {
  if (!strengths?.length && !weaknesses?.length) return null;
  return (
    <div className="mt-4 grid grid-cols-1 gap-3 md:grid-cols-2">
      {strengths?.length > 0 && (
        <div className="rounded-xl border border-emerald-200 bg-emerald-50/60 p-4">
          <div className="label mb-2 text-emerald-700">Puncte forte</div>
          <ul className="space-y-1.5">
            {strengths.map((item) => (
              <li key={item} className="flex items-start gap-2 text-xs leading-relaxed text-slate-700">
                <CheckCircle2 className="mt-0.5 h-3.5 w-3.5 flex-shrink-0 text-emerald-600" />
                {item}
              </li>
            ))}
          </ul>
        </div>
      )}
      {weaknesses?.length > 0 && (
        <div className="rounded-xl border border-amber-200 bg-amber-50/60 p-4">
          <div className="label mb-2 text-amber-700">Puncte slabe &amp; atenționări</div>
          <ul className="space-y-1.5">
            {weaknesses.map((item) => (
              <li key={item} className="flex items-start gap-2 text-xs leading-relaxed text-slate-700">
                <AlertTriangle className="mt-0.5 h-3.5 w-3.5 flex-shrink-0 text-amber-600" />
                {item}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

function Gallery({ images, title }) {
  const [failed, setFailed] = useState({});
  const usable = (images || []).filter((image) => typeof image === 'string');
  if (usable.length === 0) return null;

  return (
    <div className="mt-6">
      <div className="label mb-2">Fotografii din anunț</div>
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        {usable.slice(0, 8).map((image, index) => (
          <div
            key={image}
            className="relative aspect-[4/3] overflow-hidden rounded-xl border border-slate-200 bg-slate-100"
          >
            {failed[image] ? (
              <div className="grid h-full place-content-center text-center">
                <ImageOff className="mx-auto h-5 w-5 text-slate-300" />
              </div>
            ) : (
              <img
                src={image}
                alt={`${title || 'Proprietate'} — fotografia ${index + 1}`}
                loading="lazy"
                onError={() => setFailed((prev) => ({ ...prev, [image]: true }))}
                className="h-full w-full object-cover transition-transform duration-500 hover:scale-105"
              />
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
