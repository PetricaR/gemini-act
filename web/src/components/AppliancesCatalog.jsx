import React from 'react';
import { ArrowUpRight, ShoppingBag } from 'lucide-react';
import { eur, ron } from '../lib/format.js';

/**
 * The appliance package, recognised from the listing photos and priced twice:
 * what it cost new, and what it is worth today.
 *
 * The gap between those two is a real number in the negotiation — a kitchen
 * "fully equipped, Bosch" is worth what a buyer would pay for four-year-old
 * Bosch, not what the developer paid for it.
 */
export default function AppliancesCatalog({ audit }) {
  if (!audit) return null;

  const appliances = audit.electrocasnice || [];
  const financial = audit.sumar_financiar || {};

  const newEur = audit.total_valoare_nou_eur ?? financial.total_valoare_nou_electrocasnice_eur ?? 0;
  const currentEur =
    audit.total_valoare_actuala_eur ?? financial.total_valoare_actuala_electrocasnice_eur ?? 0;
  const currentRon = audit.total_valoare_actuala_ron ?? currentEur * 5;
  const depreciation = newEur > 0 ? Math.round(((newEur - currentEur) / newEur) * 100) : null;

  const tierClass = (tier) => {
    const value = String(tier || '').toLowerCase();
    if (value.includes('ultra') || value.includes('lux'))
      return 'bg-purple-50 text-purple-700 border-purple-200';
    if (value.includes('prem')) return 'bg-sky-50 text-sky-700 border-sky-200';
    return 'bg-slate-50 text-slate-600 border-slate-200';
  };

  return (
    <section id="dotari" className="card card-pad mb-6">
      <div className="card-head">
        <div className="flex items-start gap-3">
          <div className="icon-tile border-sky-200 bg-sky-50 text-sky-600">
            <ShoppingBag className="h-5 w-5" />
          </div>
          <div>
            <h3 className="section-title">Electrocasnice &amp; dotări incluse în preț</h3>
            <p className="section-sub">
              Brandul și seria sunt recunoscute din fotografii, iar valoarea este estimată față de
              prețurile curente din retailul online.
            </p>
          </div>
        </div>

        <div className="flex-shrink-0 rounded-xl border border-emerald-200 bg-emerald-50/70 px-4 py-2.5 text-right">
          <div className="label text-emerald-700">Valoare actuală pachet</div>
          <div className="text-lg font-extrabold text-emerald-700 tabular-nums">
            ~{eur(currentEur)}
          </div>
          <div className="text-[11px] text-slate-500">
            {ron(currentRon)} · nou ~{eur(newEur)}
            {depreciation != null ? ` (−${depreciation}%)` : ''}
          </div>
        </div>
      </div>

      {appliances.length === 0 ? (
        <div className="rounded-xl border border-slate-200 bg-slate-50/70 p-6 text-center text-sm text-slate-600">
          Nu au fost detectate electrocasnice — proprietatea pare nemobilată sau fotografiile nu le
          arată.
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
          {appliances.map((item, index) => {
            const name = item.aparat || 'Electrocasnic';
            const brand = item.brand_detectat || 'Generic';
            const series = item.model_sau_serie || item.serie || item.gama_brand || '';
            const priceNew = item.pret_nou_estimat_eur ?? item.pret_estimat_nou_eur ?? 0;
            const priceNow = item.valoare_actuala_eur ?? item.valoare_piata_actuala_eur ?? 0;
            const query = encodeURIComponent(`${brand} ${series}`.trim());

            const shops = [
              {
                name: 'eMAG',
                url: item.cautare_emag || item.link_emag || `https://www.emag.ro/search/${query}`,
                className: 'bg-blue-50 text-blue-700 border-blue-200 hover:bg-blue-100',
              },
              {
                name: 'Altex',
                url: item.cautare_altex || item.link_altex || `https://altex.ro/cauta/?q=${query}`,
                className: 'bg-amber-50 text-amber-700 border-amber-200 hover:bg-amber-100',
              },
              {
                name: 'Google',
                url:
                  item.cautare_google ||
                  item.link_google ||
                  `https://www.google.com/search?q=${query}+pret+romania`,
                className: 'bg-slate-50 text-slate-600 border-slate-200 hover:bg-slate-100',
              },
            ];

            return (
              <div
                key={`${name}-${index}`}
                className="flex flex-col justify-between rounded-xl border border-slate-200 p-4
                           transition-colors hover:border-slate-300"
              >
                <div>
                  <div className="mb-2 flex items-center justify-between gap-2">
                    <span className="pill border-slate-200 bg-slate-50 text-slate-500">
                      {item.camera || 'Locuință'}
                    </span>
                    <span className={`pill ${tierClass(item.clasa_pret)}`}>
                      {item.clasa_pret || 'Standard'}
                    </span>
                  </div>

                  <h4 className="text-sm font-bold tracking-tight text-slate-900">{name}</h4>
                  <div className="mt-0.5 text-xs font-semibold text-sky-700">
                    {brand}
                    {series && <span className="font-normal text-slate-500"> · {series}</span>}
                  </div>

                  {item.stare && (
                    <p className="mt-2 text-[11px] text-slate-500">
                      <span className="font-medium text-slate-600">Stare:</span> {item.stare}
                    </p>
                  )}
                </div>

                <div className="mt-4 border-t border-slate-100 pt-3">
                  <div className="mb-3 flex items-center justify-between text-xs">
                    <div>
                      <span className="label block">Preț nou</span>
                      <span className="font-bold text-slate-600 line-through tabular-nums">
                        ~{eur(priceNew)}
                      </span>
                    </div>
                    <div className="text-right">
                      <span className="label block">Valoare actuală</span>
                      <span className="font-extrabold text-emerald-700 tabular-nums">
                        ~{eur(priceNow)}
                      </span>
                    </div>
                  </div>

                  <div className="flex flex-wrap items-center gap-1.5 border-t border-slate-100 pt-2">
                    <span className="label mr-1">Prețuri live</span>
                    {shops.map((shop) => (
                      <a
                        key={shop.name}
                        href={shop.url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className={`inline-flex items-center gap-1 rounded border px-2 py-1 text-[10px]
                                    font-semibold transition-colors ${shop.className}`}
                      >
                        {shop.name}
                        <ArrowUpRight className="h-2.5 w-2.5" />
                      </a>
                    ))}
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </section>
  );
}
