import React, { useState } from 'react';
import { ArrowRight, CheckCircle2, Loader2, PlayCircle, Search, Sparkles } from 'lucide-react';

const INSPECTION_STEPS = [
  'Extragere specificații și fotografii din anunțul imobiliare.ro…',
  'Modelare evaluare comparativă ANEVAR (GEV 630)…',
  'AI Vision: scanare mobilier și finisaje interioare…',
  'AI Vision: detectare defecte, vicii ascunse și recunoaștere branduri…',
  'Verificare catalog retail online (eMAG, Altex, Google Shopping)…',
  'Geocodare adresă și preluare imagini Google Street View 360°…',
  'Cartografiere facilități pe rază de 500 m (Places & Routes)…',
  'Identificare dezvoltator și antreprenor general…',
  'Due diligence financiar și risc de insolvență (Targetare.ro)…',
  'Analiză sentiment din recenziile rezidenților pe Google Maps…',
  'Compilare dosar tehnic și generare PDF…',
];

export default function SearchHero({ onSearch, onDemo, loading, currentStep }) {
  const [url, setUrl] = useState('');

  const handleSubmit = (event) => {
    event.preventDefault();
    if (!url.trim()) return;
    onSearch(url.trim());
  };

  const handleQuickDemo = () => {
    setUrl('https://www.imobiliare.ro/oferta/demo-aviatiei-park');
    onDemo();
  };

  return (
    <section
      id="top"
      className="no-print relative overflow-hidden border-b border-slate-200
                 bg-gradient-to-b from-white to-canvas py-12 md:py-16"
    >
      <div
        className="pointer-events-none absolute -top-24 left-1/2 h-72 w-[min(680px,120vw)]
                   -translate-x-1/2 rounded-full bg-sky-200/40 blur-3xl"
      />

      <div className="relative z-10 mx-auto max-w-4xl px-4 sm:px-6 text-center">
        <div className="mb-6 inline-flex items-center gap-2 rounded-full border border-sky-200 bg-sky-50 px-3.5 py-1.5 text-xs font-semibold text-sky-700">
          <Sparkles className="h-3.5 w-3.5" />
          Istoricul și diagnosticul tehnic complet al oricărei proprietăți
        </div>

        <h1 className="mb-4 text-3xl font-extrabold leading-tight tracking-tight text-slate-900 sm:text-4xl md:text-5xl">
          Nu cumpăra un imobil cu vicii ascunse.
          <br />
          <span className="bg-gradient-to-r from-sky-600 to-indigo-600 bg-clip-text text-transparent">
            Află-i istoricul tehnic înainte de avans.
          </span>
        </h1>

        <p className="mx-auto mb-8 max-w-2xl text-sm leading-relaxed text-slate-600 sm:text-base">
          Introdu link-ul anunțului sau adresa. Agentul scanează finisajele, detectează defectele,
          verifică prețul față de standardul ANEVAR, evaluează electrocasnicele pe magazinele online
          și verifică solvența dezvoltatorului.
        </p>

        <form onSubmit={handleSubmit} className="mx-auto mb-5 max-w-3xl">
          <div
            className="flex flex-col items-center gap-2 rounded-2xl border border-slate-200 bg-white
                       p-2 shadow-lift transition-colors focus-within:border-sky-400 sm:flex-row"
          >
            <div className="flex w-full flex-1 items-center px-3">
              <Search className="mr-3 h-5 w-5 flex-shrink-0 text-slate-400" />
              <input
                type="text"
                value={url}
                onChange={(event) => setUrl(event.target.value)}
                placeholder="Link anunț (https://www.imobiliare.ro/oferta/…) sau ID ofertă"
                className="w-full bg-transparent py-2 text-sm text-slate-900 placeholder-slate-400 focus:outline-none"
                disabled={loading}
              />
            </div>
            <div className="flex w-full items-center gap-2 sm:w-auto">
              <button
                type="button"
                onClick={handleQuickDemo}
                disabled={loading}
                className="flex min-w-0 flex-1 items-center justify-center gap-1.5 rounded-xl border
                           border-slate-200 bg-white px-3 py-3 text-xs font-semibold text-slate-700
                           transition-colors hover:bg-slate-50 disabled:opacity-50 sm:w-auto
                           sm:flex-none sm:px-4"
              >
                <PlayCircle className="h-4 w-4 text-sky-600" />
                Demo instant
              </button>
              <button
                type="submit"
                disabled={loading || !url.trim()}
                className="flex min-w-0 flex-1 items-center justify-center gap-2 rounded-xl
                           bg-gradient-to-r from-sky-600 to-indigo-600 px-5 py-3 text-xs font-bold
                           text-white shadow-card transition-all hover:from-sky-500
                           hover:to-indigo-500 disabled:opacity-50 sm:w-auto sm:flex-none
                           sm:flex-shrink-0 sm:px-6"
              >
                {loading ? (
                  <>
                    <Loader2 className="h-4 w-4 animate-spin" />
                    Se analizează…
                  </>
                ) : (
                  <>
                    Generează raport
                    <ArrowRight className="h-4 w-4" />
                  </>
                )}
              </button>
            </div>
          </div>
        </form>

        <div className="flex flex-wrap items-center justify-center gap-2 text-xs">
          <span className="font-medium text-slate-500">Exemple rapide:</span>
          <button
            type="button"
            onClick={handleQuickDemo}
            className="rounded-lg border border-slate-200 bg-white px-3 py-1 text-slate-600
                       transition-colors hover:border-slate-300 hover:text-slate-900"
          >
            🏢 Penthouse Aviatiei Park
          </button>
          <button
            type="button"
            onClick={() => {
              setUrl('https://www.imobiliare.ro/oferta/floreasca-3-camere-lux');
              onSearch('floreasca-3-camere-lux');
            }}
            className="rounded-lg border border-slate-200 bg-white px-3 py-1 text-slate-600
                       transition-colors hover:border-slate-300 hover:text-slate-900"
          >
            🏙️ Floreasca 3 camere lux
          </button>
        </div>

        {loading && (
          <div className="mx-auto mt-8 max-w-2xl rounded-2xl border border-sky-200 bg-white p-5 text-left shadow-lift">
            <div className="mb-4 flex items-center justify-between gap-3">
              <div className="flex items-center gap-2 text-sm font-bold text-sky-700">
                <Loader2 className="h-4 w-4 animate-spin" />
                Diagnostic în desfășurare
              </div>
              <span className="font-mono text-xs text-slate-500">
                {Math.min(currentStep + 1, INSPECTION_STEPS.length)} / {INSPECTION_STEPS.length}
              </span>
            </div>

            <div className="mb-5 h-2 w-full overflow-hidden rounded-full bg-slate-100">
              <div
                className="h-full bg-gradient-to-r from-sky-500 to-emerald-500 transition-all duration-500 ease-out"
                style={{
                  width: `${Math.round(
                    (Math.min(currentStep + 1, INSPECTION_STEPS.length) / INSPECTION_STEPS.length) *
                      100,
                  )}%`,
                }}
              />
            </div>

            <div className="max-h-48 space-y-2 overflow-y-auto pr-2">
              {INSPECTION_STEPS.map((step, index) => {
                const isDone = index < currentStep;
                const isCurrent = index === currentStep;
                return (
                  <div
                    key={step}
                    className={`flex items-center gap-2.5 py-1 text-xs ${
                      isDone
                        ? 'text-emerald-700'
                        : isCurrent
                          ? 'font-semibold text-sky-700'
                          : 'text-slate-400'
                    }`}
                  >
                    {isDone ? (
                      <CheckCircle2 className="h-4 w-4 flex-shrink-0 text-emerald-600" />
                    ) : isCurrent ? (
                      <Loader2 className="h-4 w-4 flex-shrink-0 animate-spin text-sky-600" />
                    ) : (
                      <span className="h-4 w-4 flex-shrink-0 rounded-full border border-slate-200" />
                    )}
                    {step}
                  </div>
                );
              })}
            </div>
          </div>
        )}
      </div>
    </section>
  );
}
