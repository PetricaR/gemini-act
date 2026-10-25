import React from 'react';
import { AlertCircle, HelpCircle } from 'lucide-react';
import ProvenanceBadge from './ProvenanceBadge.jsx';

export default function UnavailableBlock({
  title,
  reason,
  provenance = 'indisponibil',
  detail,
  className = '',
}) {
  return (
    <div
      className={`rounded-xl border border-slate-200 bg-slate-50/70 p-5 text-slate-600 ${className}`}
    >
      <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
        <div className="flex items-start gap-3">
          <div className="rounded-lg border border-slate-200 bg-white p-2 text-slate-400 shadow-sm">
            <AlertCircle className="h-5 w-5 text-slate-500" />
          </div>
          <div>
            <h4 className="text-sm font-bold text-slate-800">
              {title || 'Informații indisponibile'}
            </h4>
            <p className="mt-1 text-xs leading-relaxed text-slate-600">
              {reason ||
                'Datele necesare pentru această secțiune nu sunt disponibile sau nu întrunesc criteriile de fiabilitate.'}
            </p>
          </div>
        </div>
        <div className="flex-shrink-0 self-start sm:self-auto">
          <ProvenanceBadge provenance={provenance} detail={detail} />
        </div>
      </div>
    </div>
  );
}
