import React, { useState } from 'react';
import {
  Calculator,
  ChevronDown,
  ChevronUp,
  ExternalLink,
  Info,
  Scale,
  TrendingDown,
  TrendingUp,
} from 'lucide-react';
import { eur, eurPerSqm, num, percent, priceDelta, priceGap, sqm } from '../lib/format.js';
import ProvenanceBadge from './ProvenanceBadge.jsx';
import UnavailableBlock from './UnavailableBlock.jsx';

/**
 * The comparison approach (SEV 103 / GEV 630 §54-58) in full: the gauge, the
 * per-square-metre figures, and the adjustment grid behind each comparable.
 *
 * The grid is what makes the estimate arguable in a negotiation — a headline
 * "worth 328.000 €" persuades nobody, "worth 328.000 € because this identical
 * flat two floors down sold at 2.826 €/mp in April, +1,5% for the floor" does.
 */
export default function ValuationMeter({ evaluare, pretTotal, suprafata }) {
  const [openComparable, setOpenComparable] = useState(null);
  if (!evaluare) return null;

  const comparables = evaluare.comparabile_utilizate || [];
  const isUnavailable =
    evaluare.status === 'indisponibil' ||
    evaluare.disponibil === false ||
    !evaluare.valoare_estimata_piata ||
    comparables.length < 3;

  if (isUnavailable) {
    return (
      <section id="evaluare" className="card card-pad mb-6">
        <div className="card-head">
          <div className="flex items-start gap-3">
            <div className="icon-tile border-slate-200 bg-slate-50 text-slate-500">
              <Calculator className="h-5 w-5" />
            </div>
            <div>
              <div className="flex flex-wrap items-center gap-2">
                <h3 className="section-title">Evaluare comparativă ANEVAR (GEV 630)</h3>
                <ProvenanceBadge
                  provenance="indisponibil"
                  detail="Sub 3 comparabile"
                />
              </div>
              <p className="section-sub">
                Analiză pe proprietăți comparabile din aceeași arie conform standardelor ANEVAR.
              </p>
            </div>
          </div>
        </div>

        <UnavailableBlock
          title="Evaluare de piață nedeterminată (eșantion insuficient)"
          reason={
            evaluare.motiv ||
            `Standardul ANEVAR GEV 630 impune un eșantion de minimum 3 tranzacții sau oferte comparabile calificate pentru determinarea valorii de piață. Au fost găsite doar ${comparables.length} comparabile în arie; extrapolarea valorică pe un eșantion sub minim este interzisă metodologic.`
          }
          provenance="indisponibil"
        />

        {comparables.length > 0 && (
          <div className="mt-6">
            <div className="label mb-2 text-slate-700">
              Proprietăți comparabile identificate ({comparables.length} din minim 3 necesare):
            </div>
            <div className="overflow-x-auto">
              <table className="data-table min-w-[720px]">
                <thead>
                  <tr>
                    <th>Adresă / complex</th>
                    <th>Preț</th>
                    <th>Suprafață</th>
                    <th>Preț / mp</th>
                    <th>Distanță</th>
                  </tr>
                </thead>
                <tbody>
                  {comparables.map((comparable, index) => (
                    <tr key={comparable.id || comparable.adresa || index}>
                      <td className="font-semibold text-slate-900">
                        {comparable.url ? (
                          <a
                            href={comparable.url}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="inline-flex items-center gap-1 text-sky-700 hover:text-sky-900 hover:underline"
                          >
                            {comparable.adresa || comparable.id}
                            <ExternalLink className="h-3 w-3 flex-shrink-0" />
                          </a>
                        ) : (
                          comparable.adresa || comparable.id
                        )}
                      </td>
                      <td className="font-semibold tabular-nums">{eur(comparable.pret_total || comparable.pret)}</td>
                      <td className="tabular-nums">{sqm(comparable.suprafata_utila || comparable.suprafata)}</td>
                      <td className="tabular-nums">{eurPerSqm(comparable.pret_mp || comparable.pret_mp_eur)}</td>
                      <td className="tabular-nums">
                        {comparable.distanta_km != null ? (
                          `${num(comparable.distanta_km, 2)} km`
                        ) : (
                          <span className="text-slate-400">nepublicat</span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </section>
    );
  }

  const marketValue = evaluare.valoare_estimata_piata || pretTotal || 0;
  const min = evaluare.interval_valoare_min || Math.round(marketValue * 0.95);
  const max = evaluare.interval_valoare_max || Math.round(marketValue * 1.05);
  const delta = priceDelta(pretTotal, marketValue, evaluare.ajustare_recomandata_procent);
  const margin = priceGap(pretTotal, marketValue, evaluare.marja_negociere_eur);
  const overpriced = delta > 0;

  const askedPerSqm = suprafata > 0 ? Math.round((pretTotal || 0) / suprafata) : null;
  const estimatedPerSqm =
    evaluare.pret_pe_mp_estimat || (suprafata > 0 ? Math.round(marketValue / suprafata) : null);

  // Both markers live on the same [min, max] axis; a price outside the band is
  // pinned to the end rather than allowed to run off the track.
  const spread = Math.max(max - min, 1);
  const clamp = (value) => Math.min(Math.max(Math.round(((value - min) / spread) * 100), 0), 100);
  const askedPosition = clamp(pretTotal || marketValue);
  const fairPosition = clamp(marketValue);

  return (
    <section id="evaluare" className="card card-pad mb-6">
      <div className="card-head">
        <div className="flex items-start gap-3">
          <div className="icon-tile border-emerald-200 bg-emerald-50 text-emerald-600">
            <Calculator className="h-5 w-5" />
          </div>
          <div>
            <div className="flex flex-wrap items-center gap-2">
              <h3 className="section-title">Evaluare comparativă ANEVAR (GEV 630)</h3>
              <ProvenanceBadge
                provenance={evaluare.provenienta || "estimat"}
                detail="Model ANEVAR GEV 630"
              />
            </div>
            <p className="section-sub">
              Analiză pe proprietăți comparabile din aceeași arie, cu grilă de ajustări pe fiecare
              element de comparație.
              {evaluare.fiabilitate && (
                <>
                  {' '}
                  Fiabilitatea concluziei: <strong>{evaluare.fiabilitate}</strong>.
                </>
              )}
            </p>
          </div>
        </div>

        <div
          className={`pill flex-shrink-0 px-3 py-1.5 ${
            overpriced
              ? 'border-rose-200 bg-rose-50 text-rose-700'
              : 'border-emerald-200 bg-emerald-50 text-emerald-700'
          }`}
        >
          {overpriced ? <TrendingUp className="h-4 w-4" /> : <TrendingDown className="h-4 w-4" />}
          {overpriced ? 'Preț peste valoarea estimată' : 'Preț sub valoarea estimată'} (
          {percent(delta, { signed: true })})
        </div>
      </div>

      {/* Price gauge */}
      <div className="mx-auto my-8 max-w-3xl">
        <div className="mb-2 flex items-end justify-between gap-2 text-[11px] font-semibold text-slate-500">
          <span>Minim piață<br />{eur(min)}</span>
          <span className="text-center text-sky-700">
            Valoare justă estimată
            <br />
            <span className="text-sm font-extrabold">{eur(marketValue)}</span>
          </span>
          <span className="text-right">Maxim piață<br />{eur(max)}</span>
        </div>

        <div className="relative h-4 w-full rounded-full bg-gradient-to-r from-emerald-200 via-sky-200 to-amber-200">
          <div
            className="absolute -top-1 bottom-[-4px] z-10 w-0.5 bg-sky-600"
            style={{ left: `${fairPosition}%` }}
          />
          <div
            className="absolute -top-2.5 z-20 -ml-4 flex h-9 w-8 flex-col items-center"
            style={{ left: `${askedPosition}%` }}
            title={`Preț solicitat: ${eur(pretTotal)}`}
          >
            <span className="flex h-6 w-6 items-center justify-center rounded-full border-[3px] border-indigo-600 bg-white shadow-card">
              <span className="h-1.5 w-1.5 rounded-full bg-indigo-600" />
            </span>
            <span className="mt-0.5 whitespace-nowrap text-[10px] font-bold text-indigo-700">
              cerut
            </span>
          </div>
        </div>

        {evaluare.verdict_piata && (
          <p className="mt-6 text-center text-xs font-medium text-slate-600">
            {evaluare.verdict_piata}
          </p>
        )}
      </div>

      {/* Unit figures */}
      <div className="mb-6 grid grid-cols-1 gap-3 sm:grid-cols-3">
        <div className="stat">
          <div className="label">Preț / mp solicitat</div>
          <div className="stat-value">{eurPerSqm(askedPerSqm)}</div>
          <div className="stat-note">calculat pe {sqm(suprafata)} utili</div>
        </div>
        <div className="stat border-sky-200 bg-sky-50/70">
          <div className="label text-sky-700">Preț / mp estimat</div>
          <div className="stat-value text-sky-700">{eurPerSqm(estimatedPerSqm)}</div>
          <div className="stat-note">valoare unitară corectată, GEV 630</div>
        </div>
        <div className="stat border-emerald-200 bg-emerald-50/70">
          <div className="label text-emerald-700">Potențial de negociere</div>
          <div className="stat-value text-emerald-700">~{eur(margin)}</div>
          <div className="stat-note">levier argumentabil pentru cumpărător</div>
        </div>
      </div>

      {evaluare.motiv_fiabilitate && (
        <p className="mb-6 flex items-start gap-2 rounded-xl border border-slate-200 bg-slate-50/70 p-3 text-xs leading-relaxed text-slate-600">
          <Info className="mt-px h-3.5 w-3.5 flex-shrink-0 text-slate-400" />
          {evaluare.motiv_fiabilitate}
        </p>
      )}

      {/* Comparables + adjustment grid */}
      {comparables.length > 0 && (
        <div>
          <div className="label mb-2">
            Proprietăți comparabile reținute ({comparables.length})
          </div>
          <div className="overflow-x-auto">
            <table className="data-table min-w-[720px]">
              <thead>
                <tr>
                  <th>Adresă / complex</th>
                  <th>Preț</th>
                  <th>Suprafață</th>
                  <th>Preț / mp</th>
                  <th>Distanță</th>
                  <th>Ajustare netă</th>
                  <th>Valoare corectată</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {comparables.map((comparable, index) => {
                  const isOpen = openComparable === index;
                  const netAdjustment =
                    comparable.ajustare_neta_procent ?? comparable.ajustare_totala_procent;
                  const grid = comparable.ajustari || [];
                  return (
                    <React.Fragment key={comparable.id || comparable.adresa || index}>
                      <tr>
                        <td className="font-semibold text-slate-900">
                          {comparable.url ? (
                            <a
                              href={comparable.url}
                              target="_blank"
                              rel="noopener noreferrer"
                              className="inline-flex items-center gap-1 text-sky-700 hover:text-sky-900 hover:underline"
                            >
                              {comparable.adresa || comparable.id}
                              <ExternalLink className="h-3 w-3 flex-shrink-0" />
                            </a>
                          ) : (
                            comparable.adresa || comparable.id
                          )}
                          {comparable.id && (
                            <span className="block text-[11px] font-normal text-slate-400">
                              anunț {comparable.id}
                            </span>
                          )}
                          {comparable.data_tranzactiei && (
                            <span className="block text-[11px] font-normal text-slate-500">
                              tranzacționat {comparable.data_tranzactiei}
                            </span>
                          )}
                        </td>
                        <td className="font-semibold tabular-nums">
                          {eur(comparable.pret_total || comparable.pret)}
                        </td>
                        <td className="tabular-nums">
                          {sqm(comparable.suprafata_utila || comparable.suprafata)}
                        </td>
                        <td className="tabular-nums">
                          {eurPerSqm(comparable.pret_mp || comparable.pret_mp_eur)}
                        </td>
                        <td className="tabular-nums">
                          {comparable.distanta_km != null ? (
                            `${num(comparable.distanta_km, 2)} km`
                          ) : (
                            <span className="text-slate-400">nepublicat</span>
                          )}
                        </td>
                        <td
                          className={`font-semibold tabular-nums ${
                            (netAdjustment ?? 0) >= 0 ? 'text-emerald-700' : 'text-rose-700'
                          }`}
                        >
                          {netAdjustment != null
                            ? percent(netAdjustment, { signed: true })
                            : comparable.ponderi_ajustare || '—'}
                        </td>
                        <td className="font-bold tabular-nums text-sky-700">
                          {comparable.valoare_corectata_eur_mp
                            ? eurPerSqm(comparable.valoare_corectata_eur_mp)
                            : '—'}
                        </td>
                        <td className="text-right">
                          {grid.length > 0 && (
                            <button
                              type="button"
                              onClick={() => setOpenComparable(isOpen ? null : index)}
                              className="inline-flex items-center gap-1 text-[11px] font-semibold text-sky-700 hover:text-sky-900"
                            >
                              Grilă
                              {isOpen ? (
                                <ChevronUp className="h-3.5 w-3.5" />
                              ) : (
                                <ChevronDown className="h-3.5 w-3.5" />
                              )}
                            </button>
                          )}
                        </td>
                      </tr>
                      {isOpen && grid.length > 0 && (
                        <tr>
                          <td colSpan={8} className="bg-slate-50/80 p-0">
                            <div className="p-4">
                              <div className="label mb-2">
                                Grila de ajustare — elemente de comparație
                              </div>
                              <div className="grid grid-cols-1 gap-x-6 gap-y-1 sm:grid-cols-2">
                                {grid.map((row) => (
                                  <div
                                    key={row.element}
                                    className="flex items-center justify-between gap-3 border-b border-slate-200/70 py-1 text-xs"
                                  >
                                    <span className="text-slate-600">{row.element}</span>
                                    <span
                                      className={`font-semibold tabular-nums ${
                                        row.procent > 0
                                          ? 'text-emerald-700'
                                          : row.procent < 0
                                            ? 'text-rose-700'
                                            : 'text-slate-400'
                                      }`}
                                    >
                                      {percent(row.procent, { signed: true })}
                                    </span>
                                  </div>
                                ))}
                              </div>
                              {comparable.ajustare_bruta_procent != null && (
                                <p className="mt-3 text-[11px] text-slate-500">
                                  Ajustare brută totală{' '}
                                  <strong>{percent(comparable.ajustare_bruta_procent)}</strong> —
                                  cu cât este mai mică, cu atât comparabilul este mai apropiat de
                                  proprietatea evaluată.
                                </p>
                              )}
                            </div>
                          </td>
                        </tr>
                      )}
                    </React.Fragment>
                  );
                })}
              </tbody>
            </table>
          </div>
          <p className="mt-2 flex items-start gap-1.5 text-[11px] text-slate-400">
            <Scale className="mt-px h-3.5 w-3.5 flex-shrink-0" />
            Ajustările se aplică asupra comparabilului, nu asupra proprietății evaluate: un „+1,5%
            etaj superior” înseamnă că respectivul comparabil ar valora cu 1,5% mai mult dacă ar
            avea etajul proprietății analizate.
          </p>
        </div>
      )}
    </section>
  );
}
