import React from 'react';
import { AlertTriangle, CheckCircle2, Lightbulb, Star } from 'lucide-react';
import { num } from '../lib/format.js';

/**
 * What the people already living there say — the only source in this report
 * that describes the building after a few winters rather than on handover day.
 */
export default function ReviewsSentiment({ reviews, complexName }) {
  if (!reviews) return null;

  const rating = reviews.rating_mediu ?? reviews.rating_global;
  const count = reviews.numar_recenzii ?? reviews.total_recenzii;
  const strengths = reviews.puncte_forte || [];
  const issues = reviews.probleme_recurente || [];
  const sentiment = reviews.locatie?.analiza_sentiment;

  return (
    <section id="recenzii" className="card card-pad mb-6">
      <div className="card-head">
        <div className="flex items-start gap-3">
          <div className="icon-tile border-amber-200 bg-amber-50 text-amber-500">
            <Star className="h-5 w-5 fill-amber-400 text-amber-500" />
          </div>
          <div>
            <h3 className="section-title">Părerea rezidenților — recenzii Google Maps</h3>
            <p className="section-sub">
              Sinteză din comentariile publice ale locatarilor din {complexName || 'ansamblu'}.
            </p>
          </div>
        </div>

        {typeof rating === 'number' && (
          <div className="flex flex-shrink-0 items-center gap-2 rounded-xl border border-slate-200 bg-slate-50 px-4 py-2.5">
            <Star className="h-5 w-5 fill-amber-400 text-amber-500" />
            <span className="text-xl font-extrabold text-slate-900 tabular-nums">
              {num(rating, 1)}
            </span>
            {count ? (
              <span className="text-xs font-medium text-slate-500">din {count} recenzii</span>
            ) : null}
          </div>
        )}
      </div>

      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        {strengths.length > 0 && (
          <div className="rounded-xl border border-emerald-200 bg-emerald-50/60 p-4">
            <div className="label mb-3 text-emerald-700">Ce apreciază vecinii</div>
            <ul className="space-y-2">
              {strengths.map((item) => (
                <li key={item} className="flex items-start gap-2 text-xs leading-relaxed text-slate-700">
                  <CheckCircle2 className="mt-0.5 h-3.5 w-3.5 flex-shrink-0 text-emerald-600" />
                  {item}
                </li>
              ))}
            </ul>
          </div>
        )}

        {issues.length > 0 && (
          <div className="rounded-xl border border-amber-200 bg-amber-50/60 p-4">
            <div className="label mb-3 text-amber-700">Probleme semnalate recurent</div>
            <ul className="space-y-2">
              {issues.map((item) => (
                <li key={item} className="flex items-start gap-2 text-xs leading-relaxed text-slate-700">
                  <AlertTriangle className="mt-0.5 h-3.5 w-3.5 flex-shrink-0 text-amber-600" />
                  {item}
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>

      {sentiment?.recomandare_cumparator && (
        <div className="mt-4 flex items-start gap-2.5 rounded-xl border border-sky-200 bg-sky-50/70 p-4">
          <Lightbulb className="mt-0.5 h-4 w-4 flex-shrink-0 text-sky-600" />
          <div>
            <div className="label text-sky-700">De verificat la vizionare</div>
            <p className="mt-0.5 text-xs leading-relaxed text-slate-700">
              {sentiment.recomandare_cumparator}
            </p>
          </div>
        </div>
      )}
    </section>
  );
}
