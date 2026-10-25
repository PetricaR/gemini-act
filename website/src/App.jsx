import React, { useEffect, useState } from 'react';
import { AlertCircle, Shield } from 'lucide-react';
import Header from './components/Header.jsx';
import SearchHero from './components/SearchHero.jsx';
import PropertySummary from './components/PropertySummary.jsx';
import ValuationMeter from './components/ValuationMeter.jsx';
import ValuationApproaches from './components/ValuationApproaches.jsx';
import LocationMap from './components/LocationMap.jsx';
import ExteriorInspection from './components/ExteriorInspection.jsx';
import DefectsInspector from './components/DefectsInspector.jsx';
import AppliancesCatalog from './components/AppliancesCatalog.jsx';
import DeveloperAudit from './components/DeveloperAudit.jsx';
import ReviewsSentiment from './components/ReviewsSentiment.jsx';
import MarketAndRisk from './components/MarketAndRisk.jsx';
import NegotiationStrategy from './components/NegotiationStrategy.jsx';
import HandoverChecklist from './components/HandoverChecklist.jsx';
import MethodologyNotes from './components/MethodologyNotes.jsx';

/**
 * Section registry.
 *
 * `all` renders the whole dossier top to bottom — that is the default, because
 * the report is a document and a document is read in order. The other tabs are
 * a filter over the same components, not different content.
 */
const SECTIONS = [
  { id: 'all', label: 'Raport complet' },
  { id: 'valuation', label: 'Evaluare ANEVAR' },
  { id: 'location', label: 'Locație & facilități' },
  { id: 'defects', label: 'Defecte & finisaje' },
  { id: 'appliances', label: 'Dotări incluse' },
  { id: 'exterior', label: 'Street View & satelit' },
  { id: 'developer', label: 'Dezvoltator & recenzii' },
  { id: 'negotiation', label: 'Negociere & buget' },
  { id: 'risk', label: 'Piață, costuri & riscuri' },
  { id: 'method', label: 'Metodologie' },
];

export default function App() {
  const [data, setData] = useState(null);
  const [pdfUrl, setPdfUrl] = useState(null);
  const [loading, setLoading] = useState(false);
  const [currentStep, setCurrentStep] = useState(0);
  const [error, setError] = useState(null);
  const [activeTab, setActiveTab] = useState('all');

  useEffect(() => {
    loadDemo();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  /**
   * The step ticker is cosmetic: the backend runs the pipeline as one call and
   * cannot stream progress, so this paces the labels and stops one short of the
   * end, letting the real response advance it to done.
   */
  const startStepTicker = () => {
    setCurrentStep(0);
    const interval = setInterval(() => {
      setCurrentStep((previous) => (previous < 9 ? previous + 1 : 9));
    }, 1200);
    return interval;
  };

  const applyResponse = (payload) => {
    setData(payload.data || payload.date_audit || null);
    setPdfUrl(payload.pdf_download_url || payload.pdf_url || null);
  };

  const generateReport = async (inputUrl) => {
    setLoading(true);
    setError(null);
    const ticker = startStepTicker();

    try {
      const response = await fetch('/api/audit/generate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          url: inputUrl,
          is_demo: inputUrl.includes('demo') || inputUrl.includes('aviatiei'),
        }),
      });
      if (!response.ok) {
        throw new Error(`Serverul a răspuns cu eroare (${response.status}).`);
      }
      const payload = await response.json();
      if (payload.status !== 'ok' && payload.status !== 'success') {
        throw new Error(payload.message || payload.mesaj || 'Eroare neprevăzută.');
      }
      setCurrentStep(10);
      applyResponse(payload);
    } catch (err) {
      console.error(err);
      setError(err.message || 'A apărut o problemă la interogarea serverului.');
    } finally {
      clearInterval(ticker);
      setLoading(false);
    }
  };

  const loadDemo = async () => {
    setLoading(true);
    setError(null);
    const ticker = startStepTicker();

    try {
      const response = await fetch('/api/audit/demo');
      if (!response.ok) {
        throw new Error(`Nu s-a putut încărca raportul demonstrativ (${response.status}).`);
      }
      const payload = await response.json();
      setCurrentStep(10);
      applyResponse(payload);
    } catch (err) {
      console.error(err);
      setError(err.message || 'Eroare la încărcarea raportului demonstrativ.');
    } finally {
      clearInterval(ticker);
      setLoading(false);
    }
  };

  const shows = (section) => activeTab === 'all' || activeTab === section;

  return (
    <div className="flex min-h-screen flex-col bg-canvas font-sans text-slate-800">
      <Header hasData={Boolean(data)} pdfUrl={pdfUrl} />

      <SearchHero
        onSearch={generateReport}
        onDemo={loadDemo}
        loading={loading}
        currentStep={currentStep}
      />

      <main className="mx-auto w-full max-w-7xl flex-1 px-4 py-8 sm:px-6 lg:px-8">
        {error && (
          <div className="mb-6 flex items-center gap-3 rounded-xl border border-rose-200 bg-rose-50 p-4 text-sm text-rose-800">
            <AlertCircle className="h-5 w-5 flex-shrink-0 text-rose-500" />
            {error}
          </div>
        )}

        {data && (
          <>
            <nav className="no-print mb-6 flex items-center gap-1.5 overflow-x-auto border-b border-slate-200 pb-3">
              {SECTIONS.map((section) => (
                <button
                  key={section.id}
                  type="button"
                  onClick={() => setActiveTab(section.id)}
                  className={`whitespace-nowrap rounded-lg px-3 py-1.5 text-xs font-semibold transition-colors ${
                    activeTab === section.id
                      ? 'bg-slate-900 text-white shadow-card'
                      : 'text-slate-500 hover:bg-slate-100 hover:text-slate-900'
                  }`}
                >
                  {section.label}
                </button>
              ))}
            </nav>

            <PropertySummary data={data} pdfUrl={pdfUrl} />

            {shows('valuation') && (
              <>
                <ValuationMeter
                  evaluare={data.evaluare_anevar}
                  pretTotal={data.pret_total}
                  suprafata={data.suprafata_utila}
                />
                <ValuationApproaches evaluare={data.evaluare_anevar} />
              </>
            )}

            {shows('location') && <LocationMap locatie={data.locatie} adresa={data.adresa} />}

            {shows('exterior') && (
              <ExteriorInspection
                audit={data.audit_exterior}
                locatie={data.locatie}
                adresa={data.adresa}
              />
            )}

            {shows('defects') && (
              <DefectsInspector
                audit={data.audit_electrocasnice || data.audit_electrocasnice_finisaje}
              />
            )}

            {shows('appliances') && (
              <AppliancesCatalog
                audit={data.audit_electrocasnice || data.audit_electrocasnice_finisaje}
              />
            )}

            {shows('developer') && (
              <>
                <DeveloperAudit
                  targetare={data.audit_targetare || data.targetare_financiar}
                  specs={data.specificatii_dezvoltator}
                />
                <ReviewsSentiment
                  reviews={data.recenzii_google}
                  complexName={data.complex_name}
                />
              </>
            )}

            {shows('negotiation') && (
              <NegotiationStrategy
                strategie={data.strategie_negociere}
                buget={data.buget_consolidat}
              />
            )}

            {shows('risk') && <MarketAndRisk data={data} />}

            {shows('method') && (
              <>
                <HandoverChecklist
                  checklist={data.checklist_receptie || data.receptie_checklist}
                />
                <MethodologyNotes
                  metodologie={data.metodologie}
                  ipoteze={data.ipoteze_limitative}
                />
              </>
            )}
          </>
        )}
      </main>

      <footer className="border-t border-slate-200 bg-white py-8 text-xs text-slate-500">
        <div className="mx-auto flex max-w-7xl flex-col items-center justify-between gap-3 px-4 text-center sm:flex-row sm:text-left">
          <div className="flex items-center gap-2">
            <Shield className="h-4 w-4 text-sky-600" />
            <span className="font-semibold text-slate-600">
              Evaluator AI · raport tehnic independent
            </span>
          </div>
          <div>
            Imagini stradale și hărți © Google · ortofotoplan © Esri, Maxar, Earthstar Geographics
          </div>
        </div>
      </footer>
    </div>
  );
}
