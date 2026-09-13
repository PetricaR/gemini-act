import React, { useState } from 'react';
import {
  AlertTriangle,
  ClipboardCheck,
  Copy,
  Handshake,
  ListChecks,
  TrendingDown,
  UserSearch,
  Wallet,
} from 'lucide-react';
import { eur } from '../lib/format.js';
import ProvenanceBadge from './ProvenanceBadge.jsx';
import UnavailableBlock from './UnavailableBlock.jsx';

/**
 * The offer ladder and everything that argues it.
 *
 * The valuation sections answer what the flat is worth. This one answers what
 * to offer for it, which is a different question — so it is rendered as its own
 * chapter and carries its own provenance badge: these are market conventions,
 * not measurements of this property, and the badge has to say so.
 */

const LADDER_ROWS = [
  ['pret_listat_eur', 'Preț listat', 'Ancora publică a vânzătorului', 'neutral'],
  ['valoare_estimata_eur', 'Valoare tehnică estimată', 'Rezultatul grilei de comparabile', 'neutral'],
  ['oferta_initiala_eur', 'Ofertă inițială', 'Punctul de ancorare, transmis în scris', 'open'],
  ['pret_tinta_eur', 'Preț țintă', 'Punctul de echilibru al tranzacției', 'target'],
  ['pret_maxim_acceptabil_eur', 'Preț maxim acceptabil', 'Plafon justificabil', 'ceiling'],
  ['walk_away_eur', 'Prag de abandon', 'Peste acest nivel se renunță', 'walk'],
];

const TONE = {
  neutral: 'border-slate-200 bg-white',
  open: 'border-sky-200 bg-sky-50/60',
  target: 'border-emerald-200 bg-emerald-50/60',
  ceiling: 'border-amber-200 bg-amber-50/60',
  walk: 'border-rose-200 bg-rose-50/60',
};

const SCRIPT_LABELS = {
  proprietar: 'Către proprietar',
  agent: 'Către agent',
  dezvoltator: 'Către dezvoltator',
};

export default function NegotiationStrategy({ strategie, buget }) {
  const [activeScript, setActiveScript] = useState('proprietar');
  const [copied, setCopied] = useState(false);

  if (!strategie) return null;

  if (strategie.disponibil === false) {
    return (
      <section id="negociere" className="mb-6">
        <UnavailableBlock
          title="Strategie de negociere indisponibilă"
          reason={strategie.motiv}
          provenance="indisponibil"
        />
      </section>
    );
  }

  const ladder = strategie.scara || {};
  const profile = strategie.profil_vanzator || {};
  const levers = strategie.parghii || [];
  const flags = strategie.steaguri_rosii || [];
  const checks = strategie.verificari || {};
  const scripts = strategie.scripturi || {};
  const counter = ladder.contraoferta_probabila_eur || [];

  const copyScript = async () => {
    try {
      await navigator.clipboard.writeText(scripts[activeScript] || '');
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      setCopied(false);
    }
  };

  return (
    <>
      <section id="negociere" className="card card-pad mb-6">
        <div className="card-head">
          <div className="flex items-start gap-3">
            <div className="icon-tile border-indigo-200 bg-indigo-50 text-indigo-600">
              <Handshake className="h-5 w-5" />
            </div>
            <div>
              <h3 className="section-title">Strategia de negociere</h3>
              <p className="section-sub">
                Cele cinci numere stabilite înainte de prima discuție cu vânzătorul. O ofertă
                improvizată la masă este cea care plătește în plus.
              </p>
            </div>
          </div>
          <ProvenanceBadge
            provenance={ladder.provenienta || 'estimat'}
            detail="Practică de piață, nu o măsurătoare a acestui imobil"
          />
        </div>

        <div className="mb-4 grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-3">
          {LADDER_ROWS.map(([key, label, role, tone]) => (
            <div key={key} className={`rounded-xl border p-3 ${TONE[tone]}`}>
              <div className="label">{label}</div>
              <div className="mt-0.5 text-lg font-extrabold tabular-nums text-slate-900">
                {eur(ladder[key])}
              </div>
              <div className="mt-0.5 text-[11px] leading-snug text-slate-500">{role}</div>
            </div>
          ))}
        </div>

        {counter.length === 2 && (
          <p className="mb-3 text-xs text-slate-600">
            <span className="font-semibold text-slate-800">Contraofertă probabilă:</span>{' '}
            {eur(counter[0])} – {eur(counter[1])}. Reacția anticipată a vânzătorului după prima
            ofertă scrisă.
          </p>
        )}

        {(ladder.concesii_descrescatoare_eur || []).length > 0 && (
          <div className="mb-3 flex flex-wrap items-center gap-2 rounded-xl border border-slate-200 bg-slate-50/70 p-3">
            <TrendingDown className="h-4 w-4 flex-shrink-0 text-slate-500" />
            <span className="text-xs font-semibold text-slate-700">Concesii descrescătoare:</span>
            {ladder.concesii_descrescatoare_eur.map((step, index) => (
              <span key={step} className="pill border-slate-200 bg-white text-slate-700">
                {index + 1}. {eur(step)}
              </span>
            ))}
            <span className="w-full text-[11px] leading-relaxed text-slate-500">
              Pași egali semnalează vânzătorului o marjă neepuizată; pașii care se micșorează
              semnalează că plafonul este real.
            </span>
          </div>
        )}

        {ladder.walk_away_limitat_de_buget && (
          <p className="mb-3 rounded-xl border border-amber-200 bg-amber-50 p-3 text-xs text-amber-900">
            Pragul de abandon este impus de bugetul consolidat, nu de valoarea imobilului.
          </p>
        )}

        {strategie.regula_decizionala && (
          <p className="rounded-xl border border-indigo-200 bg-indigo-50/60 p-4 text-sm font-semibold leading-relaxed text-indigo-900">
            {strategie.regula_decizionala}
          </p>
        )}

        <p className="mt-3 text-[11px] leading-relaxed text-slate-500">{strategie.sursa}</p>
      </section>

      {profile.profil && (
        <section id="profil-vanzator" className="card card-pad mb-6">
          <div className="card-head">
            <div className="flex items-start gap-3">
              <div className="icon-tile border-violet-200 bg-violet-50 text-violet-600">
                <UserSearch className="h-5 w-5" />
              </div>
              <div>
                <h3 className="section-title">Profilul vânzătorului</h3>
                <p className="section-sub">
                  Dedus din semnalele pe care le poartă chiar anunțul — tipul vânzătorului, timpul
                  de expunere, istoricul de preț.
                </p>
              </div>
            </div>
            <ProvenanceBadge provenance={profile.provenienta || 'estimat'} />
          </div>

          <div className="mb-3 flex flex-wrap items-center gap-2">
            <span className="pill border-violet-200 bg-violet-50 text-violet-800">
              {profile.profil}
            </span>
            {(profile.semnale_detectate || []).map((signal) => (
              <span key={signal} className="pill border-slate-200 bg-slate-50 text-slate-600">
                {signal}
              </span>
            ))}
          </div>

          <dl className="grid grid-cols-1 gap-3 lg:grid-cols-2">
            <Detail label="Ce funcționează" value={profile.tactica_eficienta} tone="emerald" />
            <Detail label="Ce nu funcționează" value={profile.erori_de_evitat} tone="rose" />
            <Detail label="Declanșator" value={profile.declansator} />
            <Detail label="Argument principal" value={profile.argument_principal} />
          </dl>
        </section>
      )}

      {levers.length > 0 && (
        <section id="parghii" className="card card-pad mb-6">
          <div className="card-head">
            <div className="flex items-start gap-3">
              <div className="icon-tile border-amber-200 bg-amber-50 text-amber-600">
                <Wallet className="h-5 w-5" />
              </div>
              <div>
                <h3 className="section-title">Pârghii tehnice de reducere</h3>
                <p className="section-sub">
                  Fiecare defect constatat, transformat într-o sumă și în fraza care o susține.
                </p>
              </div>
            </div>
          </div>
          <div className="overflow-x-auto">
            <table className="data-table min-w-[640px]">
              <thead>
                <tr>
                  <th>Problemă constatată</th>
                  <th>Deviz estimativ</th>
                  <th>Reducere justificată</th>
                  <th>Argument</th>
                </tr>
              </thead>
              <tbody>
                {levers.map((lever) => (
                  <tr key={lever.problema}>
                    <td className="font-semibold text-slate-900">{lever.problema}</td>
                    <td className="tabular-nums">
                      {eur(lever.deviz_estimativ_eur?.[0])} – {eur(lever.deviz_estimativ_eur?.[1])}
                    </td>
                    <td className="tabular-nums font-semibold text-amber-800">
                      {eur(lever.reducere_justificata_eur?.[0])} –{' '}
                      {eur(lever.reducere_justificata_eur?.[1])}
                    </td>
                    <td className="text-slate-600">{lever.argument}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

      {flags.length > 0 && (
        <section id="steaguri" className="card card-pad mb-6">
          <div className="card-head">
            <div className="flex items-start gap-3">
              <div className="icon-tile border-rose-200 bg-rose-50 text-rose-600">
                <AlertTriangle className="h-5 w-5" />
              </div>
              <div>
                <h3 className="section-title">Semnale roșii și verificări impuse</h3>
                <p className="section-sub">
                  Ce trebuie verificat înainte de ofertă, cu reducerea justificată dacă se
                  confirmă.
                </p>
              </div>
            </div>
          </div>
          <div className="space-y-3">
            {flags.map((flag) => (
              <div
                key={flag.risc}
                className={`rounded-xl border p-4 ${
                  flag.abandon_recomandat
                    ? 'border-rose-300 bg-rose-50/70'
                    : 'border-slate-200 bg-slate-50/60'
                }`}
              >
                <div className="flex flex-wrap items-center gap-2">
                  <h4 className="text-sm font-bold text-slate-900">{flag.risc}</h4>
                  {flag.reducere_justificata && (
                    <span className="pill border-amber-200 bg-amber-50 text-amber-800">
                      {flag.reducere_justificata}
                    </span>
                  )}
                </div>
                <p className="mt-1 text-xs leading-relaxed text-slate-600">{flag.descriere}</p>
                <p className="mt-2 text-xs leading-relaxed text-slate-800">
                  <span className="font-semibold">Măsură: </span>
                  {flag.mitigare}
                </p>
              </div>
            ))}
          </div>
        </section>
      )}

      {Object.keys(scripts).length > 0 && (
        <section id="scripturi" className="card card-pad mb-6">
          <div className="card-head">
            <div className="flex items-start gap-3">
              <div className="icon-tile border-sky-200 bg-sky-50 text-sky-600">
                <ClipboardCheck className="h-5 w-5" />
              </div>
              <div>
                <h3 className="section-title">Oferta scrisă, gata de trimis</h3>
                <p className="section-sub">
                  Ofertele verbale nu creează presiune. Textul de mai jos este completat cu cifrele
                  calculate mai sus — se verifică înainte de trimitere.
                </p>
              </div>
            </div>
          </div>

          <div className="mb-3 flex flex-wrap items-center gap-1.5">
            {Object.keys(scripts).map((channel) => (
              <button
                key={channel}
                type="button"
                onClick={() => setActiveScript(channel)}
                className={`rounded-lg px-3 py-1.5 text-xs font-semibold transition-colors ${
                  activeScript === channel
                    ? 'bg-slate-900 text-white'
                    : 'text-slate-500 hover:bg-slate-100 hover:text-slate-900'
                }`}
              >
                {SCRIPT_LABELS[channel] || channel}
              </button>
            ))}
            <button
              type="button"
              onClick={copyScript}
              className="no-print ml-auto flex items-center gap-1.5 rounded-lg border border-slate-200 px-3 py-1.5 text-xs font-semibold text-slate-600 hover:bg-slate-50"
            >
              <Copy className="h-3.5 w-3.5" />
              {copied ? 'Copiat' : 'Copiază'}
            </button>
          </div>

          <pre className="whitespace-pre-wrap rounded-xl border border-slate-200 bg-slate-50/70 p-4 font-sans text-xs leading-relaxed text-slate-700">
            {scripts[activeScript]}
          </pre>
        </section>
      )}

      {(checks.tehnice || checks.juridice || checks.structurale) && (
        <section id="verificari" className="card card-pad mb-6">
          <div className="card-head">
            <div className="flex items-start gap-3">
              <div className="icon-tile border-emerald-200 bg-emerald-50 text-emerald-600">
                <ListChecks className="h-5 w-5" />
              </div>
              <div>
                <h3 className="section-title">Verificări înainte de ofertă și de antecontract</h3>
                <p className="section-sub">
                  Tehnice la vizionare, juridice înainte de semnătură, structurale în funcție de
                  epoca imobilului.
                </p>
              </div>
            </div>
          </div>
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
            <ChecklistColumn title="Tehnice (la vizionare)" items={checks.tehnice} />
            <ChecklistColumn title="Juridice (pre-antecontract)" items={checks.juridice} />
            <ChecklistColumn title="Structurale" items={checks.structurale} />
          </div>
        </section>
      )}

      {buget?.disponibil && (
        <section id="buget" className="card card-pad mb-6">
          <div className="card-head">
            <div className="flex items-start gap-3">
              <div className="icon-tile border-slate-200 bg-slate-50 text-slate-600">
                <Wallet className="h-5 w-5" />
              </div>
              <div>
                <h3 className="section-title">Bugetul consolidat al proiectului</h3>
                <p className="section-sub">
                  Prețul nu este bugetul. Pragul de abandon se calculează din suma de mai jos.
                </p>
              </div>
            </div>
          </div>
          <div className="overflow-x-auto">
            <table className="data-table min-w-[560px]">
              <thead>
                <tr>
                  <th>Componentă</th>
                  <th>Interval estimat</th>
                  <th>Temei</th>
                </tr>
              </thead>
              <tbody>
                {(buget.posturi || [])
                  .filter((post) => post.minim_eur != null)
                  .map((post) => (
                    <tr key={post.componenta}>
                      <td className="font-semibold text-slate-900">{post.componenta}</td>
                      <td className="tabular-nums">
                        {post.minim_eur === post.maxim_eur
                          ? eur(post.minim_eur)
                          : `${eur(post.minim_eur)} – ${eur(post.maxim_eur)}`}
                      </td>
                      <td className="text-slate-600">{post.temei}</td>
                    </tr>
                  ))}
                <tr className="bg-slate-50 font-bold">
                  <td>Cost total consolidat</td>
                  <td className="tabular-nums">
                    {eur(buget.total_minim_eur)} – {eur(buget.total_maxim_eur)}
                  </td>
                  <td className="text-slate-600">Prețul plus tot ce urmează după semnare</td>
                </tr>
              </tbody>
            </table>
          </div>
        </section>
      )}
    </>
  );
}

function Detail({ label, value, tone }) {
  if (!value) return null;
  const border =
    tone === 'emerald'
      ? 'border-emerald-200 bg-emerald-50/50'
      : tone === 'rose'
        ? 'border-rose-200 bg-rose-50/50'
        : 'border-slate-200';
  return (
    <div className={`rounded-xl border p-3 ${border}`}>
      <dt className="label">{label}</dt>
      <dd className="mt-1 text-xs leading-relaxed text-slate-700">{value}</dd>
    </div>
  );
}

function ChecklistColumn({ title, items }) {
  if (!items || items.length === 0) return null;
  return (
    <div className="rounded-xl border border-slate-200 p-4">
      <div className="label mb-2">{title}</div>
      <ul className="space-y-1.5">
        {items.map((item) => (
          <li key={item} className="flex items-start gap-2 text-xs leading-relaxed text-slate-700">
            <span className="mt-1.5 h-1.5 w-1.5 flex-shrink-0 rounded-full bg-slate-300" />
            {item}
          </li>
        ))}
      </ul>
    </div>
  );
}
