from __future__ import annotations

import json
import logging
import os
import re
import time
from dataclasses import asdict
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

import requests
import yfinance as yf
from bs4 import BeautifulSoup

from warrant_scanner.config import ScannerConfig
from warrant_scanner.models import OptionQuote

logger = logging.getLogger(__name__)


class OnvistaClient:
    """Fetch and parse Optionsscheine from onvista.de.

    This is intentionally "best-effort" HTML parsing; use debug logging to inspect.
    """

    def __init__(self, config: ScannerConfig, delay: float | None = None):
        self.config = config
        self.base_url = "https://www.onvista.de/derivate/Optionsscheine"
        self.delay = delay if delay is not None else config.polite_delay_sec
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "de-DE,de;q=0.9,en;q=0.8",
            }
        )

        self.details_cache: dict[str, dict] = {}
        self.mapping_cache_file = "onvista_mapping.json"
        self.onvista_mapping: Dict[str, List[str]] = self._load_onvista_mapping()

    # ---------------- mapping -----------------

    def ticker_to_onvista_name(self, ticker: str) -> List[str]:
        if ticker in self.onvista_mapping and self.onvista_mapping[ticker]:
            return self.onvista_mapping[ticker]

        auto = self._generate_variants_from_yfinance(ticker)
        if auto:
            self.onvista_mapping[ticker] = auto
            self._save_onvista_mapping(self.onvista_mapping)
            return auto

        return [ticker.replace(".DE", "").replace(".US", "")]  # last resort

    def _load_onvista_mapping(self) -> Dict[str, List[str]]:
        try:
            if os.path.exists(self.mapping_cache_file):
                with open(self.mapping_cache_file, "r", encoding="utf-8") as f:
                    return json.load(f)
        except Exception as e:
            logger.debug("Failed to load mapping cache: %s", e)
        return {"^GDAXI": ["DAX"], "^NDX": ["NASDAQ-100"], "^GSPC": ["S-P-500"]}

    def _save_onvista_mapping(self, mapping: Dict[str, List[str]]) -> None:
        try:
            with open(self.mapping_cache_file, "w", encoding="utf-8") as f:
                json.dump(mapping, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.debug("Failed to save mapping cache: %s", e)

    @staticmethod
    def _slugify_name(name: str) -> str:
        if not name:
            return ""
        normalized = name
        for old, new in {"&": " and ", "/": " ", ",": " ", ".": " ", "'": " ", "’": " "}.items():
            normalized = normalized.replace(old, new)
        normalized = re.sub(r"\s+", " ", normalized.strip())
        normalized = normalized.replace(" ", "-")
        normalized = re.sub(r"-+", "-", normalized)
        return normalized.strip("-")

    def _generate_variants_from_yfinance(self, ticker: str) -> List[str]:
        variants: List[str] = []
        base_ticker = ticker.replace(".DE", "").replace(".US", "")
        variants.append(base_ticker)

        try:
            info = yf.Ticker(ticker).info
        except Exception:
            info = {}

        possible = [info.get("shortName", ""), info.get("longName", ""), info.get("displayName", ""), info.get("name", "")]
        for name in possible:
            if not name:
                continue
            variants.append(name)
            variants.append(self._slugify_name(name))

            cleaned = re.sub(
                r"\b(Inc|Incorporated|Corp|Corporation|Company|PLC|N\.V\.|AG|SE|S\.A\.|Ltd|Limited|Holdings?)\b",
                "",
                name,
                flags=re.IGNORECASE,
            ).strip()
            if cleaned:
                variants.append(cleaned)
                variants.append(self._slugify_name(cleaned))

        out: List[str] = []
        seen = set()
        for v in variants:
            v = v.strip()
            if not v:
                continue
            key = v.lower()
            if key in seen:
                continue
            seen.add(key)
            out.append(v)
        return out[:8]

    # ---------------- search urls -----------------

    def build_search_url(
        self,
        underlying: str,
        strike_min: float,
        strike_max: float,
        days_min: int,
        days_max: int,
        broker_filter: bool,
    ) -> str:
        today = datetime.now()
        maturity_min = (today + timedelta(days=days_min)).strftime("%Y-%m-%d")
        maturity_max = (today + timedelta(days=days_max)).strftime("%Y-%m-%d")

        url = f"{self.base_url}/Optionsscheine-auf-{underlying}"

        params = [
            "page=0",
            "cols=instrument,strikeAbs,dateMaturity,quote.bid,quote.ask,leverage,omega,impliedVolatilityAsk,spreadAskPct,premiumAsk,nameExerciseStyle,issuer.name,theta",
            f"strikeAbsRange={strike_min};{strike_max}",
            f"dateMaturityRange={maturity_min};{maturity_max}",
            f"spreadAskPctRange={self.config.spread_ask_pct_min};{self.config.spread_ask_pct_max}",
            "sort=spreadAskPct",
            "order=ASC",
        ]
        if broker_filter:
            params.insert(1, f"brokerId={self.config.broker_id_ing}")
        return url + "?" + "&".join(params)

    def build_search_url_variants(self, underlying: str, strike_min: float, strike_max: float) -> List[Tuple[str, str]]:
        urls: list[tuple[str, str]] = []
        urls.append(
            (
                "Standard (ING-Filter, 9-16 Tage)",
                self.build_search_url(underlying, strike_min, strike_max, self.config.days_min, self.config.days_max, True),
            )
        )
        urls.append(
            (
                "Erweitert (alle Broker, 9-16 Tage)",
                self.build_search_url(underlying, strike_min, strike_max, self.config.days_min, self.config.days_max, False),
            )
        )
        urls.append(
            (
                "Fallback (alle Broker, 8-20 Tage)",
                self.build_search_url(underlying, strike_min, strike_max, 8, 20, False),
            )
        )
        expanded_min = int(strike_min * 0.85)
        expanded_max = int(strike_max * 1.15)
        urls.append(
            (
                "Erweiterte Strikes (alle Broker, 8-20 Tage)",
                self.build_search_url(underlying, expanded_min, expanded_max, 8, 20, False),
            )
        )
        return urls

    # ---------------- parsing helpers -----------------

    def _parse_number(self, text: str) -> float:
        if not text or text in {"-", ""}:
            return 0.0
        text = text.replace(".", "").replace(",", ".").strip()
        text = re.sub(r"[^\d.\-]", "", text)
        try:
            return float(text)
        except Exception:
            return 0.0

    def _parse_price_and_currency(self, text: str) -> tuple[float, Optional[str]]:
        if not text or text == "-":
            return 0.0, None

        # detect currency symbols
        currency = None
        if "€" in text or "eur" in text.lower():
            currency = "EUR"
        elif "$" in text or "usd" in text.lower():
            currency = "USD"

        match = re.search(r"([\d.,]+)", text)
        if match:
            return self._parse_number(match.group(1)), currency
        return 0.0, currency

    # ---------------- scrape -----------------

    def scrape_options(self, url: str, timeout: int | None = None, debug_html_path: str | None = None) -> List[OptionQuote]:
        timeout = timeout or self.config.request_timeout_sec

        for attempt in range(self.config.max_retries):
            try:
                resp = self.session.get(url, timeout=timeout)
                resp.raise_for_status()

                soup = BeautifulSoup(resp.content, "html.parser")
                if debug_html_path:
                    try:
                        with open(debug_html_path, "w", encoding="utf-8") as f:
                            f.write(soup.prettify())
                    except Exception:
                        pass

                table = soup.find("table")
                if not table:
                    raise ValueError("No table found")

                rows = table.find_all("tr")
                options: list[OptionQuote] = []
                for row in rows:
                    cells = row.find_all("td")
                    if len(cells) < 8:
                        continue
                    opt = self._parse_option_row(cells)
                    if opt:
                        options.append(opt)

                time.sleep(self.delay)
                return options

            except Exception as e:
                if attempt + 1 >= self.config.max_retries:
                    logger.info("scrape failed after retries: %s", e)
                    return []
                time.sleep(self.config.retry_delay_sec * (2**attempt))

        return []

    def _parse_option_row(self, cells: List) -> Optional[OptionQuote]:
        try:
            wkn_cell = cells[0]
            wkn_link = wkn_cell.find("a")
            detail_url = None
            if wkn_link:
                wkn_text = wkn_link.get_text(strip=True)
                detail_url = wkn_link.get("href")
                if detail_url and detail_url.startswith("/"):
                    detail_url = f"https://www.onvista.de{detail_url}"
                m = re.search(r"([A-Z0-9]{6})", wkn_text)
                wkn = m.group(1) if m else wkn_text[:6]
            else:
                wkn_text = wkn_cell.get_text(strip=True)
                m = re.search(r"([A-Z0-9]{6})", wkn_text)
                wkn = m.group(1) if m else ""

            if not wkn or len(wkn) != 6:
                return None

            name = wkn_cell.get_text(strip=True).replace(wkn, "").strip()

            strike = self._parse_number(cells[2].get_text(strip=True))
            maturity = cells[3].get_text(strip=True)
            bid, bid_ccy = self._parse_price_and_currency(cells[4].get_text(strip=True))
            ask, ask_ccy = self._parse_price_and_currency(cells[5].get_text(strip=True))
            leverage = self._parse_number(cells[6].get_text(strip=True))
            omega = self._parse_number(cells[7].get_text(strip=True))
            impl_vola = self._parse_number(cells[8].get_text(strip=True)) if len(cells) > 8 else 0.0
            spread_pct = self._parse_number(cells[9].get_text(strip=True)) if len(cells) > 9 else 0.0
            premium_pct = self._parse_number(cells[10].get_text(strip=True)) if len(cells) > 10 else 0.0
            exercise = cells[11].get_text(strip=True) if len(cells) > 11 else ""
            emittent = cells[12].get_text(strip=True) if len(cells) > 12 else ""

            if strike <= 0 or ask <= 0:
                return None

            mid = (bid + ask) / 2 if bid and ask else ask
            quote_ccy = ask_ccy or bid_ccy

            q = OptionQuote(
                wkn=wkn,
                name=name,
                basispreis=strike,
                laufzeit=maturity,
                bid=bid,
                ask=ask,
                mid=mid,
                hebel=leverage,
                omega=omega,
                impl_vola=impl_vola,
                spread_pct=spread_pct,
                spread_abs=(ask - bid) if bid else 0.0,
                aufgeld_pct=premium_pct,
                ausuebung=exercise,
                emittent=emittent,
                detail_url=detail_url,
                quote_currency=quote_ccy,
            )
            logger.debug("parsed option: %s", asdict(q))
            return q
        except Exception:
            return None
