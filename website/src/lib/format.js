/**
 * Romanian formatting for everything the report prints.
 *
 * `ro-RO` uses "." for thousands and "," for decimals — the opposite of the
 * JS default — and every figure in this report is money, area or a distance a
 * Romanian buyer has to recognise at a glance.
 */

const nf0 = new Intl.NumberFormat('ro-RO', { maximumFractionDigits: 0 });
const nf1 = new Intl.NumberFormat('ro-RO', { maximumFractionDigits: 1 });
const nf2 = new Intl.NumberFormat('ro-RO', { minimumFractionDigits: 2, maximumFractionDigits: 2 });

const isNum = (value) => typeof value === 'number' && Number.isFinite(value);

export function num(value, decimals = 0) {
  if (!isNum(value)) return '—';
  if (decimals === 1) return nf1.format(value);
  if (decimals === 2) return nf2.format(value);
  return nf0.format(value);
}

export function eur(value, { decimals = 0, compact = false } = {}) {
  if (!isNum(value)) return '—';
  if (compact && Math.abs(value) >= 1_000_000) return `${nf1.format(value / 1_000_000)} mil. €`;
  return `${num(value, decimals)} €`;
}

export function ron(value, { compact = false } = {}) {
  if (!isNum(value)) return '—';
  if (compact && Math.abs(value) >= 1_000_000) return `${nf1.format(value / 1_000_000)} mil. RON`;
  return `${num(value)} RON`;
}

export function eurPerSqm(value) {
  return isNum(value) ? `${num(value)} €/mp` : '—';
}

export function percent(value, { signed = false, decimals = 1 } = {}) {
  if (!isNum(value)) return '—';
  const body = `${num(Math.abs(value), decimals)}%`;
  if (!signed) return body;
  return value === 0 ? `0%` : `${value > 0 ? '+' : '−'}${body}`;
}

export function sqm(value) {
  return isNum(value) ? `${num(value, value % 1 ? 1 : 0)} mp` : '—';
}

/** "440 m" under a kilometre, "1,2 km" above it. */
export function distance(meters) {
  if (!isNum(meters)) return '—';
  return meters < 1000 ? `${num(meters)} m` : `${num(meters / 1000, 1)} km`;
}

export function walkTime(minutes, estimated = false) {
  if (!isNum(minutes)) return '—';
  return `${estimated ? '~' : ''}${minutes} min pe jos`;
}

/** "2024-07" -> "iulie 2024", for Street View capture dates. */
export function captureDate(value) {
  if (!value) return null;
  const match = /^(\d{4})-(\d{2})$/.exec(String(value));
  if (!match) return String(value);
  const months = [
    'ianuarie', 'februarie', 'martie', 'aprilie', 'mai', 'iunie',
    'iulie', 'august', 'septembrie', 'octombrie', 'noiembrie', 'decembrie',
  ];
  return `${months[Number(match[2]) - 1]} ${match[1]}`;
}

/**
 * The report's single scale for "how good is this number, 0-10".
 * Used by every score badge so a 7.9 looks the same wherever it appears.
 */
export function scoreTone(score) {
  if (!isNum(score)) return TONES.neutral;
  if (score >= 8.5) return TONES.excellent;
  if (score >= 7) return TONES.good;
  if (score >= 5) return TONES.fair;
  return TONES.poor;
}

export const TONES = {
  excellent: {
    key: 'excellent',
    text: 'text-emerald-700',
    bg: 'bg-emerald-50',
    border: 'border-emerald-200',
    ring: 'border-emerald-500',
    solid: 'bg-emerald-600',
    label: 'Excelent',
  },
  good: {
    key: 'good',
    text: 'text-sky-700',
    bg: 'bg-sky-50',
    border: 'border-sky-200',
    ring: 'border-sky-500',
    solid: 'bg-sky-600',
    label: 'Bun',
  },
  fair: {
    key: 'fair',
    text: 'text-amber-700',
    bg: 'bg-amber-50',
    border: 'border-amber-200',
    ring: 'border-amber-500',
    solid: 'bg-amber-500',
    label: 'Acceptabil',
  },
  poor: {
    key: 'poor',
    text: 'text-rose-700',
    bg: 'bg-rose-50',
    border: 'border-rose-200',
    ring: 'border-rose-500',
    solid: 'bg-rose-600',
    label: 'Slab',
  },
  neutral: {
    key: 'neutral',
    text: 'text-slate-700',
    bg: 'bg-slate-50',
    border: 'border-slate-200',
    ring: 'border-slate-400',
    solid: 'bg-slate-600',
    label: 'Neevaluat',
  },
};

/** Severity of a defect -> the same tone vocabulary. */
export function severityTone(severity) {
  const s = String(severity || '').toLowerCase();
  if (s.includes('crit') || s.includes('ridic') || s.includes('major')) return TONES.poor;
  if (s.includes('moderat') || s.includes('mediu') || s.includes('med')) return TONES.fair;
  return TONES.good;
}

/**
 * How far the asking price sits above (+) or below (−) the estimated value.
 *
 * Derived from the two prices rather than read from
 * `ajustare_recomandata_procent`, because that field carries two different
 * conventions upstream: the live pipeline stores (asked − estimated)/estimated,
 * while parts of the dataset store the *recommended correction*, which has the
 * opposite sign for the same situation. The prices themselves are unambiguous,
 * so they win; the stored percentage is only a fallback when one is missing.
 */
export function priceDelta(asked, estimated, fallbackPercent) {
  if (isNum(asked) && isNum(estimated) && estimated > 0) {
    return ((asked - estimated) / estimated) * 100;
  }
  return isNum(fallbackPercent) ? fallbackPercent : 0;
}

/** The gap in euro, always a positive magnitude. */
export function priceGap(asked, estimated, fallbackEur) {
  if (isNum(asked) && isNum(estimated)) return Math.abs(asked - estimated);
  return isNum(fallbackEur) ? Math.abs(fallbackEur) : 0;
}
