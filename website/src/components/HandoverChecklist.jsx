import React from 'react';
import { CheckSquare, ClipboardCheck } from 'lucide-react';

const DEFAULT_ITEMS = [
  'Verificare Carte Tehnică a Construcției (disponibilă la asociație / dezvoltator)',
  'Proces verbal de recepție la terminarea lucrărilor (Legea 10/1995)',
  'Testare presiune apă și verificare termică a circuitelor de încălzire',
  'Certificat de performanță energetică, obligatoriu la autentificare',
  'Garanții scrise pentru tâmplărie și echipamentele termice',
  'Extras de carte funciară actualizat, fără sarcini',
];

/**
 * Keys the pipeline emits, spelled the way a Romanian reader expects them.
 * De-slugging `conformitate_carte_tehnica` mechanically loses every diacritic,
 * which looks like a typo in a document that is otherwise carefully written.
 */
const KEY_LABELS = {
  conformitate_carte_tehnica: 'Conformitate carte tehnică',
  garantie_legala_structura: 'Garanție legală structură',
  garantie_finisaje_echipamente: 'Garanție finisaje și echipamente',
  cadastru_si_intabulare: 'Cadastru și intabulare',
  certificat_energetic: 'Certificat energetic',
  proces_verbal_receptie: 'Proces verbal de recepție',
  extras_carte_funciara: 'Extras de carte funciară',
};

/**
 * The list a buyer takes to the viewing.
 *
 * Accepts either a flat list of actions or the keyed dictionary the pipeline
 * sometimes produces (`{cadastru_si_intabulare: "Intabulat individual…"}`) —
 * both shapes exist upstream and both are legitimate.
 */
export default function HandoverChecklist({ checklist }) {
  const isDictionary =
    checklist && !Array.isArray(checklist) && typeof checklist === 'object';

  const entries = isDictionary
    ? Object.entries(checklist).map(([key, value]) => ({
        label:
          KEY_LABELS[key] || key.replace(/_/g, ' ').replace(/^./, (char) => char.toUpperCase()),
        value,
      }))
    : (Array.isArray(checklist) && checklist.length ? checklist : DEFAULT_ITEMS).map((item) => ({
        label: item,
        value: null,
      }));

  return (
    <section id="checklist" className="card card-pad mb-6">
      <div className="card-head">
        <div className="flex items-start gap-3">
          <div className="icon-tile border-teal-200 bg-teal-50 text-teal-600">
            <ClipboardCheck className="h-5 w-5" />
          </div>
          <div>
            <h3 className="section-title">Checklist la vizionare și la semnarea contractului</h3>
            <p className="section-sub">
              Documentele și verificările tehnice care protejează cumpărătorul — de bifat înainte de
              plata avansului.
            </p>
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
        {entries.map((entry) => (
          <div
            key={entry.label}
            className="flex items-start gap-3 rounded-xl border border-slate-200 bg-slate-50/60 p-3.5"
          >
            <CheckSquare className="mt-0.5 h-4 w-4 flex-shrink-0 text-teal-600" />
            <div className="min-w-0">
              <div className="text-xs font-semibold leading-relaxed text-slate-800">
                {entry.label}
              </div>
              {entry.value && (
                <div className="mt-0.5 text-[11px] leading-relaxed text-slate-500">{entry.value}</div>
              )}
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}
