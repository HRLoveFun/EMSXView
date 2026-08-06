"""
Broker-algorithm mappings, currency-region mappings, and closing auction times.

Copied from D:\\Evaluation\\src\\mapping.py to keep the EMSX pipeline
self-contained. These are required by fill_processor.py for algo
classification, currency column derivation, and closing-auction detection.
"""

from __future__ import annotations

from typing import Dict, List


# ═══════════════════════════════════════════════════════════════════════════
# Closing Auction Times by Exchange
# ═══════════════════════════════════════════════════════════════════════════
# Exchange code → local closing auction start time (HH:MM:SS).
# Used by add_mkt_timestamp_columns() to flag is_closing_auction.

closing_auction_times: Dict[str, str] = {
    # APAC
    "AU": "16:10:00",
    "NZ": "16:45:00",
    "CH": "15:00:00",
    "C1": "15:00:00",   # 沪港通（上交所）收盘集合竞价 15:00
    "HK": "16:00:00",
    "IJ": "16:00:00",
    "IN": "15:31:00",
    "JP": "15:30:00",
    "KS": "15:30:00",
    "MK": "16:50:00",
    "SP": "17:04:00",
    # EMEA (northern)
    "DC": "16:59:00",
    "LN": "16:35:00",
    "NO": "16:25:00",
    "PW": "17:00:00",
    "SJ": "17:00:00",
    "SS": "17:30:00",
    "SW": "17:30:00",
    "IT": "17:14:00",
    # EMEA (central/southern)
    "AV": "17:35:00",
    "BB": "17:35:00",
    "FH": "17:29:00",
    "FP": "17:35:00",
    "GA": "17:09:00",
    "GR": "17:35:00",
    "ID": "17:30:00",
    "IM": "17:30:00",
    "NA": "17:34:00",
    "PL": "17:34:00",
    "SM": "17:34:00",
    # Americas
    "BZ": "16:55:00",
    "CN": "16:00:00",
    "MM": "14:00:00",
    "US": "16:00:00",
}

# Exchanges where exec time needs +1min adjustment for auction detection
EXCHANGE_AUCTION_TIME_ADJUST: set = {"JP", "PW", "SS", "BZ", "CN", "MM", "US"}


# ═══════════════════════════════════════════════════════════════════════════
# Currency → Region Mapping
# ═══════════════════════════════════════════════════════════════════════════

currency_region: Dict[str, str] = {
    "AUD": "APAC",
    "IDR": "APAC",
    "INR": "APAC",
    "JPY": "APAC",
    "KRW": "APAC",
    "MYR": "APAC",
    "NZD": "APAC",
    "SGD": "APAC",
    "CHF": "EMEA",
    "DKK": "EMEA",
    "EUR": "EMEA",
    "GBp": "EMEA",
    "ILS": "EMEA",
    "NOK": "EMEA",
    "PLN": "EMEA",
    "SEK": "EMEA",
    "ZAr": "EMEA",
    "BRL": "NSA",
    "CAD": "NSA",
    "MXN": "NSA",
    "USD": "NSA",
}


# ═══════════════════════════════════════════════════════════════════════════
# Broker → Algorithm Type Mappings
# ═══════════════════════════════════════════════════════════════════════════
# Aggregated across APAC, EMEA, Americas.

vwap: Dict[str, List[str]] = {
    "EQ-BNP": ["VWAP"],
    "EQ-CITI": ["VWAP"],
    "EQ-CLSA": ["VWAP_ADP"],
    "EQ-CLSA-EU": ["VWAP_ADP"],
    "EQ-DAIWA": ["VWAP"],
    "EQ-GS": ["VWAP"],
    "EQ-HSBC": ["VWAP."],
    "EQ-INSTNET": ["VWAP"],
    "EQ-JPM": ["VWAP"],
    "EQ-MACQ": ["VWAP"],
    "EQ-MIZUHO": ["VWAP"],
    "EQ-ML": ["VWAP"],
    "EQ-MS": ["VWAP"],
    "EQ-NOMURA": ["VWAP"],
    "EQ-UBS": ["VWAP"],
    "EQ-BARCLAY": ["VWAP", "VWAP-EU"],
    "EQ-SEB": ["VWAP"],
    "EQ-SG": ["VWAP"],
    "EQ-BMO": ["VWAP"],
    "EQ-CS": ["VWAP"],
    "EQ-ML-BR": ["VWAP"],
    "EQ-RBC": ["VWAP"],
    "EQ-SCOTIA": ["VWAP"],
    "EQ-TD": ["VWAP"],
    "EQ-WFC": ["VWAP"],

    "EQ-CICC": ["VWAP"],
    "EQ-ICBCI": ["VWAP"],
    "EQ-BOCI": ["VWAP"],
    "EQ-ABCI": ["VWAP"],
}

twap: Dict[str, List[str]] = {
    "EQ-BNP": ["TWAP"],
    "EQ-CITI": ["TWAP"],
    "EQ-CLSA": ["TWAP_ADP"],
    "EQ-DAIWA": ["TWAP"],
    "EQ-GS": ["TWAP"],
    "EQ-HSBC": ["TWAP."],
    "EQ-INSTNET": ["TWAP"],
    "EQ-JPM": ["TWAP"],
    "EQ-MACQ": ["TWAP"],
    "EQ-MIZUHO": ["TWAP"],
    "EQ-ML": ["TWAP"],
    "EQ-MS": ["TWAP"],
    "EQ-NOMURA": ["TWAP"],
    "EQ-UBS": ["TWAP"],
    "EQ-BARCLAY": ["TWAP", "TWAP-EU"],
    "EQ-SEB": ["TWAP"],
    "EQ-SG": ["TWAP"],
    "EQ-BARCLAYS": ["TWAP"],
    "EQ-BMO": ["TWAP"],
    "EQ-CS": ["TWAP"],
    "EQ-ML-BR": ["TWAP"],
    "EQ-RBC": ["TWAP"],
    "EQ-SCOTIA": ["TWAP"],
    "EQ-TD": ["TWAP"],
    "EQ-WFC": ["TWAP"],
}

close: Dict[str, List[str]] = {
    "EQ-BARCLAY": ["AuctionEU", "TClose"],
    "EQ-BMO": ["AUCTION", "OnClose"],
    "EQ-BNP": ["MOC"],
    "EQ-CITI": ["MOC", "Close"],
    "EQ-CLSA": ["MOC_ADP"],
    "EQ-CLSA-EU": ["MOC_ADP"],
    "EQ-DAIWA": ["CLOSE"],
    "EQ-GS": ["AUCTION", "Navigator"],
    "EQ-HSBC": ["HSBCCLOSE"],
    "EQ-INSTNET": ["AUCTION", "TARGETCL"],
    "EQ-JPM": ["CLOSE"],
    "EQ-MACQ": ["CLOSEPLUS"],
    "EQ-MIZUHO": ["TgtClose"],
    "EQ-ML": ["QMOC_APEU", "QMOC"],
    "EQ-MS": ["CLOSE"],
    "EQ-NOMURA": ["Custom", "TARGETCLS"],
    "EQ-UBS": ["CUSTOM2", "AT CLOSE"],
    "EQ-SEB": ["TGTCLOSE"],
    "EQ-SG": ["CLOSE"],
    "EQ-CS": ["CLOSE"],
    "EQ-ML-BR": ["QMOC"],
    "EQ-RBC": ["CLOSER"],
    "EQ-SCOTIA": ["MOCDirect", "SmrtClose"],
    "EQ-TD": ["CLOSE"],
    "EQ-WFC": ["CLOSE"],


    "EQ-CICC": ["CLOSETGT"],
    "EQ-ICBCI": ["CLOSE"],
    "EQ-BOCI": ["TARGETCLO"],
    "EQ-ABCI": ["CLOSE"],

}

pov: Dict[str, List[str]] = {
    "EQ-BNP": ["POV"],
    "EQ-CITI": ["PART"],
    "EQ-CLSA": ["VolinLine"],
    "EQ-DAIWA": ["POV"],
    "EQ-GS": ["PARTCIPTE"],
    "EQ-HSBC": ["POV."],
    "EQ-INSTNET": ["PART"],
    "EQ-JPM": ["POV"],
    "EQ-MACQ": ["VOLINLINE"],
    "EQ-MIZUHO": ["VolInline"],
    "EQ-ML": ["POV"],
    "EQ-MS": ["TARGETPOV"],
    "EQ-NOMURA": ["With-Vol"],
    "EQ-UBS": ["V-INLINE"],
    "EQ-BARCLAY": ["With-Vol"],
    "EQ-CLSA-EU": ["INLN_ADP"],
    "EQ-SEB": ["PRTICP"],
    "EQ-SG": ["WVOL"],
    "EQ-BMO": ["POV"],
    "EQ-CS": ["VOLINLINE"],
    "EQ-ML-BR": ["POV"],
    "EQ-RBC": ["POV"],
    "EQ-SCOTIA": ["POV"],
    "EQ-TD": ["POV"],
    "EQ-WFC": ["POV"],
}
