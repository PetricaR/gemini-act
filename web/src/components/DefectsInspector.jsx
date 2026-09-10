import React, { useState } from 'react';
import {
  AlertTriangle,
  CheckCircle,
  ChevronDown,
  ChevronUp,
  ShieldAlert,
  Wallet,
  Wrench,
} from 'lucide-react';
import { eur, num, ron, scoreTone, severityTone } from '../lib/format.js';

/**
 * What the vision pass found on the seller's own photographs, priced.
 *
 * Every defect carries a remediation cost, because a defect without a number
 * next to it is an opinion; with one, it is a line in the negotiation.
 */
export default function DefectsInspector({ audit }) {
  const [expanded, setExpanded] = useState(null);
  if (!audit) return null;

  const defects = audit.defecte_identificate || audit.defecte_si_probleme || [];
  const finishes = audit.categorii_finisaje || [];
  const financial = audit.sumar_financiar || {};

  const finishScore = audit.scor_finisaje ?? audit.calitate_generala_finisaje?.scor_global;
  const finishClass = audit.clasa_finisaje ?? audit.calitate_generala_finisaje?.clasa;
  const tone = scoreTone(finishScore);

  const repairsEur =
    audit.buget_total_reparatii_eur ?? financial.total_buget_remediere_defecte_eur ?? 0;
  const repairsRon = audit.buget_total_reparatii_ron ?? repairsEur * 5;
  const leverage =
    audit.levier_negociere_recomandat_eur ??
    financial.impact_negociere_recomandat_eur ??
    Math.round(repairsEur * 2.5);

  return (
    <section id="defecte" className="card card-pad mb-6">
      <div className="card-head">
        <div className="flex items-start gap-3">
          <div className="icon-tile border-amber-200 bg-amber-50 text-amber-600">
            <ShieldAlert className="h-5 w-5" />
          </div>
          <div>
            <h3 className="section-title">Defecte vizibile &amp; calitatea finisajelor</h3>
            <p className="section-sub">
              Inspecție fotografică automată. Un viciu care nu apare în nicio fotografie publicată nu
              poate fi detectat — lista de mai jos nu înlocuiește o expertiză tehnică la fața locului.
            </p>
          </div>
        </div>

        {typeof finishScore === 'number' && (
          <div className={`flex-shrink-0 rounded-xl border px-4 py-2.5 text-right ${tone.bg} ${tone.border}`}>
            <div className="label">Calitate finisaje</div>
            <div className={`text-lg font-extrabold tabular-nums ${tone.text}`}>
              {num(finishScore, 1)}
              <span className="text-xs font-semibold text-slate-500"> / 10</span>
            </div>
            {finishClass && <div className="text-[11px] text-slate-500">Clasa {finishClass}</div>}
          </div>
        )}
      </div>

      {audit.rezumat_audit && (
        <p className="mb-5 rounded-xl border border-slate-200 bg-slate-50/70 p-4 text-sm leading-relaxed text-slate-700">
          {audit.rezumat_audit}
        </p>
      )}

      <div className="mb-6 grid grid-cols-1 gap-3 md:grid-cols-3">
        <div className="stat flex items-center justify-between">
          <div>
            <div className="label">Defecte detectate</div>
            <div className="stat-value">{defects.length} elemente</div>
          </div>
          <span className="icon-tile border-slate-200 bg-white text-amber-600">
            <AlertTriangle className="h-5 w-5" />
          </span>
        </div>

        <div className="stat flex items-center justify-between border-amber-200 bg-amber-50/70">
          <div>
            <div className="label text-amber-700">Buget de remediere</div>
            <div className="stat-value text-amber-700">~{eur(repairsEur)}</div>
            <div className="stat-note">{ron(repairsRon)}</div>
          </div>
          <span className="icon-tile border-amber-200 bg-white text-amber-600">
            <Wrench className="h-5 w-5" />
          </span>
        </div>

        <div className="stat flex items-center justify-between border-emerald-200 bg-emerald-50/70">
          <div>
            <div className="label text-emerald-700">Levier de negociere</div>
            <div className="stat-value text-emerald-700">−{eur(leverage)}</div>
            <div className="stat-note">defecte + uzura dotărilor incluse</div>
          </div>
          <span className="icon-tile border-emerald-200 bg-white text-emerald-600">
            <Wallet className="h-5 w-5" />
          </span>
        </div>
      </div>

      <div className="mb-6 space-y-2">
        <div className="label mb-2">Defecte identificate pe fotografii</div>

        {defects.length === 0 ? (
          <div className="rounded-xl border border-slate-200 bg-slate-50/70 p-6 text-center text-sm text-slate-600">
            <CheckCircle className="mx-auto mb-2 h-7 w-7 text-emerald-600" />
            Nu au fost detectate defecte aparente în fotografiile disponibile.
          </div>
        ) : (
          defects.map((defect, index) => {
            const isOpen = expanded === index;
            const element = defect.element || defect.element_afectat || 'Element interior';
            const description = defect.defect || defect.descriere_defect || '—';
            const cost = defect.cost_estimat_eur ?? defect.cost_estimat_remediere_eur ?? 0;
            const fix = defect.remediere || defect.metoda_remediere || '—';
            const severity = severityTone(defect.severitate);

            return (
              <div
                key={`${element}-${index}`}
                className="overflow-hidden rounded-xl border border-slate-200 transition-colors hover:border-slate-300"
              >
                <button
                  type="button"
                  onClick={() => setExpanded(isOpen ? null : index)}
                  className="flex w-full items-center justify-between gap-3 p-4 text-left"
                >
                  <div className="flex min-w-0 items-center gap-3">
                    <span className={`pill ${severity.bg} ${severity.text} ${severity.border}`}>
                      <AlertTriangle className="h-3 w-3" />
                      {defect.severitate || 'Minor'}
                    </span>
                    <div className="min-w-0">
                      <div className="text-sm font-bold text-slate-900">{element}</div>
                      <div className="truncate text-xs text-slate-500">{description}</div>
                    </div>
                  </div>
                  <div className="flex flex-shrink-0 items-center gap-4">
                    <div className="text-right">
                      <div className="text-xs font-extrabold text-amber-700 tabular-nums">
                        ~{eur(cost)}
                      </div>
                      <div className="text-[10px] text-slate-400">estimat reparație</div>
                    </div>
                    {isOpen ? (
                      <ChevronUp className="h-4 w-4 text-slate-400" />
                    ) : (
                      <ChevronDown className="h-4 w-4 text-slate-400" />
                    )}
                  </div>
                </button>

                {isOpen && (
                  <div className="grid grid-cols-1 gap-4 border-t border-slate-200 bg-slate-50/70 px-4 py-3 sm:grid-cols-3">
                    <div>
                      <div className="label">Descriere</div>
                      <p className="mt-0.5 text-xs text-slate-700">{description}</p>
                    </div>
                    {defect.cauza_probabila && (
                      <div>
                        <div className="label">Cauză probabilă</div>
                        <p className="mt-0.5 text-xs text-slate-700">{defect.cauza_probabila}</p>
                      </div>
                    )}
                    <div>
                      <div className="label">Metodă de remediere</div>
                      <p className="mt-0.5 text-xs font-medium text-emerald-700">{fix}</p>
                    </div>
                  </div>
                )}
              </div>
            );
          })
        )}
      </div>

      {finishes.length > 0 && (
        <div className="border-t border-slate-200 pt-5">
          <div className="label mb-3">Specificații materiale &amp; clasă de finisaje</div>
          <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
            {finishes.map((finish) => {
              const rating = finish.nota ?? finish.scor;
              const finishTone = scoreTone(rating);
              return (
                <div
                  key={finish.categorie}
                  className="rounded-xl border border-slate-200 bg-slate-50/60 p-3.5"
                >
                  <div className="mb-1 flex items-center justify-between gap-2">
                    <span className="text-xs font-bold text-slate-900">{finish.categorie}</span>
                    {rating != null && (
                      <span className={`pill ${finishTone.bg} ${finishTone.text} ${finishTone.border}`}>
                        {num(rating, 1)}/10
                      </span>
                    )}
                  </div>
                  <div className="text-xs font-medium text-slate-700">
                    {finish.calitate || finish.material_identificat}
                  </div>
                  {finish.stare_vizuala && (
                    <div className="mt-1 text-[11px] text-slate-500">{finish.stare_vizuala}</div>
                  )}
                  {finish.observatii && (
                    <div className="mt-1 text-[11px] text-slate-500">{finish.observatii}</div>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      )}
    </section>
  );
}
