from __future__ import annotations

import logging
import re
import time
from typing import Dict, Optional

from bs4 import BeautifulSoup

from warrant_scanner.models import OptionQuote
from warrant_scanner.onvista.client import OnvistaClient

logger = logging.getLogger(__name__)


def _normalize_label(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip().lower()


def _extract_pairs(soup: BeautifulSoup) -> Dict[str, str]:
    pairs: dict[str, str] = {}

    for row in soup.select("tr"):
        cells = row.find_all(["th", "td"])
        if len(cells) >= 2:
            label = cells[0].get_text(" ", strip=True)
            value = cells[1].get_text(" ", strip=True)
            if label and value:
                pairs[_normalize_label(label)] = value

    for dt in soup.select("dt"):
        dd = dt.find_next_sibling("dd")
        if dd:
            label = dt.get_text(" ", strip=True)
            value = dd.get_text(" ", strip=True)
            if label and value:
                pairs[_normalize_label(label)] = value

    return pairs


def enrich_with_details(client: OnvistaClient, opt: OptionQuote) -> OptionQuote:
    if not opt.detail_url:
        return opt

    if opt.detail_url in client.details_cache:
        detail = client.details_cache[opt.detail_url]
    else:
        try:
            resp = client.session.get(opt.detail_url, timeout=10)
            if resp.status_code != 200:
                return opt
            soup = BeautifulSoup(resp.text, "html.parser")
            pairs = _extract_pairs(soup)
            detail = {}

            for label, value in pairs.items():
                if "bezugsverhältnis" in label:
                    detail["bezugsverhaeltnis"] = client._parse_number(value)
                if "restlaufzeit" in label:
                    days = client._parse_number(value)
                    detail["restlaufzeit_tage"] = int(days) if days else None
                if "break even" in label or "break-even" in label or "breakeven" in label:
                    detail["break_even"] = client._parse_number(value)

                # try to detect quote currency from detail page text
                if ("aktueller briefkurs" in label or "aktueller geldkurs" in label) and opt.quote_currency is None:
                    if "€" in value or "eur" in value.lower():
                        detail["quote_currency"] = "EUR"
                    if "$" in value or "usd" in value.lower():
                        detail["quote_currency"] = "USD"

            client.details_cache[opt.detail_url] = detail
        except Exception as e:
            logger.debug("detail fetch failed: %s", e)
            detail = {}

    # apply detail values
    if detail.get("bezugsverhaeltnis"):
        opt.bezugsverhaeltnis = float(detail["bezugsverhaeltnis"])
    if detail.get("restlaufzeit_tage") is not None:
        opt.restlaufzeit_tage = int(detail["restlaufzeit_tage"])
    if detail.get("break_even"):
        opt.break_even = float(detail["break_even"])
    if detail.get("quote_currency") and not opt.quote_currency:
        opt.quote_currency = str(detail["quote_currency"])

    time.sleep(client.delay / 2)
    return opt
