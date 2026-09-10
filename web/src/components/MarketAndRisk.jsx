import React from 'react';
import { Activity, Clock, Leaf, ShieldAlert, Target, TrendingUp, Wallet } from 'lucide-react';
import { eur, eurPerSqm, num, percent } from '../lib/format.js';

/**
 * Market context, holding costs and the risk register.
 *
 * These are the chapters a buyer skips and then regrets: what the area actually
 * does with prices, what the flat costs to own per year on top of the mortgage,
 * and what could go wrong with a probability and a mitigation next to it.
 */
export default function MarketAndRisk({ data }) {
  const market = data?.analiza_piata;
  const risks = data?.riscuri || [];
  const holding = data?.costuri_detinere;
  const transaction = data?.costuri_tranzactionare;
  const esg = data?.esg;
  const bestUse = data?.cea_mai_buna_utilizare;

  if (!market && risks.length === 0 && !holding && !esg && !bestUse) return null;

  return (
    <>
      {(market || bestUse) && (
        <section id="piata" className="card card-pad mb-6">
          <div className="card-head">
            <div className="flex items-start gap-3">
              <div className="icon-tile border-sky-200 bg-sky-50 text-sky-600">
                <Activity className="h-5 w-5" />
              </div>
              <div>
                <h3 className="section-title">Analiza pieței și cea mai bună utilizare</h3>
                <p className="section-sub">
                  Contextul în care se face tranzacția: cât cere zona, cât de repede se vinde și ce
                  utilizare produce valoarea maximă.
                </p>
              </div>
            </div>
            {market?.zona && (
              <span className="pill flex-shrink-0 border-slate-200 bg-slate-50 text-slate-600">
                {market.zona}
              </span>
            )}
          </div>

          {market && (
            <div className="mb-4 grid grid-cols-2 gap-3 lg:grid-cols-4">
              <div className="stat">
                <div className="label">Preț mediu zonă</div>
                <div className="stat-value">{eurPerSqm(market.pret_mediu_zona_eur_mp)}</div>
              </div>
              <div className="stat">
                <div className="label">Variație anuală</div>
                <div
                  className={`stat-value flex items-center gap-1 ${
                    (market.variatie_anuala_procent ?? 0) >= 0 ? 'text-emerald-700' : 'text-rose-700'
                  }`}
                >
                  <TrendingUp className="h-4 w-4" />
                  {percent(market.variatie_anuala_procent, { signed: true })}
                </div>
              </div>
              <div className="stat">
                <div className="label">Timp mediu de expunere</div>
                <div className="stat-value flex items-center gap-1">
                  <Clock className="h-4 w-4 text-slate-400" />
                  {num(market.timp_mediu_expunere_luni, 1)} luni
                </div>
              </div>
              <div className="stat">
                <div className="label">Ofertă activă similară</div>
                <div className="stat-value">{num(market.oferta_activa_similara)} anunțuri</div>
                {market.tendinta && <div className="stat-note">{market.tendinta}</div>}
              </div>
            </div>
          )}

          {market?.comentariu && (
            <p className="rounded-xl border border-slate-200 bg-slate-50/70 p-4 text-sm leading-relaxed text-slate-700">
              {market.comentariu}
            </p>
          )}

          {bestUse && (
            <div className="mt-4 flex items-start gap-2.5 rounded-xl border border-slate-200 p-4">
              <Target className="mt-0.5 h-4 w-4 flex-shrink-0 text-indigo-600" />
              <div>
                <div className="label">Cea mai bună utilizare</div>
                <p className="mt-0.5 text-xs leading-relaxed text-slate-700">{bestUse}</p>
              </div>
            </div>
          )}
        </section>
      )}

      {(holding || transaction || esg) && (
        <section id="costuri" className="card card-pad mb-6">
          <div className="card-head">
            <div className="flex items-start gap-3">
              <div className="icon-tile border-emerald-200 bg-emerald-50 text-emerald-600">
                <Wallet className="h-5 w-5" />
              </div>
              <div>
                <h3 className="section-title">Costuri de deținere, de tranzacționare și profil ESG</h3>
                <p className="section-sub">
                  Ce se plătește după semnare: întreținere, impozit, asigurare, plus taxele
                  tranzacției și performanța energetică a clădirii.
                </p>
              </div>
            </div>
          </div>

          <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
            {holding && (
              <div className="rounded-xl border border-slate-200 p-4">
                <div className="label mb-3">Costuri anuale de deținere</div>
                <dl className="space-y-1 text-xs">
                  <CostRow label="Întreținere lunară" value={eur(holding.intretinere_lunara_eur)} />
                  <CostRow label="Fond de reparații lunar" value={eur(holding.fond_reparatii_lunar_eur)} />
                  <CostRow label="Impozit anual" value={eur(holding.impozit_anual_eur)} />
                  <CostRow label="Asigurare anuală" value={eur(holding.asigurare_anuala_eur)} />
                  <CostRow label="Total anual" value={eur(holding.total_anual_eur)} strong />
                </dl>
                {holding.comentariu && (
                  <p className="mt-3 border-t border-slate-100 pt-3 text-[11px] leading-relaxed text-slate-500">
                    {holding.comentariu}
                  </p>
                )}
              </div>
            )}

            {transaction && (
              <div className="rounded-xl border border-slate-200 p-4">
                <div className="label mb-3">Costuri de tranzacționare</div>
                <dl className="space-y-1 text-xs">
                  <CostRow
                    label="Onorariu notarial"
                    value={percent(transaction.onorariu_notarial_procent)}
                  />
                  <CostRow
                    label="Taxă de intabulare"
                    value={percent(transaction.taxa_intabulare_procent, { decimals: 2 })}
                  />
                  <CostRow
                    label="Comision agenție"
                    value={percent(transaction.comision_agentie_procent)}
                  />
                  <CostRow label="Total estimat" value={eur(transaction.total_estimat_eur)} strong />
                </dl>
              </div>
            )}

            {esg && (
              <div className="rounded-xl border border-emerald-200 bg-emerald-50/40 p-4">
                <div className="label mb-3 flex items-center gap-1.5 text-emerald-700">
                  <Leaf className="h-3.5 w-3.5" />
                  Profil ESG
                </div>
                <dl className="space-y-1 text-xs">
                  {esg.certificare && <CostRow label="Certificare" value={esg.certificare} />}
                  {esg.clasa_energetica && (
                    <CostRow label="Clasă energetică" value={esg.clasa_energetica} />
                  )}
                  {esg.consum_specific_kwh_mp_an && (
                    <CostRow
                      label="Consum specific"
                      value={`${num(esg.consum_specific_kwh_mp_an)} kWh/mp/an`}
                    />
                  )}
                </dl>
                {esg.riscuri_climatice && (
                  <p className="mt-3 border-t border-emerald-200/70 pt-3 text-[11px] leading-relaxed text-slate-600">
                    {esg.riscuri_climatice}
                  </p>
                )}
              </div>
            )}
          </div>
        </section>
      )}

      {risks.length > 0 && (
        <section id="riscuri" className="card card-pad mb-6">
          <div className="card-head">
            <div className="flex items-start gap-3">
              <div className="icon-tile border-rose-200 bg-rose-50 text-rose-600">
                <ShieldAlert className="h-5 w-5" />
              </div>
              <div>
                <h3 className="section-title">Registrul de riscuri</h3>
                <p className="section-sub">
                  Fiecare risc identificat, cu probabilitatea, impactul și acțiunea concretă care îl
                  reduce înainte de semnarea antecontractului.
                </p>
              </div>
            </div>
          </div>

          <div className="overflow-x-auto">
            <table className="data-table min-w-[640px]">
              <thead>
                <tr>
                  <th>Risc</th>
                  <th>Probabilitate</th>
                  <th>Impact</th>
                  <th>Măsură de reducere</th>
                </tr>
              </thead>
              <tbody>
                {risks.map((risk) => (
                  <tr key={risk.risc}>
                    <td className="font-semibold text-slate-900">{risk.risc}</td>
                    <td>
                      <span className={`pill ${likelihoodClass(risk.probabilitate)}`}>
                        {risk.probabilitate}
                      </span>
                    </td>
                    <td>
                      <span className={`pill ${impactClass(risk.impact)}`}>{risk.impact}</span>
                    </td>
                    <td className="text-slate-600">{risk.mitigare}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}
    </>
  );
}

function CostRow({ label, value, strong = false }) {
  return (
    <div
      className={`flex items-center justify-between gap-3 py-1 ${
        strong ? 'mt-1 border-t border-slate-200 pt-2' : 'border-b border-slate-100'
      }`}
    >
      <dt className={strong ? 'font-semibold text-slate-700' : 'text-slate-500'}>{label}</dt>
      <dd
        className={`text-right tabular-nums ${
          strong ? 'text-sm font-extrabold text-slate-900' : 'font-semibold text-slate-800'
        }`}
      >
        {value}
      </dd>
    </div>
  );
}

function likelihoodClass(value) {
  const normalised = String(value || '').toLowerCase();
  if (normalised.startsWith('cert') || normalised.includes('ridic'))
    return 'border-rose-200 bg-rose-50 text-rose-700';
  if (normalised.includes('medi')) return 'border-amber-200 bg-amber-50 text-amber-700';
  return 'border-slate-200 bg-slate-50 text-slate-600';
}

function impactClass(value) {
  const normalised = String(value || '').toLowerCase();
  if (normalised.includes('ridic') || normalised.includes('major'))
    return 'border-rose-200 bg-rose-50 text-rose-700';
  if (normalised.includes('medi')) return 'border-amber-200 bg-amber-50 text-amber-700';
  return 'border-emerald-200 bg-emerald-50 text-emerald-700';
}
