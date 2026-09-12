import React from 'react';
import {
  AlertCircle,
  Calculator,
  Database,
  FileText,
  Sparkles,
} from 'lucide-react';

const PROVENANCE_CONFIG = {
  masurat: {
    label: 'Măsurat',
    sub: 'Date obiective / API extern',
    icon: Database,
    badgeClass: 'border-emerald-300 bg-emerald-50 text-emerald-800',
    dotClass: 'bg-emerald-500',
  },
  estimat: {
    label: 'Estimat',
    sub: 'Calcul econometric ANEVAR',
    icon: Calculator,
    badgeClass: 'border-sky-300 bg-sky-50 text-sky-800',
    dotClass: 'bg-sky-500',
  },
  model: {
    label: 'Model AI',
    sub: 'Gemini Vision / multimodal',
    icon: Sparkles,
    badgeClass: 'border-purple-300 bg-purple-50 text-purple-800',
    dotClass: 'bg-purple-500',
  },
  anunt: {
    label: 'Text anunț',
    sub: 'Declarat de vânzător',
    icon: FileText,
    badgeClass: 'border-amber-300 bg-amber-50 text-amber-800',
    dotClass: 'bg-amber-500',
  },
  indisponibil: {
    label: 'Indisponibil',
    sub: 'Date insuficiente',
    icon: AlertCircle,
    badgeClass: 'border-slate-300 bg-slate-100 text-slate-600',
    dotClass: 'bg-slate-400',
  },
};

const CONFIDENCE_CONFIG = {
  ridicata: {
    label: 'încredere ridicată',
    badgeClass: 'bg-emerald-100/80 text-emerald-800 border-emerald-300',
  },
  medie: {
    label: 'încredere medie',
    badgeClass: 'bg-amber-100/80 text-amber-800 border-amber-300',
  },
  scazuta: {
    label: 'încredere scăzută',
    badgeClass: 'bg-rose-100/80 text-rose-800 border-rose-300',
  },
};

export default function ProvenanceBadge({
  provenance,
  provenienta,
  confidence,
  incredere,
  detail,
  className = '',
}) {
  const key = (provenance || provenienta || 'indisponibil').toLowerCase();
  const confKey = (confidence || incredere || '').toLowerCase();

  const cfg = PROVENANCE_CONFIG[key] || PROVENANCE_CONFIG.indisponibil;
  const confCfg = CONFIDENCE_CONFIG[confKey];
  const Icon = cfg.icon;

  return (
    <div className={`inline-flex flex-wrap items-center gap-1.5 text-[11px] ${className}`}>
      <span
        title={detail || cfg.sub}
        className={`inline-flex items-center gap-1.5 rounded-md border px-2 py-0.5 font-semibold tracking-tight shadow-sm ${cfg.badgeClass}`}
      >
        <Icon className="h-3 w-3 flex-shrink-0" />
        <span>{cfg.label}</span>
        {detail && <span className="opacity-75 font-normal">· {detail}</span>}
      </span>

      {confCfg && (
        <span
          className={`inline-flex items-center rounded-md border px-1.5 py-0.5 text-[10px] font-medium ${confCfg.badgeClass}`}
        >
          {confCfg.label}
        </span>
      )}
    </div>
  );
}
