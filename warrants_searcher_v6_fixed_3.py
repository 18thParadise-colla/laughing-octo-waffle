import yfinance as yf
import pandas as pd
import numpy as np
import requests
from bs4 import BeautifulSoup
import time
from datetime import datetime, timedelta
import re
from typing import List, Dict, Optional

# ================================
# TEIL 1: BASISWERT-CHECKER
# ================================

def calculate_atr(df, window=14):
    prev_close = df["Close"].shift(1)
    tr = pd.concat([
        df["High"] - df["Low"],
        (df["High"] - prev_close).abs(),
        (df["Low"] - prev_close).abs()
    ], axis=1).max(axis=1)
    return tr.rolling(window).mean()

def calculate_rsi(df, window=14):
    """Berechne Relative Strength Index"""
    delta = df["Close"].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=window).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=window).mean()
    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))
    return rsi

def calculate_recent_volatility(df, window=14):
    """Berechne Volatilität der letzten Tage (relevanter für Short-Term)"""
    recent_returns = df["Close"].pct_change()
    return recent_returns.rolling(window).std() * 100

def check_basiswert(ticker, period="6mo", interval="1d"):
    """Prüfe einzelnen Basiswert"""
    df = yf.download(ticker, period=period, interval=interval, progress=False)

    if df.empty or len(df) < 80:
        return None

    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    df = df.dropna()
    df["SMA20"] = df["Close"].rolling(20).mean()
    df["SMA50"] = df["Close"].rolling(50).mean()
    df["ATR"] = calculate_atr(df)
    df["RSI"] = calculate_rsi(df)
    df["Vol_Mean"] = df["Volume"].rolling(20).mean()
    df["Recent_Vol"] = calculate_recent_volatility(df)
    df = df.dropna()

    latest = df.iloc[-1]
    prev10 = df.iloc[-11]

    close = float(latest["Close"])
    sma20 = float(latest["SMA20"])
    sma50 = float(latest["SMA50"])
    atr = float(latest["ATR"])
    atr_pct = atr / close
    recent_vol = float(latest["Recent_Vol"])
    rsi = float(latest["RSI"])
    volume = float(latest["Volume"])
    vol_mean = float(latest["Vol_Mean"])
    
    # Bessere Strike-Berechnung: nutze 5-Tage ATR für realistischere Ziele
    atr_5d = float(df["ATR"].iloc[-5])
    long_strike = round(close + atr_5d * 1.5, 2)
    short_strike = round(close - atr_5d * 1.5, 2)

    score = 0
    reasons = []

    # Trend
    if close > sma20 > sma50:
        score += 4
        reasons.append("✔ Aufwärtstrend (Close > SMA20 > SMA50)")
    else:
        reasons.append("✘ Kein sauberer Aufwärtstrend")

    # Momentum (mit RSI Bestätigung)
    if close > float(prev10["Close"]) and 50 < rsi < 70:
        score += 3
        reasons.append(f"✔ Positives Momentum + RSI({rsi:.0f}) bestätigt")
    elif close > float(prev10["Close"]):
        score += 2
        reasons.append(f"⚠ Momentum ok aber RSI({rsi:.0f}) warnt")
    else:
        reasons.append("✘ Momentum nicht bestätigt")

    # ATR (durchschnittliche vs recent Volatilität)
    if 0.02 <= atr_pct <= 0.05 and recent_vol >= 0.8:
        score += 3
        reasons.append(f"✔ ATR ideal + Recent Vol aktiv ({recent_vol:.1f}%)")
    elif 0.02 <= atr_pct <= 0.05:
        score += 2
        reasons.append(f"⚠ ATR ok aber Recent Vol niedrig ({recent_vol:.1f}%)")
    elif atr_pct > 0.05:
        score += 1
        reasons.append(f"⚠ Sehr hohe Volatilität ({atr_pct*100:.2f}%)")
    else:
        reasons.append(f"✘ Zu wenig Volatilität ({atr_pct*100:.2f}%)")

    # Volumen
    if volume > vol_mean:
        score += 2
        reasons.append("✔ Volumen über Durchschnitt")
    else:
        reasons.append("✘ Volumen unter Durchschnitt")

    # Seitwärtsfilter
    range_15 = (
        df["High"].rolling(15).max()
        - df["Low"].rolling(15).min()
    ).iloc[-1] / close

    if range_15 < 0.025:
        score -= 5
        reasons.append("✘ Seitwärtsmarkt (Theta-Gefahr)")
    else:
        reasons.append("✔ Genug Range, kein Seitwärtsmarkt")

    # OS-OK
    os_ok = (
        score >= 7 and
        atr_pct >= 0.02 and
        range_15 >= 0.025
    )

    if os_ok:
        reasons.append("✅ OPTIONS-SCHEIN-TAUGLICH für 9–16 Tage")
    else:
        reasons.append("❌ Nicht optionsschein-tauglich (Filter nicht erfüllt)")

    return {
        "Ticker": ticker,
        "Close": round(close, 2),
        "ATR_%": round(atr_pct * 100, 2),
        "ATR_abs": round(atr, 2),
        "Recent_Vol_%": round(recent_vol, 2),
        "RSI": round(rsi, 1),
        "Score": score,
        "OS_OK": os_ok,
        "Long_Strike": long_strike,
        "Short_Strike": short_strike,
        "Reasoning": " | ".join(reasons)
    }

def strike_step(ticker):
    """Bestimme Strike-Schritte für verschiedene Ticker"""
    if not ticker.endswith(".DE") and not ticker.startswith("^"):
        return 5  # US Aktien → 5$
    elif ticker.endswith(".DE"):
        return 1  # Deutsche Aktien → 1€
    elif ticker.startswith("^G") or ticker.startswith("^N") or ticker.startswith("^S"):
        return 50  # Indizes
    else:
        return 5


# ================================
# TEIL 2: ING OPTIONSSCHEIN-FINDER
# ================================

class INGOptionsFinder:
    """
    Findet und bewertet Optionsscheine auf onvista.de
    Fokus: ING als Broker, umfassende Bewertung
    """
    
    def __init__(self, delay: float = 2.0):
        self.base_url = "https://www.onvista.de/derivate/Optionsscheine"
        self.delay = delay
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'de-DE,de;q=0.9,en;q=0.8'
        })
        
        # Retry-Konfiguration
        self.max_retries = 3
        self.retry_delay = 1  # Sekunden
        self.search_cache = {}  # Cache für erfolgreiche Suchen
        self.details_cache = {}  # Cache für Optionsschein-Details
    
    def ticker_to_onvista_name(self, ticker):
        """
        Konvertiere Ticker zu onvista Basiswert-Namen (DYNAMISCH)
        Lädt Mapping aus Cache oder generiert automatisch
        """
        # Lade Mapping aus Cache
        if not hasattr(self, 'onvista_mapping'):
            self.onvista_mapping = self._load_onvista_mapping()
        
        # Verwende gecachtes Mapping
        if ticker in self.onvista_mapping:
            cached = self.onvista_mapping[ticker]
            if cached:  # Nicht leere Liste
                return cached
        
        # Fallback: Generiere Namen-Varianten
        return self._generate_name_variants(ticker)
    
    def _load_onvista_mapping(self) -> Dict[str, List[str]]:
        """Lade onvista Mapping aus Cache-Datei"""
        import json
        import os
        
        cache_file = "onvista_mapping.json"
        
        try:
            if os.path.exists(cache_file):
                with open(cache_file, 'r') as f:
                    mapping = json.load(f)
                    print(f"   📦 Onvista-Mapping geladen: {len(mapping)} Ticker")
                    return mapping
        except:
            pass
        
        # Fallback: Minimal-Mapping
        return {
            "^GDAXI": ["DAX"],
            "^NDX": ["NASDAQ-100"],
            "^GSPC": ["S-P-500"]
        }
    
    def _generate_name_variants(self, ticker: str) -> List[str]:
        """Generiere Namens-Varianten wenn kein Mapping existiert"""
        base = ticker.replace('.DE', '').replace('.US', '')
        
        # Umfassendes Mapping: Ticker → Onvista-Basiswert-Name
        ticker_map = {
            # === DEUTSCHE AKTIEN ===
            "RWE": ["RWE"],
            "EOAN": ["E-ON"],
            "SIE": ["Siemens"],
            "RHM": ["Rheinmetall"],
            "MTX": ["MTU-Aero-Engines"],
            "IFX": ["Infineon"],
            "SAP": ["SAP"],
            "BAYN": ["Bayer"],
            "MRK": ["Merck-KGaA"],  # Deutsche Merck!
            "FRE": ["Fresenius"],
            "VOW3": ["Volkswagen-Vz"],
            "BMW": ["BMW"],
            "MBG": ["Mercedes-Benz-Group"],
            "ALV": ["Allianz"],
            "DBK": ["Deutsche-Bank"],
            "MUV2": ["Muenchener-Rueck"],
            "DTE": ["Deutsche-Telekom"],
            "BAS": ["BASF"],
            "LIN": ["Linde"],
            "ADS": ["Adidas"],
            "PUM": ["Puma"],
            "DPW": ["Deutsche-Post"],
            "HEI": ["HeidelbergCement"],
            "HOCN": ["Hochtief"],
            "HYQ": ["Hannover-Rueck"],
            "CBK": ["Commerzbank"],
            "E3N": ["E-ON"],
            "HLI": ["HeidelbergCement"],
            "CLS1": ["Covestro"],
            
            # === US TECH (MEGA CAP) ===
            "AAPL": ["Apple"],
            "APPLE": ["Apple"],
            "MSFT": ["Microsoft"],
            "GOOGL": ["Alphabet-A", "Alphabet", "Google"],
            "GOOG": ["Alphabet-C", "Alphabet"],
            "NVDA": ["NVIDIA"],
            "META": ["Meta-Platforms"],
            "AMZN": ["Amazon"],
            "TSLA": ["Tesla"],
            
            # === US TECH (SEMICONDUCTORS) ===
            "INTC": ["Intel"],
            "AMD": ["AMD"],
            "QCOM": ["Qualcomm"],
            "AVGO": ["Broadcom"],
            "MU": ["Micron-Technology"],
            "LRCX": ["Lam-Research"],
            
            # === US SOFTWARE & CLOUD ===
            "ADBE": ["Adobe"],
            "CRM": ["Salesforce"],
            "NFLX": ["Netflix"],
            "CSCO": ["Cisco-Systems"],
            "WDAY": ["Workday"],
            "VEEV": ["Veeva-Systems"],
            
            # === US HEALTHCARE (PHARMA) ===
            "JNJ": ["Johnson-Johnson"],
            "PFE": ["Pfizer"],  # HIER ist das Problem!
            "UNH": ["UnitedHealth-Group"],
            "MRK": ["Merck-US"],  # US Merck - KORRIGIERT!
            "ABBV": ["AbbVie"],
            "AMGN": ["Amgen"],
            
            # === US HEALTHCARE (DEVICES) ===
            "TMO": ["Thermo-Fisher-Scientific"],
            "EW": ["Edwards-Lifesciences"],
            "BSX": ["Boston-Scientific"],
            "ABT": ["Abbott-Laboratories"],
            "ISRG": ["Intuitive-Surgical"],
            
            # === US FINANCIALS (BANKS) ===
            "JPM": ["JPMorgan-Chase"],
            "BAC": ["Bank-of-America"],
            "WFC": ["Wells-Fargo"],
            "C": ["Citigroup"],
            "GS": ["Goldman-Sachs"],
            "MS": ["Morgan-Stanley"],
            
            # === US FINANCIALS (INSURANCE) ===
            "BRK.B": ["Berkshire-Hathaway-B"],
            "AIG": ["AIG"],
            "ALL": ["Allstate"],
            "PGR": ["Progressive"],
            
            # === US ENERGY ===
            "XOM": ["Exxon-Mobil"],
            "CVX": ["Chevron"],
            "COP": ["ConocoPhillips"],
            "MPC": ["Marathon-Petroleum"],
            "PSX": ["Phillips-66"],
            
            # === US INDUSTRIALS ===
            "BA": ["Boeing"],
            "CAT": ["Caterpillar"],
            "MMM": ["3M"],
            "RTX": ["RTX"],
            "GE": ["General-Electric"],
            "HON": ["Honeywell"],
            
            # === US CONSUMER DISCRETIONARY ===
            "MCD": ["McDonald-s"],
            "NKE": ["Nike"],
            "TJX": ["TJX-Companies"],
            "COST": ["Costco"],
            "HD": ["Home-Depot"],
            
            # === US CONSUMER STAPLES ===
            "PG": ["Procter-Gamble"],
            "KO": ["Coca-Cola"],
            "MO": ["Altria-Group"],
            "PM": ["PHILIP-MORRIS-INTERNATIONAL-INC", "Philip-Morris-International"],
            "WMT": ["Walmart"],
            "PEP": ["PepsiCo"],
            
            # === US MATERIALS ===
            "NEM": ["Newmont"],
            "FCX": ["Freeport-McMoRan"],
            "APD": ["Air-Products-Chemicals"],
            "LYB": ["LyondellBasell"],
            
            # === US COMMUNICATION ===
            "T": ["AT-T"],
            "VZ": ["Verizon"],
            "DIS": ["Walt-Disney"],
            "CMCSA": ["Comcast"],
            "CHTR": ["Charter-Communications"],
            
            # === US UTILITIES ===
            "NEE": ["NextEra-Energy"],
            "DUK": ["Duke-Energy"],
            "SO": ["Southern-Company"],
            "EXC": ["Exelon"],
            "D": ["Dominion-Energy"],
            
            # === US REITS ===
            "PLD": ["Prologis"],
            "AMT": ["American-Tower"],
            "CCI": ["Crown-Castle"],
            "EQIX": ["Equinix"],
            "PSA": ["Public-Storage"],
            
            # === SONSTIGE ===
            "ASML": ["ASML-Holding"],  # Niederländisch
        }
        
        if base in ticker_map:
            return ticker_map[base]
        
        # Fallback: verwende Ticker selbst
        return [base]
    
    def build_search_url(self, underlying: str, option_type: str, 
                        strike_min: float, strike_max: float,
                        days_min: int = 9, days_max: int = 16,
                        broker_filter: bool = True) -> str:
        """Baue onvista URL mit optionalen ING-Filter"""
        
        today = datetime.now()
        maturity_min = (today + timedelta(days=days_min)).strftime("%Y-%m-%d")
        maturity_max = (today + timedelta(days=days_max)).strftime("%Y-%m-%d")
        
        url = f"{self.base_url}/Optionsscheine-auf-{underlying}"
        
        params = [
            "page=0",
            "cols=instrument,strikeAbs,dateMaturity,quote.bid,quote.ask,leverage,omega,impliedVolatilityAsk,spreadAskPct,premiumAsk,nameExerciseStyle,issuer.name,theta",
            f"strikeAbsRange={strike_min};{strike_max}",
            f"dateMaturityRange={maturity_min};{maturity_max}",
            "spreadAskPctRange=0.3;3.0",
            "sort=spreadAskPct",
            "order=ASC"
        ]
        
        # Broker-Filter optional (Fallback ohne ING-Filter)
        if broker_filter:
            params.insert(1, "brokerId=4")  # ING
        
        return url + "?" + "&".join(params)
    
    def validate_underlying(self, actual_underlying: str, expected_underlying: str) -> bool:
        """
        Validiere, ob ein extrahierter Basiswert-String dem erwarteten Basiswert entspricht.
        Diese Version erwartet bereits extrahierten Text (nicht mehr die ganze Zellen-Liste).
        """
        if not actual_underlying or not expected_underlying:
            return False
        return self._matches_expected_string(expected_underlying, actual_underlying)

    def _normalize_name(self, s: str) -> str:
        """Normalize company/underlying names for comparison.
        - lowercase
        - remove punctuation
        - remove common legal suffixes (AG, SE, GmbH, Aktiengesellschaft, etc.)
        - collapse whitespace
        """
        if not s:
            return ""
        t = s.lower()
        # replace common separators
        t = t.replace('&', ' and ')
        # remove parenthesis content
        t = re.sub(r"\(.*?\)", "", t)
        # remove punctuation
        t = re.sub(r"[^a-z0-9äöüß ]+", " ", t)
        # remove common legal forms
        t = re.sub(r"\b(aktiengesellschaft|aktienges|aktien|aktg|ag|se|gmbh|plc|inc|llc|sa|nv)\b", "", t)
        # collapse spaces
        t = re.sub(r"\s+", " ", t).strip()
        return t

    def _matches_expected_string(self, expected: str, actual: str) -> bool:
        """Compare two strings with normalized substring and relaxed fuzzy matching (60%)."""
        if not expected or not actual:
            return False
        e = self._normalize_name(expected)
        a = self._normalize_name(actual)
        if not e or not a:
            return False
        if e in a or a in e:
            return True
        # simple fuzzy: proportion of identical chars over max length
        matches = sum(1 for x, y in zip(e, a) if x == y)
        return (matches / max(len(e), len(a))) >= 0.6
    
    def extract_underlying_from_cells(self, cells: List, col_index: int = 1) -> str:
        """Extrahiere den Basiswert aus einer gegebenen Spalte (default 1)."""
        if not cells:
            return "Unbekannt"
        if 0 <= col_index < len(cells):
            return cells[col_index].get_text(strip=True)
        # fallback: try first non-empty cell that looks like a name
        for c in cells:
            txt = c.get_text(strip=True)
            if re.search(r'[A-Za-zÄÖÜäöüß]', txt):
                return txt
        return "Unbekannt"

    def _detect_underlying_column(self, rows: List, expected: str = None) -> int:
        """Heuristik: Bestimme Spaltenindex, der am ehesten den Basiswert-Namen enthält.
        Wenn `expected` übergeben wird, priorisiere Spalten, die das erwartete Wort enthalten.
        Liefert Index (int) oder 1 als Fallback.
        """
        sample = rows[1: min(12, len(rows))]
        if not sample:
            return 1
        col_scores = {}
        col_empty_count = {}  # Track how many empty cells per column
        expected_norm = self._normalize_name(expected) if expected else None
        
        # Common issuer names to penalize heavily
        common_issuers = {
            'morgan stanley', 'goldman sachs', 'jpmorgan', 'j p morgan', 'jp morgan',
            'deutsche bank', 'unicredit', 'bnp paribas', 'societe generale',
            'vontobel', 'hsbc', 'citigroup', 'barclays', 'credit suisse',
            'ubs', 'commerzbank', 'ing', 'dz bank'
        }
        
        # Exercise style keywords (definitely NOT underlying)
        exercise_styles = {'amerikanisch', 'europäisch', 'europaisch', 'european', 'american'}

        for row in sample:
            cells = row.find_all('td')
            for i, cell in enumerate(cells):
                txt = cell.get_text(strip=True)
                txt_norm = self._normalize_name(txt)
                txt_lower = txt.lower()
                score = 0
                
                # CRITICAL: Empty cells are useless - heavy penalty
                if not txt or len(txt) == 0:
                    col_empty_count[i] = col_empty_count.get(i, 0) + 1
                    score -= 5  # Penalty for empty cell
                    col_scores[i] = col_scores.get(i, 0) + score
                    continue
                
                # Check for exercise style (Amerikanisch/Europäisch) - definitely not underlying
                if txt_lower in exercise_styles:
                    score -= 25  # Massive penalty
                    col_scores[i] = col_scores.get(i, 0) + score
                    continue
                
                # Check if this is likely an issuer column (big penalty)
                is_issuer = any(issuer in txt_norm for issuer in common_issuers)
                if is_issuer:
                    score -= 20  # Heavy penalty for issuer columns
                    col_scores[i] = col_scores.get(i, 0) + score
                    continue
                
                # Penalize columns with currency/numeric indicators (strike, price columns)
                if re.search(r'€|\$|EUR', txt.upper()):
                    score -= 5  # Strong penalty for currency
                    col_scores[i] = col_scores.get(i, 0) + score
                    continue
                    
                if re.search(r'^\d+[,\.]\d+$', txt):  # Pure decimal numbers
                    score -= 5  # Strong penalty for pure numbers
                    col_scores[i] = col_scores.get(i, 0) + score
                    continue
                    
                if '/' in txt and len(txt) < 10:  # Dates
                    score -= 3
                    col_scores[i] = col_scores.get(i, 0) + score
                    continue
                
                # Check for WKN-like codes (6 alphanumeric chars) - likely column 0
                if re.match(r'^[A-Z0-9]{6}$', txt):
                    score -= 10  # Strong penalty for WKN codes
                    col_scores[i] = col_scores.get(i, 0) + score
                    continue  # Don't process further
                
                # Positive signals for underlying column
                has_letters = bool(re.search(r'[A-Za-zÄÖÜäöüß]', txt))
                if has_letters:
                    score += 3  # Base bonus for text
                    
                # Strong bonus for company-name-like text (medium length, mostly letters)
                if 4 < len(txt) < 50 and has_letters:
                    score += 5  # Company names are typically 5-50 chars
                    
                    # Extra bonus if it looks like a real company name (capitalized)
                    if txt[0].isupper():
                        score += 3
                
                # Penalize very short text (likely codes/symbols)
                if len(txt) <= 3:
                    score -= 2
                
                # Big bonus if the expected underlying appears in this cell
                if expected_norm and len(expected_norm) > 0:
                    if expected_norm in txt_norm or txt_norm in expected_norm:
                        score += 20  # Very strong match bonus
                    # Partial match bonus
                    elif len(expected_norm) > 3:
                        words_expected = set(expected_norm.split())
                        words_txt = set(txt_norm.split())
                        common_words = words_expected & words_txt
                        if common_words:
                            score += 10
                
                col_scores[i] = col_scores.get(i, 0) + score

        # Apply penalty for columns that are mostly empty
        for col_idx, empty_count in col_empty_count.items():
            if empty_count > len(sample) * 0.5:  # More than 50% empty
                col_scores[col_idx] = col_scores.get(col_idx, 0) - 30

        # choose column with max score
        if not col_scores:
            return 1
        
        # Debug: print top 3 scoring columns
        if expected:
            sorted_scores = sorted(col_scores.items(), key=lambda x: x[1], reverse=True)[:5]
            # Comment out debug print for production
            # print(f"      DEBUG - Top 5 columns: {sorted_scores}")
        
        best = max(col_scores.items(), key=lambda x: x[1])[0]
        return best

    def _column_looks_like_underlying(self, rows: List, col_index: int) -> bool:
        """Prüfe, ob eine Spalte tatsächlich wie ein Basiswert-Name aussieht."""
        if col_index is None:
            return False
        sample = rows[1: min(12, len(rows))]
        if not sample:
            return False

        text_hits = 0
        numeric_hits = 0
        total = 0

        for row in sample:
            cells = row.find_all('td')
            if col_index >= len(cells):
                continue
            txt = cells[col_index].get_text(strip=True)
            if not txt:
                continue
            total += 1
            txt_lower = txt.lower()

            has_letters = bool(re.search(r'[A-Za-zÄÖÜäöüß]', txt))
            has_digits = bool(re.search(r'\d', txt))
            looks_like_currency = bool(re.search(r'(usd|eur|€|\$)', txt_lower))
            looks_like_date = bool(re.search(r'\d{1,2}\.\d{1,2}\.\d{2,4}', txt))

            if has_digits and (looks_like_currency or looks_like_date):
                numeric_hits += 1
                continue
            if has_digits and not has_letters:
                numeric_hits += 1
                continue
            if has_letters:
                text_hits += 1

        if total == 0:
            return False

        text_ratio = text_hits / total
        numeric_ratio = numeric_hits / total
        return text_ratio >= 0.3 and text_hits >= numeric_hits

    def _normalize_header(self, text: str) -> str:
        """Normalize header text for robust column mapping."""
        if not text:
            return ""
        t = text.lower()
        t = t.replace('%', ' pct ')
        t = re.sub(r'[^a-z0-9äöüß ]+', ' ', t)
        t = re.sub(r'\s+', ' ', t).strip()
        return t

    def _header_alias_map(self) -> Dict[str, set]:
        """Return header alias map for column detection."""
        return {
            "basispreis": {"basispreis", "strike", "strike abs", "strikeabs", "ausuebungspreis"},
            "laufzeit": {"faelligkeit", "faelligkeitsdatum", "laufzeit", "date maturity", "datematurity"},
            "geld": {"geld", "bid", "quote bid", "bidkurs"},
            "brief": {"brief", "ask", "quote ask", "askkurs", "briefkurs"},
            "hebel": {"hebel", "leverage", "einfacher hebel"},
            "omega": {"omega"},
            "impl_vola": {"implizite volatilitaet", "implizite vola", "impl vola", "implied volatility", "implied volatility ask"},
            "spread_pct": {
                "spread",
                "spread ask pct",
                "spread pct",
                "spread in pct",
                "spread in prozent",
                "spread in",
            },
            "aufgeld_pct": {"aufgeld", "aufgeld in pct", "premium", "premium ask"},
            "ausuebung": {"ausuebung", "ausuebungsart", "exercise", "exercise style", "name exercise style"},
            "emittent": {"emittent", "issuer", "issuer name"},
        }

    def _match_alias(self, label: str, alias_map: Dict[str, set]) -> Optional[str]:
        """Match normalized label to alias map key."""
        for key, aliases in alias_map.items():
            if label in aliases:
                return key
        return None

    def _build_header_map(self, rows: List) -> Dict[str, int]:
        """Build a header->index map using table headers or data-label attributes."""
        alias_map = self._header_alias_map()

        header_map: Dict[str, int] = {}
        header_cells = rows[0].find_all(['th', 'td']) if rows else []
        for idx, cell in enumerate(header_cells):
            label = self._normalize_header(cell.get_text(strip=True))
            key = self._match_alias(label, alias_map)
            if key and key not in header_map:
                header_map[key] = idx

        if header_map:
            return header_map

        # Fallback: use data-label/data-title attributes from first data row
        sample_row = rows[1] if len(rows) > 1 else None
        if not sample_row:
            return header_map
        for idx, cell in enumerate(sample_row.find_all('td')):
            label_raw = cell.get("data-label") or cell.get("data-title") or ""
            label = self._normalize_header(label_raw)
            key = self._match_alias(label, alias_map)
            if key and key not in header_map:
                header_map[key] = idx
        return header_map

    def _build_row_map(self, cells: List) -> Dict[str, int]:
        """Build a map from data-label/data-title within a row."""
        alias_map = self._header_alias_map()
        row_map: Dict[str, int] = {}
        for idx, cell in enumerate(cells):
            label_raw = cell.get("data-label") or cell.get("data-title") or ""
            label = self._normalize_header(label_raw)
            key = self._match_alias(label, alias_map)
            if key and key not in row_map:
                row_map[key] = idx
        return row_map

    def _pick_cell_text(
        self,
        cells: List,
        header_map: Dict[str, int],
        key: str,
        fallback_idx: int,
        row_map: Optional[Dict[str, int]] = None,
    ) -> str:
        """Pick text from row map, header map, or fallback index."""
        if row_map:
            idx = row_map.get(key)
            if idx is not None and idx < len(cells):
                return cells[idx].get_text(strip=True)
        idx = header_map.get(key)
        if idx is not None and idx < len(cells):
            return cells[idx].get_text(strip=True)
        if fallback_idx < len(cells):
            return cells[fallback_idx].get_text(strip=True)
        return ""
    
    def build_search_url_variants(self, underlying: str, option_type: str, 
                                   strike_min: float, strike_max: float) -> List[str]:
        """Generiere mehrere URL-Varianten mit verschiedenen Strategien"""
        urls = []
        
        # Variante 1: Standard mit ING-Filter (straff)
        urls.append(("Standard (ING-Filter, 9-16 Tage)", 
                    self.build_search_url(underlying, option_type, strike_min, strike_max, 
                                         days_min=9, days_max=16, broker_filter=True)))
        
        # Variante 2: Ohne ING-Filter (breiter)
        urls.append(("Erweitert (alle Broker, 9-16 Tage)", 
                    self.build_search_url(underlying, option_type, strike_min, strike_max, 
                                         days_min=9, days_max=16, broker_filter=False)))
        
        # Variante 3: Längere Laufzeit ohne ING-Filter (Fallback)
        urls.append(("Fallback (alle Broker, 8-20 Tage)", 
                    self.build_search_url(underlying, option_type, strike_min, strike_max, 
                                         days_min=8, days_max=20, broker_filter=False)))
        
        # Variante 4: Breitere Strike-Range
        expanded_min = int(strike_min * 0.85)
        expanded_max = int(strike_max * 1.15)
        urls.append(("Erweiterte Strikes (alle Broker, 8-20 Tage)", 
                    self.build_search_url(underlying, option_type, expanded_min, expanded_max, 
                                         days_min=8, days_max=20, broker_filter=False)))
        
        return urls
    
    def scrape_options(self, url: str, expected_underlying: str = "", debug: bool = False, retry_count: int = 0) -> List[Dict]:
        """Scrape Optionsscheine von onvista mit Retry-Logik und Basiswert-Validierung"""
        options = []
        found_underlyings = set()  # Track was tatsächlich gefunden wurde
        underlying_col = None
        
        try:
            response = self.session.get(url, timeout=15)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.content, 'html.parser')
            
            if debug:
                with open('onvista_debug.html', 'w', encoding='utf-8') as f:
                    f.write(soup.prettify())
                print("      🔍 Debug: HTML gespeichert als onvista_debug.html")
            
            # Finde Tabelle
            table = soup.find('table')
            if not table:
                if retry_count < self.max_retries:
                    print(f"      ⚠️ Keine Tabelle gefunden (Versuch {retry_count + 1}/{self.max_retries})")
                    time.sleep(self.retry_delay * (2 ** retry_count))  # Exponentielles Backoff
                    return self.scrape_options(url, expected_underlying, debug=debug, retry_count=retry_count + 1)
                else:
                    print("      ❌ Keine Tabelle gefunden nach mehreren Versuchen")
                    return options
            
            rows = table.find_all('tr')
            print(f"      📊 {len(rows)} Zeilen in Tabelle gefunden")

            # Bestimme heuristisch, welche Spalte den Basiswert-Namen enthält
            underlying_col = self._detect_underlying_column(rows, expected=expected_underlying)
            if expected_underlying and not self._column_looks_like_underlying(rows, underlying_col):
                if debug:
                    print("      ⚠️ Basiswert-Spalte wirkt numerisch — Validierung wird übersprungen")
                underlying_col = None

            if debug:
                print(f"      🎯 Detected underlying column: {underlying_col}")

            header_map = self._build_header_map(rows)

            for idx, row in enumerate(rows):
                cells = row.find_all('td')

                if len(cells) < 8:
                    continue

                # VALIDIERUNG: extrahiere Basiswert aus detektierter Spalte (falls vorhanden)
                actual_underlying = None
                if underlying_col is not None:
                    actual_underlying = self.extract_underlying_from_cells(cells, col_index=underlying_col)
                    found_underlyings.add(actual_underlying)

                if debug and idx == 1:  # Erste Datenzeile
                    print(f"\n      🔍 DEBUG - Spalten-Mapping (erste Datenzeile): detected_col={underlying_col}")
                    print(f"      {'─'*74}")
                    for i, cell in enumerate(cells[:15]):
                        cell_text = cell.get_text(strip=True)[:50]
                        flag = '<--' if underlying_col is not None and i == underlying_col else ''
                        print(f"      [{i:2d}] {cell_text:<50} {flag}")
                    print(f"      {'─'*74}\n")

                # Basiswert-Validierung (nur wenn expected_underlying gesetzt)
                if expected_underlying and underlying_col is not None and not self.validate_underlying(actual_underlying, expected_underlying):
                    if debug and idx < 5:  # Nur erste paar Fehler zeigen
                        print(f"      ⚠️ Zeile {idx}: FALSCHER BASISWERT '{actual_underlying}' (erwartet '{expected_underlying}')")
                    continue  # Skip diese Zeile
                
                try:
                    option = self._parse_option_row(cells, header_map=header_map)
                    if option:
                        options.append(option)
                    else:
                        if debug:
                            sample_text = ' | '.join([c.get_text(strip=True)[:30] for c in cells[:6]])
                            print(f"      ⚠️ Zeile {idx}: Parsing lieferte None — Zellen: {sample_text}")
                except Exception as e:
                    if debug:
                        print(f"      ⚠️ Parse-Fehler Zeile {idx}: {e}")
                    continue
            
            # WARNUNG: Falls gefundene Underlyings nicht passen
            if expected_underlying:
                # Use string-based matching to avoid creating fake cell objects
                matching = any(self._matches_expected_string(expected_underlying, u) for u in found_underlyings)

                if underlying_col is None:
                    matching = False

                # If no direct match found in the table, try a lightweight product-page confirmation
                if not matching:
                    expected_norm = self._normalize_name(expected_underlying)
                    # Try up to 5 product links from the table to confirm underlying
                    confirmed = False
                    for row in rows[1: min(6, len(rows))]:
                        cells = row.find_all('td')
                        if not cells:
                            continue
                        wkn_cell = cells[0]
                        a = wkn_cell.find('a')
                        if not a or not a.get('href'):
                            continue
                        href = a.get('href')
                        # Build absolute URL
                        if href.startswith('/'):
                            href = 'https://www.onvista.de' + href
                        try:
                            r = self.session.get(href, timeout=8)
                            if r.status_code != 200:
                                continue
                            page_text = r.text
                            page_norm = self._normalize_name(page_text)
                            if expected_norm in page_norm:
                                confirmed = True
                                break
                        except Exception:
                            continue

                    if not confirmed and found_underlyings:
                        print(f"\n      ⚠️ WARNUNG: Suche nach '{expected_underlying}'")
                        print(f"      ABER Tabelle enthält: {', '.join(list(found_underlyings)[:5])}")
                        print(f"      → {len(options)} Optionsscheine werden IGNORIERT (falsche Underlyings)\n")
                        return []  # Keine falschen Warrants zurückgeben!
                    if confirmed:
                        # confirmed via product page — proceed but log it
                        print(f"\n      ✅ Produkt-Seiten bestätigen Ergebnisse für '{expected_underlying}' — parsing trotz fehlender Spalte")
                    elif underlying_col is None and not found_underlyings:
                        print(f"\n      ⚠️ Basiswert-Spalte fehlt — Ergebnisse ohne Tabellen-Validierung")
            
            if options:
                print(f"      ✅ {len(options)} Optionsscheine geparst")
                if found_underlyings:
                    print(f"      ✓ Basiswert validiert: {', '.join(list(found_underlyings)[:3])}")
            else:
                print(f"      ⚠️ Keine Optionsscheine gefunden")
                if found_underlyings:
                    print(f"      (Tabelle enthielt: {', '.join(list(found_underlyings)[:3])})")
            
            time.sleep(self.delay)
            
        except requests.exceptions.Timeout:
            if retry_count < self.max_retries:
                print(f"      ⏱️ Timeout (Versuch {retry_count + 1}/{self.max_retries})")
                time.sleep(self.retry_delay * (2 ** retry_count))
                return self.scrape_options(url, expected_underlying, debug=debug, retry_count=retry_count + 1)
            else:
                print(f"      ❌ Timeout nach {self.max_retries} Versuchen")
        except requests.exceptions.ConnectionError:
            if retry_count < self.max_retries:
                print(f"      🌐 Verbindungsfehler (Versuch {retry_count + 1}/{self.max_retries})")
                time.sleep(self.retry_delay * (2 ** retry_count))
                return self.scrape_options(url, expected_underlying, debug=debug, retry_count=retry_count + 1)
            else:
                print(f"      ❌ Verbindungsfehler nach {self.max_retries} Versuchen")
        except Exception as e:
            if retry_count < self.max_retries:
                print(f"      ❌ Fehler: {type(e).__name__} (Versuch {retry_count + 1}/{self.max_retries})")
                time.sleep(self.retry_delay * (2 ** retry_count))
                return self.scrape_options(url, expected_underlying, debug=debug, retry_count=retry_count + 1)
            else:
                print(f"      ❌ Fehler nach {self.max_retries} Versuchen: {e}")
        
        return options
    
    def _parse_option_row(self, cells: List, header_map: Optional[Dict[str, int]] = None) -> Optional[Dict]:
        """Parse einzelne Optionsschein-Zeile"""
        try:
            header_map = header_map or {}
            row_map = self._build_row_map(cells)
            # Spalte 0: WKN/Name
            wkn_cell = cells[0]
            wkn_link = wkn_cell.find('a')
            detail_url = None
            if wkn_link:
                wkn_text = wkn_link.get_text(strip=True)
                detail_url = wkn_link.get('href')
                if detail_url and detail_url.startswith('/'):
                    detail_url = f"https://www.onvista.de{detail_url}"
                wkn_match = re.search(r'([A-Z0-9]{6})', wkn_text)
                wkn = wkn_match.group(1) if wkn_match else wkn_text[:6]
            else:
                wkn_text = wkn_cell.get_text(strip=True)
                wkn_match = re.search(r'([A-Z0-9]{6})', wkn_text)
                wkn = wkn_match.group(1) if wkn_match else ""
            
            if not wkn or len(wkn) != 6:
                return None
            
            # Produktname extrahieren
            name = wkn_cell.get_text(strip=True).replace(wkn, '').strip()
            
            def looks_like_money_cell(cell):
                txt = cell.get_text(strip=True)
                return bool(re.search(r'\d+[\.,]?\d*\s*(€|eur|EUR|EUR|EUR)?', txt)) and ('€' in txt or 'EUR' in txt.upper() or re.search(r'\d+[,\.]\d+', txt))

            strike_idx = 2
            maturity_idx = 3
            bid_idx = 4
            ask_idx = 5
            leverage_idx = 6
            omega_idx = 7
            impl_idx = 8
            spread_idx = 9
            premium_idx = 10
            exercise_idx = 11
            emittent_idx = 12

            if len(cells) > 1 and looks_like_money_cell(cells[1]):
                strike_idx = 1
                maturity_idx = 2
                bid_idx = 3
                ask_idx = 4
                leverage_idx = 5
                omega_idx = 6
                impl_idx = 7
                spread_idx = 8
                premium_idx = 9
                exercise_idx = 10
                emittent_idx = 11

            strike_text = self._pick_cell_text(cells, header_map, "basispreis", strike_idx, row_map=row_map)
            maturity = self._pick_cell_text(cells, header_map, "laufzeit", maturity_idx, row_map=row_map)
            bid_text = self._pick_cell_text(cells, header_map, "geld", bid_idx, row_map=row_map)
            ask_text = self._pick_cell_text(cells, header_map, "brief", ask_idx, row_map=row_map)
            leverage_text = self._pick_cell_text(cells, header_map, "hebel", leverage_idx, row_map=row_map)
            omega_text = self._pick_cell_text(cells, header_map, "omega", omega_idx, row_map=row_map)
            impl_text = self._pick_cell_text(cells, header_map, "impl_vola", impl_idx, row_map=row_map)
            spread_text = self._pick_cell_text(cells, header_map, "spread_pct", spread_idx, row_map=row_map)
            premium_text = self._pick_cell_text(cells, header_map, "aufgeld_pct", premium_idx, row_map=row_map)
            exercise = self._pick_cell_text(cells, header_map, "ausuebung", exercise_idx, row_map=row_map)
            emittent = self._pick_cell_text(cells, header_map, "emittent", emittent_idx, row_map=row_map)

            strike = self._parse_number(strike_text) if strike_text else 0
            bid = self._parse_price(bid_text) if bid_text else 0
            ask = self._parse_price(ask_text) if ask_text else 0
            leverage = self._parse_number(leverage_text) if leverage_text else 0
            omega = self._parse_number(omega_text) if omega_text else 0
            impl_vola = self._parse_number(impl_text) if impl_text else 0
            spread_pct = self._parse_number(spread_text) if spread_text else 0
            premium = self._parse_number(premium_text) if premium_text else 0
            
            if strike == 0 or ask == 0:
                return None
            
            mid_price = (bid + ask) / 2 if bid and ask else ask
            
            return {
                'wkn': wkn,
                'name': name,
                'basispreis': strike,
                'laufzeit': maturity,
                'geld': bid,
                'brief': ask,
                'mid_kurs': mid_price,
                'hebel': leverage,
                'omega': omega,
                'impl_vola': impl_vola,
                'spread_pct': spread_pct,
                'spread_abs': (ask - bid) if bid else 0,
                'aufgeld_pct': premium,
                'ausuebung': exercise,
                'emittent': emittent,
                'detail_url': detail_url
            }
            
        except Exception as e:
            return None
    
    def _parse_number(self, text: str) -> float:
        """Parse deutsche Zahlen (1.234,56)"""
        if not text or text == '-' or text == '':
            return 0.0
        text = text.replace('.', '').replace(',', '.').strip()
        text = re.sub(r'[^\d.\-]', '', text)
        try:
            return float(text)
        except:
            return 0.0
    
    def _parse_price(self, text: str) -> float:
        """Parse Preis mit Währung"""
        if not text or text == '-':
            return 0.0
        match = re.search(r'([\d.,]+)', text)
        if match:
            return self._parse_number(match.group(1))
        return 0.0

    def _normalize_label(self, text: str) -> str:
        return re.sub(r'\s+', ' ', text or '').strip().lower()

    def _extract_detail_pairs(self, soup: BeautifulSoup) -> Dict[str, str]:
        pairs = {}
        for row in soup.select("tr"):
            cells = row.find_all(["th", "td"])
            if len(cells) >= 2:
                label = cells[0].get_text(" ", strip=True)
                value = cells[1].get_text(" ", strip=True)
                if label and value:
                    pairs[self._normalize_label(label)] = value
        for dt in soup.select("dt"):
            dd = dt.find_next_sibling("dd")
            if dd:
                label = dt.get_text(" ", strip=True)
                value = dd.get_text(" ", strip=True)
                if label and value:
                    pairs[self._normalize_label(label)] = value
        return pairs

    def _fetch_option_details(self, detail_url: str) -> Dict[str, Optional[float]]:
        if not detail_url:
            return {}
        if detail_url in self.details_cache:
            return self.details_cache[detail_url]
        try:
            resp = self.session.get(detail_url, timeout=10)
            if resp.status_code != 200:
                self.details_cache[detail_url] = {}
                return {}
            soup = BeautifulSoup(resp.text, "html.parser")
            pairs = self._extract_detail_pairs(soup)
            detail_data = {}
            for label, value in pairs.items():
                if "einfacher hebel" in label:
                    detail_data["einfacher_hebel"] = self._parse_number(value)
                if "restlaufzeit" in label:
                    days = self._parse_number(value)
                    detail_data["restlaufzeit_tage"] = int(days) if days else None
                if "letzter handelstag" in label or "bewertungstag" in label:
                    date_match = re.search(r'\d{2}\.\d{2}\.\d{4}', value)
                    if date_match:
                        detail_data["laufzeit_datum"] = date_match.group(0)
            self.details_cache[detail_url] = detail_data
            return detail_data
        except Exception:
            self.details_cache[detail_url] = {}
            return {}

    def enrich_options_with_details(self, options: List[Dict], max_options: Optional[int] = None) -> None:
        candidates = options[:max_options] if max_options else options
        for opt in candidates:
            detail_url = opt.get('detail_url')
            if not detail_url:
                continue
            detail = self._fetch_option_details(detail_url)
            if detail.get("einfacher_hebel"):
                opt['hebel'] = detail["einfacher_hebel"]
            if detail.get("restlaufzeit_tage") is not None:
                opt['restlaufzeit_tage'] = detail["restlaufzeit_tage"]
            if detail.get("laufzeit_datum"):
                opt['laufzeit'] = detail["laufzeit_datum"]
            time.sleep(self.delay / 2)
    
    def calculate_theta_per_day(self, option: Dict, days_to_maturity: int) -> float:
        """
        Berechne Theta (Zeitwertverlust pro Tag)
        Bessere Schätzung: Premium als Zeitwert mit Beschleunigung
        """
        if days_to_maturity <= 0:
            return 0.0
        
        # Premium (Aufgeld) = reiner Zeitwert für OTM Optionen
        premium_value = option['aufgeld_pct'] if option['aufgeld_pct'] > 0 else option['mid_kurs']
        
        # Theta beschleunigt sich exponentiell zum Ende hin (sqrt Factor)
        acceleration_factor = np.sqrt(max(1, days_to_maturity - 1)) / np.sqrt(days_to_maturity)
        theta_per_day = (premium_value / days_to_maturity) * acceleration_factor
        
        return theta_per_day
    
    def calculate_days_to_maturity(self, maturity_str: str) -> int:
        """Berechne verbleibende Tage"""
        try:
            # Format: DD.MM.YYYY oder ähnlich
            maturity_date = datetime.strptime(maturity_str, "%d.%m.%Y")
            days = (maturity_date - datetime.now()).days
            
            # WARNUNG: Falls Laufzeit > 100 Tage, könnte das Parsing falsch sein
            if days > 100:
                print(f"      ⚠️ WARNUNG: Laufzeit {days} Tage ist sehr lang (erwartet 9-16)")
                print(f"         Maturity String: '{maturity_str}'")
                print(f"         Parsed Date: {maturity_date.strftime('%d.%m.%Y')}")
            
            return max(0, days)
        except:
            # Fallback: schätze 12 Tage
            print(f"      ⚠️ Konnte Laufzeit nicht parsen: '{maturity_str}'")
            return 12
    
    def score_option(self, option: Dict, asset_data: Dict, is_call: bool) -> Dict:
        """
        Bewerte Optionsschein nach mehreren Kriterien
        
        Scoring-Faktoren:
        1. Spread (niedriger = besser)
        2. Omega (6-10 = optimal)
        3. Strike-Nähe zum optimalen Strike
        4. Theta/Zeitwertverlust (niedriger = besser)
        5. Implizite Vola (moderat = besser)
        6. Aufgeld (niedriger = besser)
        7. Break-Even Entfernung (realistischer Move erforderlich)
        8. Leverage-Prämie Balance
        """
        
        days = option.get("restlaufzeit_tage")
        if not isinstance(days, (int, float)) or days <= 0:
            days = self.calculate_days_to_maturity(option['laufzeit'])
        theta_per_day = self.calculate_theta_per_day(option, days)
        
        # Break-Even Berechnung
        current_price = asset_data['Close']
        strike = option['basispreis']
        premium = option['brief']
        
        if is_call:
            breakeven = strike + premium
            move_needed = ((breakeven - current_price) / current_price) * 100
        else:
            breakeven = strike - premium
            move_needed = ((current_price - breakeven) / current_price) * 100
        
        # Intrinsic vs. Extrinsic Value
        if is_call:
            intrinsic = max(0, current_price - strike)
        else:
            intrinsic = max(0, strike - current_price)
        extrinsic = premium - intrinsic
        extrinsic_pct = (extrinsic / premium * 100) if premium > 0 else 0
        
        # 1. Spread-Score (0-25 Punkte)
        spread = option['spread_pct']
        if spread <= 0.8:
            spread_score = 25
        elif spread <= 1.2:
            spread_score = 20
        elif spread <= 1.8:
            spread_score = 15
        elif spread <= 2.5:
            spread_score = 10
        else:
            spread_score = 5
        
        # 2. Omega-Score (0-25 Punkte)
        omega = option['omega']
        if 6 <= omega <= 10:
            omega_score = 25
        elif 4 <= omega <= 12:
            omega_score = 20
        elif 3 <= omega <= 15:
            omega_score = 15
        else:
            omega_score = 5
        
        # 3. Strike-Nähe Score (0-20 Punkte)
        target_strike = asset_data['Long_Strike'] if is_call else asset_data['Short_Strike']
        strike_diff_pct = abs(option['basispreis'] - target_strike) / target_strike
        
        if strike_diff_pct <= 0.02:
            strike_score = 20
        elif strike_diff_pct <= 0.05:
            strike_score = 15
        elif strike_diff_pct <= 0.10:
            strike_score = 10
        else:
            strike_score = 5
        
        # 4. Theta-Score (0-15 Punkte) - niedriger ist besser
        theta_pct = (theta_per_day / option['mid_kurs'] * 100) if option['mid_kurs'] > 0 else 100
        
        if theta_pct <= 5:
            theta_score = 15
        elif theta_pct <= 7:
            theta_score = 12
        elif theta_pct <= 10:
            theta_score = 8
        else:
            theta_score = 3
        
        # 5. Implizite Vola Score (0-10 Punkte) - moderat ist gut
        impl_vola = option['impl_vola']
        if 20 <= impl_vola <= 40:
            vola_score = 10
        elif 15 <= impl_vola <= 50:
            vola_score = 7
        else:
            vola_score = 4
        
        # 6. Aufgeld-Score (0-5 Punkte) - niedriger ist besser
        aufgeld = option['aufgeld_pct']
        if aufgeld <= 2:
            aufgeld_score = 5
        elif aufgeld <= 5:
            aufgeld_score = 3
        else:
            aufgeld_score = 1
        
        # 7. Break-Even Score (0-10 Punkte) - Move sollte realistisch sein
        if abs(move_needed) <= 3:
            breakeven_score = 10
        elif abs(move_needed) <= 5:
            breakeven_score = 8
        elif abs(move_needed) <= 8:
            breakeven_score = 5
        else:
            breakeven_score = 2
        
        # 8. Leverage-Prämie Balance (0-5 Punkte)
        leverage_premium_ratio = option['hebel'] / (premium * 100) if premium > 0 else 0
        if leverage_premium_ratio > 0.5:
            leverage_score = 5
        elif leverage_premium_ratio > 0.3:
            leverage_score = 4
        else:
            leverage_score = 2
        
        # Gesamt-Score (max 115 Punkte)
        total_score = (
            spread_score +
            omega_score +
            strike_score +
            theta_score +
            vola_score +
            aufgeld_score +
            breakeven_score +
            leverage_score
        )
        
        return {
            **option,
            'tage_laufzeit': days,
            'theta_pro_tag': round(theta_per_day, 4),
            'theta_pct_pro_tag': round(theta_pct, 2),
            'strike_abweichung_pct': round(strike_diff_pct * 100, 2),
            'breakeven': round(breakeven, 2),
            'move_needed_pct': round(move_needed, 2),
            'intrinsic_value': round(intrinsic, 3),
            'extrinsic_value': round(extrinsic, 3),
            'extrinsic_pct': round(extrinsic_pct, 1),
            'spread_score': spread_score,
            'omega_score': omega_score,
            'strike_score': strike_score,
            'theta_score': theta_score,
            'vola_score': vola_score,
            'aufgeld_score': aufgeld_score,
            'breakeven_score': breakeven_score,
            'leverage_score': leverage_score,
            'gesamt_score': round(total_score, 1)
        }
    
    def find_top_options(self, ticker: str, asset_data: Dict, 
                        option_type: str = "call", debug: bool = False) -> pd.DataFrame:
        """
        Finde Top 3 Optionsscheine für einen Basiswert
        Probiert mehrere Namensvarianten und Such-Strategien mit Fallbacks
        """
        
        underlying_names = self.ticker_to_onvista_name(ticker)
        is_call = option_type.lower() == "call"
        
        # Bestimme Strike-Range
        if is_call:
            target_strike = asset_data['Long_Strike']
        else:
            target_strike = asset_data['Short_Strike']
        
        # Range: ±10% um Target-Strike
        strike_min = int(target_strike * 0.90)
        strike_max = int(target_strike * 1.10)
        
        print(f"\n{'='*80}")
        print(f"🔎 Suche {option_type.upper()}-Optionsscheine für {ticker}")
        print(f"{'='*80}")
        print(f"   Aktueller Kurs: {asset_data['Close']}")
        print(f"   Target Strike: {target_strike}")
        print(f"   Strike-Range: {strike_min} - {strike_max}")
        
        # Probiere verschiedene Namensvarianten
        all_options = []
        success = False
        
        for underlying in underlying_names:
            print(f"\n   Probiere Basiswert-Name: '{underlying}'")
            
            # Generiere mehrere URL-Varianten für Fallback-Strategien
            url_variants = self.build_search_url_variants(underlying, option_type, strike_min, strike_max)
            
            for variant_name, url in url_variants:
                print(f"      Versuche {variant_name}...", end=" ")
                # WICHTIG: Übergebe expected_underlying für Validierung!
                options = self.scrape_options(url, expected_underlying=underlying, 
                                            debug=(debug and len(all_options) == 0 and variant_name.startswith("Standard")))
                
                if options:
                    print(f"✅ {len(options)} gefunden")
                    all_options.extend(options)
                    success = True
                    break  # Erfolg mit diesem Basiswert, gehe zu nächstem Basiswert
                else:
                    print("⚠️ Keine Ergebnisse")
            
            if success:
                print(f"   ✅ {len(all_options)} Optionsscheine mit '{underlying}' insgesamt gefunden")
                break  # Erfolg, keine weiteren Basiswert-Varianten nötig
            else:
                print(f"   ⚠️ Alle Strategien für '{underlying}' fehlgeschlagen")
        
        if not all_options:
            print(f"\n   ❌ Keine Optionsscheine gefunden")
            print(f"   Probierte Basiswert-Namen: {', '.join(underlying_names)}")
            print(f"   Probierte Strategien: Standard, Erweitert, Fallback, Erweiterte Strikes")
            print(f"   💡 Tipp: Prüfe manuell auf onvista.de, wie der Basiswert geschrieben wird")
            return pd.DataFrame()
        
        # Vorfilter für Details (reduziert Requests)
        prefiltered = [
            opt for opt in all_options
            if len(opt.get('wkn', '')) == 6
            and opt.get('basispreis', 0) > 0
            and opt.get('spread_pct', 100) <= 3.0
            and opt.get('omega', 0) >= 2
        ]

        if not prefiltered:
            print(f"   ❌ Keine Optionsscheine nach Qualitätsfilter übrig (von {len(all_options)})")
            return pd.DataFrame()

        self.enrich_options_with_details(prefiltered)

        # Bewerte alle Optionsscheine
        scored_options = []
        for opt in prefiltered:
            scored = self.score_option(opt, asset_data, is_call)
            scored_options.append(scored)
        
        df = pd.DataFrame(scored_options)
        
        # Qualitätsfilter nach Scoring
        original_count = len(df)
        df = df[df['wkn'].str.len() == 6]
        df = df[df['basispreis'] > 0]
        df = df[df['spread_pct'] <= 3.0]
        df = df[df['omega'] >= 2]
        
        if df.empty:
            print(f"   ❌ Keine Optionsscheine nach Qualitätsfilter übrig (von {original_count})")
            return pd.DataFrame()
        
        # Sortiere nach Gesamt-Score
        df = df.sort_values('gesamt_score', ascending=False)
        
        print(f"   ✅ {len(df)} qualifizierte Optionsscheine (von {original_count} vor Filter)")
        
        return df


# ================================
# TEIL 3: HAUPT-ANALYSE
# ================================

def run_complete_analysis(tickers, min_score=7):
    """
    Vollständige Analyse:
    1. Prüfe alle Basiswerte
    2. Für qualifizierte: Finde Top 3 Optionsscheine
    """
    
    print("=" * 80)
    print("🎯 BASISWERT-ANALYSE & OPTIONSSCHEIN-FINDER")
    print("=" * 80)
    print(f"Suche: ING-handelbare Optionsscheine mit 9-16 Tagen Laufzeit")
    print(f"Min. Asset-Score: {min_score}")
    print("=" * 80)
    
    # ===== SCHRITT 1: Basiswerte analysieren =====
    print("\n📊 SCHRITT 1: Analysiere Basiswerte...\n")
    
    results = []
    for ticker in tickers:
        print(f"  Prüfe {ticker}...", end=" ")
        res = check_basiswert(ticker)
        if res:
            results.append(res)
            print(f"Score: {res['Score']} | OS_OK: {'✅' if res['OS_OK'] else '❌'}")
        else:
            print("❌ Keine Daten")
    
    df_assets = pd.DataFrame(results)
    df_assets = df_assets.sort_values(["OS_OK", "Score"], ascending=[False, False])
    
    # Filter nach Score
    df_qualified = df_assets[
        (df_assets["OS_OK"] == True) & 
        (df_assets["Score"] >= min_score)
    ].copy()
    
    if df_qualified.empty:
        print(f"\n⚠️ Keine Basiswerte mit Score >= {min_score} gefunden!")
        print("\nVerfügbare Basiswerte:")
        print(df_assets[["Ticker", "Score", "OS_OK", "Close"]].to_string(index=False))
        return None
    
    print(f"\n✅ {len(df_qualified)} qualifizierte Basiswerte gefunden:\n")
    print(df_qualified[["Ticker", "Score", "Close", "ATR_%", "Long_Strike", "Short_Strike"]].to_string(index=False))
    
    # ===== SCHRITT 2: Top 3 Optionsscheine finden =====
    print("\n\n🎯 SCHRITT 2: Finde Top 3 Optionsscheine pro Basiswert")
    print("=" * 80)
    
    finder = INGOptionsFinder(delay=2.0)
    all_top_options = []
    
    for idx, (_, asset) in enumerate(df_qualified.iterrows()):
        ticker = asset['Ticker']
        is_first = (idx == 0)
        
        # Finde Optionsscheine
        df_options = finder.find_top_options(
            ticker=ticker,
            asset_data=asset,
            option_type="call",
            debug=is_first
        )
        
        if df_options.empty:
            continue
        
        # Top 3 für diesen Basiswert
        top3 = df_options.head(3).copy()
        
        print(f"\n   🏆 TOP 3 für {ticker}:")
        print(f"   {'─'*76}")
        
        for i, (_, opt) in enumerate(top3.iterrows(), 1):
            print(f"\n   {i}. WKN: {opt['wkn']} | Score: {opt['gesamt_score']}/100")
            print(f"      Strike: {opt['basispreis']} | Kurs: {opt['brief']:.3f} EUR | Hebel: {opt['hebel']:.1f}")
            print(f"      Omega: {opt['omega']:.1f} | Spread: {opt['spread_pct']:.2f}% | Laufzeit: {opt['tage_laufzeit']} Tage")
            print(f"      Theta: {opt['theta_pro_tag']:.4f} EUR/Tag ({opt['theta_pct_pro_tag']:.1f}% pro Tag)")
            print(f"      Impl.Vola: {opt['impl_vola']:.1f}% | Aufgeld: {opt['aufgeld_pct']:.1f}%")
            print(f"      Emittent: {opt['emittent']}")
            print(f"      ├─ Spread-Score: {opt['spread_score']}/25")
            print(f"      ├─ Omega-Score: {opt['omega_score']}/25")
            print(f"      ├─ Strike-Score: {opt['strike_score']}/20")
            print(f"      ├─ Theta-Score: {opt['theta_score']}/15")
            print(f"      └─ Gesamt: {opt['gesamt_score']}/100")
        
        # Speichere für finalen Export
        top3['ticker'] = ticker
        top3['asset_score'] = asset['Score']
        all_top_options.append(top3)
        
        time.sleep(1)
    
    # ===== SCHRITT 3: Finale Zusammenfassung =====
    if not all_top_options:
        print("\n❌ Keine Optionsscheine gefunden")
        return None
    
    df_final = pd.concat(all_top_options, ignore_index=True)
    df_final = df_final.sort_values('gesamt_score', ascending=False)
    
    print("\n\n" + "=" * 80)
    print("🏆 FINALE TOP 3 OPTIONSSCHEINE (alle Basiswerte)")
    print("=" * 80)
    
    final_top3 = df_final.head(3)
    
    for i, (_, opt) in enumerate(final_top3.iterrows(), 1):
        print(f"\n{i}. RANG - {opt['ticker']} CALL | WKN: {opt['wkn']}")
        print(f"   {'─'*76}")
        print(f"   Gesamt-Score: {opt['gesamt_score']}/115 ⭐")
        print(f"   Strike: {opt['basispreis']} | Kurs: {opt['brief']:.3f} EUR | Abweichung: {opt['strike_abweichung_pct']:.1f}%")
        print(f"   Omega: {opt['omega']:.1f} | Hebel: {opt['hebel']:.1f} | Spread: {opt['spread_pct']:.2f}%")
        print(f"   Laufzeit: {opt['tage_laufzeit']} Tage | Impl.Vola: {opt['impl_vola']:.1f}% | Aufgeld: {opt['aufgeld_pct']:.1f}%")
        print(f"   Zeitwertverlust: {opt['theta_pro_tag']:.4f} EUR/Tag ({opt['theta_pct_pro_tag']:.1f}%/Tag)")
        print(f"   Break-Even: {opt['breakeven']:.2f} EUR (benötigt {opt['move_needed_pct']:+.1f}% Bewegung)")
        print(f"   Innerer Wert: {opt['intrinsic_value']:.3f} EUR | Zeitwert: {opt['extrinsic_value']:.3f} EUR ({opt['extrinsic_pct']:.0f}%)")
        print(f"   Asset-Score: {opt['asset_score']}/12 | Emittent: {opt['emittent']}")
        print(f"   ├─ Spread-Score: {opt['spread_score']}/25 | Omega-Score: {opt['omega_score']}/25")
        print(f"   ├─ Strike-Score: {opt['strike_score']}/20 | Theta-Score: {opt['theta_score']}/15")
        print(f"   ├─ Vola-Score: {opt['vola_score']}/10 | Aufgeld-Score: {opt['aufgeld_score']}/5")
        print(f"   ├─ Break-Even-Score: {opt['breakeven_score']}/10 | Leverage-Score: {opt['leverage_score']}/5")
    
    # Export
    output_file = 'top_optionsscheine_ing.csv'
    df_final.to_csv(output_file, index=False, encoding='utf-8-sig')
    print(f"\n✅ Vollständige Ergebnisse exportiert: {output_file}")
    
    # Statistiken
    print("\n" + "=" * 80)
    print("📊 STATISTIKEN")
    print("=" * 80)
    print(f"Analysierte Basiswerte: {len(tickers)}")
    print(f"Qualifizierte Basiswerte: {len(df_qualified)}")
    print(f"Gefundene Optionsscheine: {len(df_final)}")
    print(f"Ø Gesamt-Score: {df_final['gesamt_score'].mean():.1f}/100")
    print(f"Ø Spread: {df_final['spread_pct'].mean():.2f}%")
    print(f"Ø Omega: {df_final['omega'].mean():.1f}")
    print(f"Ø Theta pro Tag: {df_final['theta_pct_pro_tag'].mean():.2f}%")
    
    return df_final


# ================================
# MAIN
# ================================

def get_tickers_dynamically() -> List[str]:
    """Hardcoded ticker list covering major sectors - Germany & USA"""
    return [
        # ===== INDICES =====
        "^GDAXI", "^NDX", "^GSPC", "^STOXX50E",
        
        # ===== GERMANY: Technology =====
        "SAP.DE", "SIE.DE", "IFX.DE", "ASML.AS",
        
        # ===== GERMANY: Healthcare =====
        "BAYN.DE", "MRK.DE", "FRE.DE", "CBK.DE",
        
        # ===== GERMANY: Energy & Utilities =====
        "RWE.DE", "EOAN.DE", "VOW3.DE", "E3N.DE",
        
        # ===== GERMANY: Industrials & Defense =====
        "RHM.DE", "MTX.DE", "HEI.DE", "HOCN.DE",
        
        # ===== GERMANY: Finance & Insurance =====
        "ALV.DE", "DBK.DE", "MUV2.DE", "HYQ.DE",
        
        # ===== GERMANY: Consumer & Retail =====
        "BMW.DE", "MBG.DE", "ADS.DE", "PUM.DE", "DPW.DE",
        
        # ===== GERMANY: Materials & Chemicals =====
        "BAS.DE", "LIN.DE", "HLI.DE", "CLS1.DE",
        
        # ===== USA: Technology (Mega Cap) =====
        "APPLE", "MSFT", "GOOGL", "NVDA", "META", "AMZN",
        
        # ===== USA: Technology (Semiconductors & Hardware) =====
        "INTC", "AMD", "QCOM", "AVGO", "MU", "LRCX",
        
        # ===== USA: Software & Cloud =====
        "ADBE", "CRM", "NFLX", "CSCO", "WDAY", "VEEV",
        
        # ===== USA: Healthcare (Pharma & Biotech) =====
        "JNJ", "PFE", "UNH", "MRK", "ABBV", "AMGN",
        
        # ===== USA: Healthcare (Medical Devices) =====
        "TMO", "EW", "BSX", "ABT", "ISRG",
        
        # ===== USA: Financials (Banks) =====
        "JPM", "BAC", "WFC", "C", "GS", "MS",
        
        # ===== USA: Financials (Insurance) =====
        "BRK.B", "AIG", "ALL", "PGR",
        
        # ===== USA: Energy & Oil =====
        "XOM", "CVX", "COP", "MPC", "PSX",
        
        # ===== USA: Industrials & Manufacturing =====
        "BA", "CAT", "MMM", "RTX", "GE", "HON",
        
        # ===== USA: Consumer Discretionary =====
        "TSLA", "MCD", "NKE", "TJX", "COST", "HD",
        
        # ===== USA: Consumer Staples =====
        "PG", "KO", "MO", "PM", "WMT", "PEP",
        
        # ===== USA: Materials & Chemicals =====
        "NEM", "FCX", "APD", "LYB",
        
        # ===== USA: Communication Services =====
        "T", "VZ", "DIS", "CMCSA", "CHTR", "TWX",
        
        # ===== USA: Utilities & Infrastructure =====
        "NEE", "DUK", "SO", "EXC", "D",
        
        # ===== USA: Real Estate (REITs) =====
        "PLD", "AMT", "CCI", "EQIX", "PSA"
    ]


if __name__ == "__main__":
    
    # ===== HOLE TICKER =====
    TICKERS = get_tickers_dynamically()
    
    print("\n" + "=" * 80)
    print(f"✅ {len(TICKERS)} Ticker werden analysiert:")
    print("=" * 80)
    print(", ".join(TICKERS))
    print("=" * 80)
    
    # ===== FÜHRE ANALYSE AUS =====
    df_results = run_complete_analysis(TICKERS, min_score=12)
    
    print("\n" + "=" * 80)
    print("✅ ANALYSE ABGESCHLOSSEN")
    print("=" * 80)
    print("\n💡 HINWEISE:")
    print("- Validiere WKNs manuell auf onvista.de vor Trading")
    print("- Spread und Laufzeit ändern sich täglich")
    print("- Top-Optionsscheine sind nach Gesamt-Score sortiert")
    print("- ING-Filter bevorzugt (straffe Broker-Vorgaben)")
