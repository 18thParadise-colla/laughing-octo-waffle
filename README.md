# Optionsschein-Scanner (ING / Onvista) – Projektüberblick

Dieses Projekt scannt **Basiswerte** (Aktien/Indizes) und findet anschließend **ING‑handelbare Optionsscheine** auf onvista.de. Ziel ist es, kurzfristig handelbare Calls (9–16 Tage Laufzeit) mit soliden Chancen/Risiko‑Eigenschaften zu identifizieren.

Der Ablauf besteht aus drei Teilen:
1. **Basiswert‑Check (Trend/Momentum/Volatilität)**
2. **Optionsschein‑Suche & Qualitätsfilter (Onvista‑Scraping)**
3. **Scoring der Optionsscheine & Top‑Auswahl**

> **Hinweis:** Das Skript arbeitet mit Live‑Daten (yfinance + onvista) und ist als Analysehilfe gedacht, **keine Anlageberatung**.

---

## Installation & Start

**Voraussetzungen:**
- Python **3.10+** empfohlen
- (Ubuntu/Debian) für venv: `sudo apt install python3-venv`

### Option A: Neues CLI (empfohlen)

Dieses Repo wurde von einem großen Single‑File Script auf ein modulares Package refactored.

```bash
# im Repo
python -m venv .venv
. .venv/bin/activate
pip install -U pip
pip install -e .

# schneller Testlauf (limit = weniger Ticker)
python -m warrant_scanner.main --limit 50 --out top_options.csv
```

### Option B: Legacy Entry Point (kompatibel)

```bash
python warrants_searcher_v6_fixed_3.py --limit 50 --out top_options.csv
```

**Output:**
- CSV Export: `top_options.csv` (oder via `--out`)

### US-Ticker Support (Währungslogik)
Für US Underlyings versucht der Refactor Premium/Intrinsic/Break-even **währungskonsistent** zu berechnen,
indem FX-Raten via Yahoo (`EURUSD=X`, etc.) geladen werden. Wenn FX nicht verfügbar ist, werden einige
Kennzahlen (z.B. Intrinsic/Extrinsic) defensiv leer gelassen statt falsch gerechnet.

---

## Teil 1 – Basiswert‑Check (Was wird geprüft?)

Jeder Ticker bekommt einen **Score** und ein Flag `OS_OK`. Nur wenn der Basiswert „optionsschein‑tauglich“ ist, geht es mit Teil 2 weiter.

### 1) Trend (Aufwärtstrend‑Bestätigung)
**Kriterium:**
- `Close > SMA20 > SMA50`

**Punkte:** +4 bei sauberem Aufwärtstrend.

### 2) Momentum & RSI‑Bestätigung
**Kriterium:**
- Kurs liegt über dem Schlusskurs von vor 10 Tagen
- RSI zwischen 50 und 70 (Trend bestätigt, aber nicht überkauft)

**Punkte:**
- +3 bei Momentum **und** RSI im Idealbereich
- +2 bei Momentum, aber RSI‑Warnung

### 3) Volatilität (ATR & Recent Vol)
**Kriterium:**
- ATR‑Prozent (`ATR / Close`) zwischen **2% und 5%**
- „Recent Volatility“ (Rolling STD) möglichst aktiv

**Punkte:**
- +3 bei idealer ATR **und** aktiver Recent Vol
- +2 bei idealer ATR, aber geringe Recent Vol
- +1 bei sehr hoher Volatilität

### 4) Volumen
**Kriterium:**
- aktuelles Volumen > 20‑Tage‑Durchschnitt

**Punkte:** +2 wenn Volumen über Durchschnitt.

### 5) Seitwärts‑Filter (Theta‑Gefahr)
**Kriterium:**
- 15‑Tage‑Range (High‑Low) relativ zum Kurs
- wenn Range < 2.5% → **Abzug**

**Punkte:**
- −5 bei Seitwärtsmarkt
- +0 wenn genug Bewegung

### 6) „Optionsschein‑tauglich“ (OS_OK)
Ein Basiswert ist **OS_OK**, wenn:
- Score ≥ 7
- ATR‑Prozent ≥ 2%
- 15‑Tage‑Range ≥ 2.5%

### 7) Ziel‑Strikes (für Optionsschein‑Score)
Für die spätere Bewertung der Optionsscheine wird ein Ziel‑Strike berechnet:
- **Long‑Strike:** `Close + 1.5 × ATR(5d)`
- **Short‑Strike:** `Close − 1.5 × ATR(5d)`

Diese Ziel‑Strikes helfen beim Abgleich, ob ein Optionsschein sinnvoll nahe am erwarteten Bewegungsraum liegt.

---

## Teil 2 – Optionsschein‑Suche (Onvista)

Für jeden qualifizierten Basiswert:
- **Ticker → Onvista‑Namen** (Mapping + Fallback‑Varianten)
- Suche auf onvista.de
- Vorsortierung für Qualität (um Requests zu reduzieren)

### Vorfilter (Qualität)
Ein Optionsschein kommt **nur weiter**, wenn:
- WKN‑Länge = 6
- Basispreis > 0
- Spread ≤ 3.0%
- Omega ≥ 2

---

## Teil 3 – Optionsschein‑Scoring (Was wird geprüft?)

Jeder Optionsschein bekommt einen **Gesamt‑Score (max 115 Punkte)** aus 8 Faktoren:

### 1) Spread‑Score (0–25 Punkte)
- ≤ 0.8% → 25
- ≤ 1.2% → 20
- ≤ 1.8% → 15
- ≤ 2.5% → 10
- > 2.5% → 5

### 2) Omega‑Score (0–25 Punkte)
- 6–10 → 25
- 4–12 → 20
- 3–15 → 15
- sonst → 5

### 3) Strike‑Nähe (0–20 Punkte)
Vergleicht Basispreis mit dem Ziel‑Strike.
- ≤ 2% Abweichung → 20
- ≤ 5% → 15
- ≤ 10% → 10
- sonst → 5

### 4) Theta‑Score (0–15 Punkte)
Zeitwertverlust pro Tag (in % vom Mid‑Preis):
- ≤ 5% → 15
- ≤ 7% → 12
- ≤ 10% → 8
- sonst → 3

### 5) Implizite Volatilität (0–10 Punkte)
- 20–40% → 10
- 15–50% → 7
- sonst → 4

### 6) Aufgeld (0–5 Punkte)
- ≤ 2% → 5
- ≤ 5% → 3
- sonst → 1

### 7) Break‑Even‑Entfernung (0–10 Punkte)
Benötigte Bewegung bis Break‑Even:
- ≤ 3% → 10
- ≤ 5% → 8
- ≤ 8% → 5
- sonst → 2

### 8) Leverage‑Prämie (0–5 Punkte)
Hebel vs. Preisrelation:
- > 0.5 → 5
- > 0.3 → 4
- sonst → 2

---

## Ergebnisse & Output

- **Top 3 Optionsscheine pro Basiswert** werden ausgegeben.
- Am Ende werden die **besten 3 Optionen insgesamt** gelistet.
- Export als CSV: **`top_optionsscheine_ing.csv`**

Zusätzlich gibt das Skript eine **Positionsgröße für 200€ Einsatz** aus (mit 10% Stop‑Loss‑Annahme).

---


## Mailversand der finalen Top 3 (für Cronjobs)

Das Skript kann nach dem Konsolen-Output optional eine Mail mit genau den finalen **Top 3 Optionsscheinen** senden.

Dafür folgende Umgebungsvariablen setzen:

```bash
export TOP3_EMAIL_TO=dein.empfaenger@example.com
export TOP3_SMTP_HOST=smtp.gmail.com
export TOP3_SMTP_PORT=587
export TOP3_SMTP_USER=dein.smtp.user@example.com
export TOP3_SMTP_PASSWORD='dein-passwort-oder-app-passwort'
# optional:
export TOP3_EMAIL_FROM=dein.absender@example.com
export TOP3_SMTP_USE_TLS=1
```

Wenn `TOP3_EMAIL_TO` oder SMTP-Login fehlen, wird der Mailversand sauber übersprungen und das Skript läuft normal weiter.

Beispiel für `crontab` (3x pro Tag):

```bash
0 8,12,16 * * 1-5 cd /pfad/zum/repo && /usr/bin/python3 warrants_searcher_v6_fixed_3.py >> scanner.log 2>&1
```

## Anpassungsideen (falls du erweitern willst)

- Andere Laufzeiten (z. B. 20–30 Tage) ermöglichen
- Put‑Suche aktivieren (aktuell auf Calls ausgerichtet)
- Scoring‑Gewichtung anpassen
- Weitere Broker/Quellen integrieren

---

## Projektdateien

- **`warrants_searcher_v6_fixed_3.py`** → Komplettes Skript (Basiswert‑Check, Onvista‑Scraping, Scoring)
- **`top_optionsscheine_ing.csv`** → Output der letzten Analyse (wird beim Lauf überschrieben)
