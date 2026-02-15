const STORAGE_KEY = 'trading-logbook-v1';

const schemaExample = [
  {
    rank: 3,
    name: 'BAYN.DE CALL',
    wkn: 'VJ0QX5',
    score: 92,
    scoreMax: 115,
    strike: 44.0,
    price: 2.32,
    spreadPct: 0.48,
    omega: 14.9,
    leverage: 21.7,
    durationDays: 13,
    impliedVolPct: 36.2,
    premiumPct: 1.6,
    thetaPerDayPct: 5.0,
    breakEvenMovePct: 0.8,
    issuer: 'Vontobel',
    stakeholderInfo:
      'enger Spread, geringer Zeitwertverlust, Break-even mit kleiner Bewegung erreichbar',
    setup200: {
      pieces: 86,
      entry: 2.32,
      stop: 2.088,
      cost: 199.52,
      risk: 19.95,
    },
  },
];

const sampleData = [
  {
    rank: 3,
    name: 'BAYN.DE CALL',
    wkn: 'VJ0QX5',
    score: 92,
    scoreMax: 115,
    strike: 44.0,
    price: 2.32,
    spreadPct: 0.48,
    omega: 14.9,
    leverage: 21.7,
    durationDays: 13,
    impliedVolPct: 36.2,
    premiumPct: 1.6,
    thetaPerDayPct: 5.0,
    breakEvenMovePct: 0.8,
    issuer: 'Vontobel',
    stakeholderInfo:
      'Fokus auf BAYN.DE mit enger Ausführung und niedriger Theta-Belastung.',
    setup200: { pieces: 86, entry: 2.32, stop: 2.088, cost: 199.52, risk: 19.95 },
  },
  {
    rank: 2,
    name: 'ADI CALL',
    wkn: 'JV653M',
    score: 95,
    scoreMax: 115,
    strike: 330,
    price: 2.62,
    spreadPct: 0.76,
    omega: 6.1,
    leverage: 10.7,
    durationDays: 124,
    impliedVolPct: 37.6,
    premiumPct: 9.0,
    thetaPerDayPct: 2.8,
    breakEvenMovePct: 8.9,
    issuer: 'J.P. Morgan',
    stakeholderInfo: 'Fokus auf ADI mit solidem Omega bei längerer Laufzeit.',
    setup200: { pieces: 76, entry: 2.62, stop: 2.358, cost: 199.12, risk: 19.91 },
  },
];

const tableBody = document.getElementById('tradesTableBody');
const schemaPreview = document.getElementById('schemaPreview');
const rowTemplate = document.getElementById('rowTemplate');

document.getElementById('jsonFile').addEventListener('change', handleFileUpload);
document.getElementById('loadSampleBtn').addEventListener('click', () => {
  persistTrades(sampleData);
  render(sampleData);
});
document.getElementById('clearBtn').addEventListener('click', () => {
  localStorage.removeItem(STORAGE_KEY);
  render([]);
});

schemaPreview.textContent = JSON.stringify(schemaExample, null, 2);

const persisted = readPersistedTrades();
render(persisted.length ? persisted : []);

function handleFileUpload(event) {
  const file = event.target.files?.[0];
  if (!file) return;

  const reader = new FileReader();
  reader.onload = () => {
    try {
      const raw = JSON.parse(String(reader.result));
      const rows = normalizeInput(raw);
      if (!rows.length) throw new Error('Keine gültigen Trade-Objekte gefunden.');
      persistTrades(rows);
      render(rows);
    } catch (error) {
      alert(`JSON konnte nicht verarbeitet werden: ${error.message}`);
    }
  };
  reader.readAsText(file);
}

function normalizeInput(raw) {
  const arr = Array.isArray(raw) ? raw : [raw];
  return arr
    .map((item) => ({
      rank: Number(item.rank ?? item.Rang ?? 0),
      name: String(item.name ?? item.Name ?? '-'),
      wkn: String(item.wkn ?? item.WKN ?? '-'),
      score: Number(item.score ?? item.gesamtScore ?? 0),
      scoreMax: Number(item.scoreMax ?? item.score_max ?? 115),
      spreadPct: Number(item.spreadPct ?? item.spread ?? 0),
      omega: Number(item.omega ?? 0),
      breakEvenMovePct: Number(item.breakEvenMovePct ?? item.breakEvenPct ?? 0),
      thetaPerDayPct: Number(item.thetaPerDayPct ?? item.thetaPct ?? 0),
      issuer: String(item.issuer ?? item.emittent ?? '-'),
      stakeholderInfo: String(item.stakeholderInfo ?? item.info ?? '-'),
      setup200: {
        risk: Number(item?.setup200?.risk ?? item.risk200 ?? 0),
      },
    }))
    .filter((x) => x.name !== '-');
}

function render(rows) {
  tableBody.innerHTML = '';

  for (const row of rows) {
    const clone = rowTemplate.content.cloneNode(true);
    const values = {
      rank: row.rank || '-',
      name: row.name,
      wkn: row.wkn,
      score: `${row.score}/${row.scoreMax}`,
      spread: `${row.spreadPct.toFixed(2)}%`,
      omega: row.omega.toFixed(1),
      breakEvenMove: `${row.breakEvenMovePct.toFixed(1)}%`,
      thetaPerDay: `${row.thetaPerDayPct.toFixed(1)}%`,
      issuer: row.issuer,
      stakeholderInfo: row.stakeholderInfo,
    };

    Object.entries(values).forEach(([key, value]) => {
      clone.querySelector(`[data-key="${key}"]`).textContent = value;
    });

    tableBody.appendChild(clone);
  }

  renderStats(rows);
}

function renderStats(rows) {
  const count = rows.length;
  const avgScore = average(rows.map((r) => r.score));
  const avgSpread = average(rows.map((r) => r.spreadPct));
  const avgTheta = average(rows.map((r) => r.thetaPerDayPct));
  const avgRisk = average(rows.map((r) => r.setup200?.risk ?? 0));

  const issuerCounts = rows.reduce((acc, row) => {
    acc[row.issuer] = (acc[row.issuer] || 0) + 1;
    return acc;
  }, {});

  const bestIssuer = Object.entries(issuerCounts).sort((a, b) => b[1] - a[1])[0]?.[0] ?? '-';

  text('statTrades', count);
  text('statAvgScore', count ? avgScore.toFixed(1) : '0');
  text('statAvgSpread', `${avgSpread.toFixed(2)}%`);
  text('statAvgTheta', `${avgTheta.toFixed(2)}%`);
  text('statBestIssuer', bestIssuer);
  text('statAvgRisk', `${avgRisk.toFixed(2)}€`);
}

function text(id, value) {
  document.getElementById(id).textContent = String(value);
}

function average(values) {
  if (!values.length) return 0;
  return values.reduce((a, b) => a + Number(b || 0), 0) / values.length;
}

function readPersistedTrades() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    return raw ? normalizeInput(JSON.parse(raw)) : [];
  } catch {
    return [];
  }
}

function persistTrades(rows) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(rows));
}
