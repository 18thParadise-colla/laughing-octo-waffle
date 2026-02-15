from __future__ import annotations


def get_default_tickers() -> list[str]:
    """Hardcoded ticker list covering major sectors - Germany & USA.

    Kept compatible with the original legacy script list.
    """

    return [
        # ===== INDICES =====
        "^GDAXI",
        "^NDX",
        "^GSPC",
        "^STOXX50E",
        "^DJI",
        "^FTSE",
        "^N225",

        # ===== GERMANY: Technology =====
        "SAP.DE",
        "SIE.DE",
        "IFX.DE",
        "ASML.AS",
        "SY1.DE",
        "BC8.DE",

        # ===== GERMANY: Healthcare =====
        "BAYN.DE",
        "MRK.DE",
        "FRE.DE",
        "CBK.DE",
        "SRT3.DE",
        "QIA.DE",

        # ===== GERMANY: Energy & Utilities =====
        "RWE.DE",
        "EOAN.DE",
        "VOW3.DE",
        "P911.DE",
        "PAH3.DE",

        # ===== GERMANY: Industrials & Defense =====
        "RHM.DE",
        "MTX.DE",
        "HEI.DE",
        "DHER.DE",
        "HEN3.DE",

        # ===== GERMANY: Finance & Insurance =====
        "ALV.DE",
        "DBK.DE",
        "MUV2.DE",
        "HNR1.DE",
        "TKA.DE",

        # ===== GERMANY: Consumer & Retail =====
        "BMW.DE",
        "MBG.DE",
        "ADS.DE",
        "PUM.DE",
        "DHL.DE",
        "BEI.DE",
        "ZAL.DE",

        # ===== GERMANY / FRANCE: Additional Europe Large Caps =====
        "ENR.DE",
        "OR.PA",
        "BNP.PA",
        "DG.PA",
        "AI.PA",

        # ===== GERMANY: Materials & Chemicals =====
        "BAS.DE",
        "LIN.DE",
        "1COV.DE",
        "HFG.DE",
        "WCH.DE",

        # ===== USA: Technology (Mega Cap) =====
        "AAPL",
        "MSFT",
        "GOOGL",
        "NVDA",
        "META",
        "AMZN",
        "ORCL",
        "IBM",
        "GOOG",
        "SHOP",

        # ===== USA: Technology (Semiconductors & Hardware) =====
        "INTC",
        "AMD",
        "QCOM",
        "AVGO",
        "MU",
        "LRCX",
        "TXN",
        "AMAT",
        "ARM",
        "NXPI",
        "ADI",
        "MCHP",
        "ON",

        # ===== USA: Software & Cloud =====
        "ADBE",
        "CRM",
        "NFLX",
        "CSCO",
        "WDAY",
        "VEEV",
        "NOW",
        "PANW",
        "SNOW",
        "PLTR",
        "CRWD",
        "DDOG",
        "MDB",

        # ===== USA: Healthcare (Pharma & Biotech) =====
        "JNJ",
        "PFE",
        "UNH",
        "MRK",
        "ABBV",
        "AMGN",
        "LLY",
        "NVO",
        "BMY",
        "GILD",
        "VRTX",
        "REGN",

        # ===== USA: Healthcare (Medical Devices) =====
        "TMO",
        "EW",
        "BSX",
        "ABT",
        "ISRG",
        "MDT",
        "SYK",
        "ZBH",

        # ===== USA: Financials (Banks) =====
        "JPM",
        "BAC",
        "WFC",
        "C",
        "GS",
        "MS",
        "BLK",
        "SCHW",
        "USB",
        "PNC",
        "BK",

        # ===== USA: Financials (Insurance) =====
        "BRK-B",
        "AIG",
        "ALL",
        "PGR",
        "TRV",
        "CB",

        # ===== USA: Energy & Oil =====
        "XOM",
        "CVX",
        "COP",
        "MPC",
        "PSX",
        "SLB",
        "EOG",
        "KMI",
        "OKE",

        # ===== USA: Industrials & Manufacturing =====
        "BA",
        "CAT",
        "MMM",
        "RTX",
        "GE",
        "HON",
        "DE",
        "ETN",
        "EMR",
        "NOC",

        # ===== USA: Consumer Discretionary =====
        "TSLA",
        "MCD",
        "NKE",
        "TJX",
        "COST",
        "HD",
        "BKNG",
        "SBUX",
        "LOW",
        "CMG",
        "MAR",
        "RCL",

        # ===== USA: Consumer Staples =====
        "PG",
        "KO",
        "MO",
        "PM",
        "WMT",
        "PEP",
        "CL",
        "MDLZ",
        "GIS",
        "KHC",
        "KMB",

        # ===== USA: Materials & Chemicals =====
        "NEM",
        "FCX",
        "APD",
        "LYB",
        "DOW",
        "DD",
        "ECL",

        # ===== USA: Communication Services =====
        "T",
        "VZ",
        "DIS",
        "CMCSA",
        "CHTR",
        "TMUS",
        "WBD",
        "PARA",

        # ===== USA: Utilities & Infrastructure =====
        "NEE",
        "DUK",
        "SO",
        "EXC",
        "D",
        "AEP",
        "SRE",
        "XEL",

        # ===== USA: Real Estate (REITs) =====
        "PLD",
        "AMT",
        "CCI",
        "EQIX",
        "PSA",
        "O",
        "SPG",
        "WELL",

        # ===== EUROPE: Additional Big Players =====
        "MC.PA",
        "AIR.PA",
        "SU.PA",
        "SAN.PA",
        "TTE.PA",
        "RMS.PA",
        "SHEL",
        "NESN.SW",
        "NOVN.SW",
        "ROG.SW",
        "ULVR.L",
        "AZN.L",
        "GSK.L",
        "HSBA.L",
        "RIO.L",
        "BP.L",
    ]
