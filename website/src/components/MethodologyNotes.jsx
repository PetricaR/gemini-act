import React from 'react';
import { AlertTriangle, BookOpen, Database } from 'lucide-react';

/**
 * Terms of reference, limiting conditions and sources.
 *
 * This section exists because the report reads like a valuation and is not one:
 * it is compiled without a site inspection and without an authorised ANEVAR
 * valuer. Saying so plainly, in the document itself, is the difference between a
 * useful decision aid and a misleading one.
 */
export default function MethodologyNotes({ metodologie, ipoteze }) {
  if (!metodologie && !ipoteze?.length) return null;

  const terms = [
    { label: 'Standard aplicat', value: metodologie?.standard },
    { label: 'Tipul valorii', value: metodologie?.tip_valoare },
    { label: 'Data evaluării', value: metodologie?.data_evaluarii },
    { label: 'Moneda', value: metodologie?.moneda },
    { label: 'Client', value: metodologie?.client },
    { label: 'Utilizarea desemnată', value: metodologie?.utilizare_desemnata },
    { label: 'Utilizator desemnat', value: metodologie?.utilizator_desemnat },
  ].filter((row) => row.value);

  return (
    <section id="metodologie" className="card card-pad mb-6">
      <div className="card-head">
        <div className="flex items-start gap-3">
          <div className="icon-tile border-slate-200 bg-slate-50 text-slate-600">
            <BookOpen className="h-5 w-5" />
          </div>
          <div>
            <h3 className="section-title">Metodologie, ipoteze și limite ale analizei</h3>
            <p className="section-sub">
              Termenii de referință ai analizei și, explicit, ce nu acoperă acest document.
            </p>
          </div>
        </div>
      </div>

      {metodologie?.evaluator && (
        <div className="mb-5 flex items-start gap-2.5 rounded-xl border border-amber-300 bg-amber-50 p-4">
          <AlertTriangle className="mt-0.5 h-4 w-4 flex-shrink-0 text-amber-600" />
          <div>
            <div className="text-xs font-bold uppercase tracking-wider text-amber-800">
              Neconformitate declarată
            </div>
            <p className="mt-1 text-xs leading-relaxed text-slate-700">{metodologie.evaluator}</p>
            {metodologie.amploare && (
              <p className="mt-1.5 text-xs leading-relaxed text-slate-700">{metodologie.amploare}</p>
            )}
          </div>
        </div>
      )}

      <div className="grid grid-cols-1 gap-5 lg:grid-cols-2">
        {terms.length > 0 && (
          <div>
            <div className="label mb-2">Termenii de referință</div>
            <dl className="text-xs">
              {terms.map((row) => (
                <div
                  key={row.label}
                  className="flex items-start justify-between gap-4 border-b border-slate-100 py-1.5"
                >
                  <dt className="flex-shrink-0 text-slate-500">{row.label}</dt>
                  <dd className="text-right font-medium text-slate-800">{row.value}</dd>
                </div>
              ))}
            </dl>
          </div>
        )}

        {ipoteze?.length > 0 && (
          <div>
            <div className="label mb-2">Ipoteze și condiții limitative</div>
            <ul className="space-y-1.5">
              {ipoteze.map((item) => (
                <li key={item} className="flex items-start gap-2 text-xs leading-relaxed text-slate-600">
                  <span className="mt-1.5 h-1 w-1 flex-shrink-0 rounded-full bg-slate-400" />
                  {item}
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>

      {metodologie?.surse_date?.length > 0 && (
        <div className="mt-5 border-t border-slate-200 pt-4">
          <div className="label mb-2 flex items-center gap-1.5">
            <Database className="h-3.5 w-3.5 text-slate-400" />
            Surse de date
          </div>
          <div className="flex flex-wrap gap-1.5">
            {metodologie.surse_date.map((source) => (
              <span key={source} className="pill border-slate-200 bg-slate-50 text-slate-600">
                {source}
              </span>
            ))}
          </div>
        </div>
      )}
    </section>
  );
}
