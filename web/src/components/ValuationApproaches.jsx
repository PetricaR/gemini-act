import React from 'react';
import { Banknote, Hammer, LineChart, Scale } from 'lucide-react';
import { eur, num, percent } from '../lib/format.js';

/**
 * The two approaches that cross-check the comparison one, plus how the three
 * were weighted and how much the answer moves when the assumptions do.
 *
 * A single number with no sensitivity band invites false confidence; showing
 * that a 0,2pp move in the cap rate is worth ~24.000 € is what tells a buyer
 * how hard to hold the line.
 */
export default function ValuationApproaches({ evaluare }) {
  const income = evaluare?.abordare_venit;
  const cost = evaluare?.abordare_cost;
  const reconciliation = evaluare?.reconciliere;
  const sensitivity = evaluare?.senzitivitate || [];

  if (!income && !cost && !reconciliation && sensitivity.length === 0) return null;

  const worstDelta = sensitivity.length
    ? Math.min(...sensitivity.map((row) => row.delta_procent ?? 0))
    : null;

  return (
    <section id="abordari" className="card card-pad mb-6">
      <div className="card-head">
        <div className="flex items-start gap-3">
          <div className="icon-tile border-indigo-200 bg-indigo-50 text-indigo-600">
            <Scale className="h-5 w-5" />
          </div>
          <div>
            <h3 className="section-title">Abordarea prin venit, prin cost și reconcilierea lor</h3>
            <p className="section-sub">
              Verificări independente ale valorii obținute prin comparație, cu ponderile efectiv
              folosite în concluzie și o analiză de senzitivitate pe ipotezele cheie.
            </p>
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        {income && (
          <div className="rounded-xl border border-slate-200 p-4">
            <div className="mb-3 flex items-center gap-2">
              <Banknote className="h-4 w-4 text-emerald-600" />
              <span className="text-sm font-bold text-slate-900">
                Abordarea prin venit (GEV 630 §59–71)
              </span>
            </div>
            <dl className="grid grid-cols-2 gap-x-4 gap-y-2 text-xs">
              <Row label="Chirie lunară estimată" value={eur(income.chirie_lunara_estimata_eur)} />
              <Row
                label="Chirie unitară"
                value={income.chirie_mp_eur ? `${num(income.chirie_mp_eur, 1)} €/mp` : '—'}
              />
              <Row label="Grad de neocupare" value={percent(income.grad_neocupare_procent)} />
              <Row
                label="Cheltuieli operaționale"
                value={percent(income.cheltuieli_operationale_procent)}
              />
              <Row label="Venit net anual" value={eur(income.venit_net_anual_eur)} />
              <Row label="Rată de capitalizare" value={percent(income.rata_capitalizare_procent)} />
              <Row label="Randament brut" value={percent(income.randament_brut_procent, { decimals: 2 })} />
              <Row
                label="Valoare rezultată"
                value={eur(income.valoare_prin_venit_eur)}
                emphasis="text-emerald-700"
              />
            </dl>
            {income.comentariu && (
              <p className="mt-3 border-t border-slate-100 pt-3 text-[11px] leading-relaxed text-slate-500">
                {income.comentariu}
              </p>
            )}
          </div>
        )}

        {cost && (
          <div className="rounded-xl border border-slate-200 p-4">
            <div className="mb-3 flex items-center gap-2">
              <Hammer className="h-4 w-4 text-amber-600" />
              <span className="text-sm font-bold text-slate-900">
                Abordarea prin cost (GEV 630 §72–75)
              </span>
            </div>
            <dl className="grid grid-cols-2 gap-x-4 gap-y-2 text-xs">
              <Row label="Valoare teren alocată" value={eur(cost.valoare_teren_alocata_eur)} />
              <Row label="Cost de reconstrucție" value={eur(cost.cost_reconstructie_nou_eur)} />
              <Row label="Depreciere fizică" value={percent(cost.deprecierea_fizica_procent)} />
              <Row
                label="Depreciere funcțională"
                value={percent(cost.deprecierea_functionala_procent)}
              />
              <Row
                label="Valoare rezultată"
                value={eur(cost.valoare_prin_cost_eur)}
                emphasis="text-amber-700"
              />
            </dl>
            {cost.comentariu && (
              <p className="mt-3 border-t border-slate-100 pt-3 text-[11px] leading-relaxed text-slate-500">
                {cost.comentariu}
              </p>
            )}
          </div>
        )}
      </div>

      {reconciliation && (
        <div className="mt-4 rounded-xl border border-slate-200 bg-slate-50/70 p-4">
          <div className="label mb-3">Reconcilierea valorilor</div>
          <div className="mb-3 flex h-3 w-full overflow-hidden rounded-full">
            <Weight
              value={reconciliation.pondere_comparatie_procent}
              className="bg-sky-500"
              label="Comparație"
            />
            <Weight
              value={reconciliation.pondere_venit_procent}
              className="bg-emerald-500"
              label="Venit"
            />
            <Weight
              value={reconciliation.pondere_cost_procent}
              className="bg-amber-500"
              label="Cost"
            />
          </div>
          <div className="mb-3 flex flex-wrap gap-x-5 gap-y-1 text-[11px] font-semibold text-slate-600">
            <Legend className="bg-sky-500" label="Comparație" value={reconciliation.pondere_comparatie_procent} />
            <Legend className="bg-emerald-500" label="Venit" value={reconciliation.pondere_venit_procent} />
            <Legend className="bg-amber-500" label="Cost" value={reconciliation.pondere_cost_procent} />
          </div>
          {reconciliation.concluzie && (
            <p className="text-xs leading-relaxed text-slate-600">{reconciliation.concluzie}</p>
          )}
        </div>
      )}

      {sensitivity.length > 0 && (
        <div className="mt-4">
          <div className="mb-2 flex items-center gap-2">
            <LineChart className="h-4 w-4 text-slate-400" />
            <span className="label">Analiză de senzitivitate</span>
          </div>
          <div className="space-y-2">
            {sensitivity.map((row) => {
              const delta = row.delta_procent ?? 0;
              const isBase = Math.abs(delta) < 0.05;
              // Bars are scaled against the largest downside so the base case
              // sits mid-track and the spread is visible at a glance.
              const width = Math.min(Math.abs(delta) * 8 + 4, 48);
              return (
                // On a phone the scenario label takes the full row and the bar
                // sits under it; side by side, a 224px label plus a bar plus two
                // figures cannot fit 390px without overflowing the page.
                <div
                  key={row.scenariu}
                  className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs sm:flex-nowrap"
                >
                  <span className="w-full flex-shrink-0 text-slate-600 sm:w-56 sm:truncate">
                    {row.scenariu}
                  </span>
                  <span className="relative flex h-5 min-w-[80px] flex-1 items-center">
                    <span className="absolute left-1/2 h-full w-px bg-slate-200" />
                    <span
                      className={`absolute h-2.5 rounded ${
                        isBase ? 'bg-slate-400' : delta > 0 ? 'bg-emerald-500' : 'bg-rose-500'
                      }`}
                      style={{
                        width: `${width}%`,
                        left: delta >= 0 ? '50%' : `${50 - width}%`,
                      }}
                    />
                  </span>
                  <span className="w-20 flex-shrink-0 text-right font-semibold tabular-nums text-slate-800 sm:w-24">
                    {eur(row.valoare_eur)}
                  </span>
                  <span
                    className={`w-14 flex-shrink-0 text-right font-semibold tabular-nums sm:w-16 ${
                      isBase ? 'text-slate-400' : delta > 0 ? 'text-emerald-700' : 'text-rose-700'
                    }`}
                  >
                    {percent(delta, { signed: true })}
                  </span>
                </div>
              );
            })}
          </div>
          {worstDelta != null && worstDelta < 0 && (
            <p className="mt-2 text-[11px] text-slate-500">
              În cel mai defavorabil scenariu modelat, valoarea scade cu {percent(Math.abs(worstDelta))} față
              de estimarea centrală — acesta este intervalul în care o ofertă rămâne rezonabilă.
            </p>
          )}
        </div>
      )}
    </section>
  );
}

function Row({ label, value, emphasis }) {
  return (
    <>
      <dt className="text-slate-500">{label}</dt>
      <dd className={`text-right font-semibold tabular-nums ${emphasis || 'text-slate-800'}`}>
        {value}
      </dd>
    </>
  );
}

function Weight({ value, className, label }) {
  if (!value) return null;
  return <span className={className} style={{ width: `${value}%` }} title={`${label}: ${value}%`} />;
}

function Legend({ className, label, value }) {
  if (!value) return null;
  return (
    <span className="inline-flex items-center gap-1.5">
      <span className={`h-2 w-2 rounded-full ${className}`} />
      {label} {percent(value, { decimals: 0 })}
    </span>
  );
}
