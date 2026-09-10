import React from 'react';
import { Award, Building2, Leaf, ShieldCheck } from 'lucide-react';
import { num, percent, ron, scoreTone } from '../lib/format.js';

/**
 * Who built it, and whether they are still solvent.
 *
 * For a flat bought off-plan or still inside its structural warranty, the
 * developer's balance sheet *is* part of the property's risk: a guarantee from
 * a single-purpose vehicle that dissolves after handover is worth nothing.
 */
export default function DeveloperAudit({ targetare, specs }) {
  if (!targetare && !specs) return null;

  const company = targetare?.denumire || specs?.dezvoltator || '—';
  const cui = targetare?.cui;
  const constructor = specs?.constructor;
  const rating = targetare?.scor_bonitate;
  const tone = scoreTone(rating);

  const financials = [
    { label: 'Cifră de afaceri', value: targetare?.cifra_afaceri_ron, tone: 'text-slate-900' },
    { label: 'Profit net', value: targetare?.profit_net_ron, tone: 'text-emerald-700' },
    { label: 'Datorii totale', value: targetare?.datorii_totale_ron, tone: 'text-slate-700' },
    { label: 'Capitaluri proprii', value: targetare?.capitaluri_proprii_ron, tone: 'text-slate-900' },
  ].filter((row) => typeof row.value === 'number');

  const specRows = [
    { label: 'Regim de înălțime', value: specs?.regim_inaltime },
    { label: 'Structură de rezistență', value: specs?.structura_rezistenta },
    { label: 'Închideri și pereți', value: specs?.inchideri_pereti },
    { label: 'Termen de finalizare', value: specs?.termen_finalizare },
  ].filter((row) => row.value);

  return (
    <section id="dezvoltator" className="card card-pad mb-6">
      <div className="card-head">
        <div className="flex items-start gap-3">
          <div className="icon-tile border-indigo-200 bg-indigo-50 text-indigo-600">
            <Building2 className="h-5 w-5" />
          </div>
          <div>
            <h3 className="section-title">Due diligence dezvoltator &amp; constructor</h3>
            <p className="section-sub">
              Bonitate financiară, grad de îndatorare și risc de insolvență, din datele publice ale
              firmei — plus specificațiile tehnice ale construcției.
            </p>
          </div>
        </div>

        {typeof rating === 'number' && (
          <div className={`flex-shrink-0 rounded-xl border px-4 py-2.5 text-right ${tone.bg} ${tone.border}`}>
            <div className="label">Scor bonitate</div>
            <div className={`flex items-center justify-end gap-1.5 text-lg font-extrabold ${tone.text}`}>
              <Award className="h-4 w-4" />
              <span className="tabular-nums">{num(rating, 1)}</span>
              <span className="text-xs font-semibold text-slate-500">/ 10</span>
            </div>
            {targetare?.calificativ_risc && (
              <div className="mt-0.5 max-w-[190px] text-[11px] text-slate-500">
                {targetare.calificativ_risc}
              </div>
            )}
          </div>
        )}
      </div>

      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        <div className="rounded-xl border border-slate-200 p-4">
          <div className="label mb-2">Identificarea companiei</div>
          <div className="text-base font-bold text-slate-900">{company}</div>
          <dl className="mt-2 space-y-1 text-xs">
            {cui && <InfoRow label="CUI" value={cui} />}
            {targetare?.an_infiintare && (
              <InfoRow label="An înființare" value={targetare.an_infiintare} />
            )}
            {targetare?.stare && <InfoRow label="Stare" value={targetare.stare} />}
            {constructor && <InfoRow label="Constructor" value={constructor} />}
            {typeof targetare?.numar_angajati === 'number' && (
              <InfoRow label="Angajați" value={`${targetare.numar_angajati} persoane`} />
            )}
            {typeof targetare?.grad_indatorare === 'number' && (
              <InfoRow
                label="Grad de îndatorare"
                value={percent(targetare.grad_indatorare * 100, { decimals: 0 })}
              />
            )}
          </dl>

          {targetare?.alerta_spv && (
            <div className="mt-4 flex items-start gap-2 rounded-lg border border-emerald-200 bg-emerald-50/70 p-3 text-xs text-emerald-800">
              <ShieldCheck className="mt-0.5 h-4 w-4 flex-shrink-0 text-emerald-600" />
              <span>
                <strong className="font-bold">Analiză SPV:</strong> {targetare.alerta_spv}
              </span>
            </div>
          )}
        </div>

        <div className="rounded-xl border border-slate-200 p-4">
          <div className="label mb-3">Indicatori financiari (ultimul an fiscal)</div>
          {financials.length > 0 ? (
            <div className="grid grid-cols-2 gap-3">
              {financials.map((row) => (
                <div key={row.label}>
                  <span className="block text-[11px] text-slate-500">{row.label}</span>
                  <span className={`text-sm font-extrabold tabular-nums ${row.tone}`}>
                    {ron(row.value, { compact: true })}
                  </span>
                </div>
              ))}
            </div>
          ) : (
            <p className="text-xs text-slate-500">
              Nu au fost găsite date financiare publice pentru această firmă.
            </p>
          )}
        </div>
      </div>

      {(specRows.length > 0 || specs?.certificare_verde) && (
        <div className="mt-4 border-t border-slate-200 pt-4">
          <div className="label mb-3">Specificații structurale &amp; certificări</div>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {specRows.map((row) => (
              <div key={row.label} className="rounded-xl border border-slate-200 bg-slate-50/60 p-3">
                <span className="label block">{row.label}</span>
                <span className="mt-0.5 block text-xs font-medium text-slate-700">{row.value}</span>
              </div>
            ))}
            {specs?.certificare_verde && (
              <div className="rounded-xl border border-emerald-200 bg-emerald-50/60 p-3">
                <span className="label block text-emerald-700">Eficiență &amp; mediu</span>
                <span className="mt-0.5 flex items-start gap-1.5 text-xs font-medium text-emerald-800">
                  <Leaf className="mt-px h-3.5 w-3.5 flex-shrink-0" />
                  {specs.certificare_verde}
                </span>
              </div>
            )}
          </div>
        </div>
      )}
    </section>
  );
}

function InfoRow({ label, value }) {
  return (
    <div className="flex items-center justify-between gap-3 border-b border-slate-100 py-1">
      <dt className="text-slate-500">{label}</dt>
      <dd className="text-right font-semibold text-slate-800">{value}</dd>
    </div>
  );
}
