import React from 'react';
import { Building2, FileText, Printer, ShieldCheck } from 'lucide-react';

export default function Header({ pdfUrl, hasData }) {
  return (
    <header className="no-print sticky top-0 z-50 bg-white/90 backdrop-blur-md border-b border-slate-200">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 h-16 flex items-center justify-between gap-4">
        <a href="#top" className="flex items-center gap-3 min-w-0">
          <div
            className="h-10 w-10 rounded-xl bg-gradient-to-tr from-sky-600 to-indigo-600
                       flex items-center justify-center shadow-card flex-shrink-0"
          >
            <Building2 className="h-5 w-5 text-white" />
          </div>
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <span className="font-extrabold text-lg sm:text-xl tracking-tight text-slate-900">
                EVALUATOR<span className="text-sky-600">·AI</span>
              </span>
              <span className="hidden sm:inline pill bg-sky-50 text-sky-700 border-sky-200">
                Audit 360°
              </span>
            </div>
            <p className="text-[11px] text-slate-500 hidden sm:block truncate">
              Agent AI pentru audit tehnic și evaluare imobiliară
            </p>
          </div>
        </a>

        <div className="flex items-center gap-2 flex-shrink-0">
          {hasData && (
            <button
              type="button"
              onClick={() => window.print()}
              className="hidden sm:inline-flex items-center gap-1.5 text-xs font-semibold
                         text-slate-600 hover:text-slate-900 border border-slate-200
                         hover:border-slate-300 bg-white px-3 py-2 rounded-lg transition-colors"
            >
              <Printer className="h-4 w-4" />
              Printează
            </button>
          )}
          {hasData && pdfUrl && (
            <a
              href={pdfUrl}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-2 bg-slate-900 hover:bg-slate-800 text-white
                         text-xs font-semibold px-4 py-2 rounded-lg shadow-card transition-colors"
            >
              <FileText className="h-4 w-4" />
              <span className="hidden sm:inline">Descarcă raportul PDF</span>
              <span className="sm:hidden">PDF</span>
            </a>
          )}
          <div
            className="hidden lg:flex items-center gap-1.5 text-[11px] font-medium text-slate-500
                       bg-slate-50 border border-slate-200 px-3 py-2 rounded-lg"
          >
            <ShieldCheck className="h-4 w-4 text-emerald-600" />
            Structurat pe SEV 106 &amp; GEV 630
          </div>
        </div>
      </div>
    </header>
  );
}
