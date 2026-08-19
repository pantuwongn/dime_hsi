# 🇭🇰 Hang Seng Index (HSI) & 🇹🇭 SET50 / Thai Stock DW Day Trading Suite

A real-time Python terminal suite for **Day Traders** looking to trade **Derivative Warrants (Call DW / Put DW)** on:
1. **Hang Seng Index (`^HSI`)**
2. **SET50 Index & Thai Stocks** (`S50`, `DELTA`, `GULF`, `ADVANC`, `PTTEP`, `TRUE`, `SIRI`, `TTB`, `WHA`, etc.)

---

## 🚀 Quick Start Commands

### 1. 🇹🇭 Scan All SET50 & Active Thai DW Stocks
```bash
python3 thai_dw_screener.py
```

### 2. 💰 Scan Only Cheap / Low-Priced Thai Stocks (< 5 THB, e.g. SIRI, TTB, WHA, BTS)
```bash
python3 thai_dw_screener.py --cheap-only
```

### 3. 🎯 Deep-Dive Specific Thai Stock (e.g. SIRI or DELTA)
```bash
python3 hsi_analyzer.py --ticker SIRI.BK --timeframe 15m
python3 hsi_analyzer.py --ticker DELTA.BK --timeframe 5m
```

### 4. 🇭🇰 Live Hang Seng Index Dashboard
```bash
python3 hsi_analyzer.py --live
```

1. **Intraday Technical Indicators (via Pandas & NumPy)**:
   - **RSI (14)**: Wilder's smoothing algorithm with visual momentum gauge and overbought/oversold alerts.
   - **MACD (12, 26, 9)**: Fast line, Signal line, Histogram acceleration, Golden Cross and Death Cross detection.
   - **Trend Ribbon (EMA 9, 21, 50)**: Dynamic support/resistance and moving average stack alignment.
   - **ATR (14)**: Average True Range for volatility measurement and dynamic stop-loss buffer calculation.
   - **Intraday Floor Pivot Points**: R2, R1, Pivot Point (P), S1, S2 calculated from daily session data.

2. **Multi-Timeframe Alignment Matrix (1m | 5m | 15m | 60m)**:
   - Checks higher timeframe trend before recommending short-term entries.
   - Avoids "false alarms" and traps on micro-timeframes.

3. **DW Day Trading Recommendation Engine**:
   - 🟢 **BUY CALL DW (STRONG BULLISH)**: Multi-timeframe trend up, MACD expanding above signal, RSI healthy (50–70).
   - 🟢 **CALL BIAS (Wait For Dip)**: Bullish structure, suggests waiting for pullback to EMA9/21.
   - 🟡 **STANDBY / NO TRADE (Chop)**: Conflicting indicators or low volatility (*protects against DW Theta decay*).
   - 🔴 **PUT BIAS (Wait For Rebound)**: Bearish structure, suggests shorting on bounce rejection.
   - 🔴 **BUY PUT DW (STRONG BEARISH)**: Multi-timeframe trend down, MACD expanding below signal, RSI breaking below 50.

4. **Rich Terminal UI**:
   - Modern, color-coded terminal dashboard.
   - HKEX Market Status & Session indicator (HKT vs BKK time).
   - Snapshot mode or live continuous auto-refresh mode.

---

## 📦 Installation

```bash
pip install -r requirements.txt
```

---

## 🚀 Usage

### 1. Single Snapshot Analysis (Default 5-minute primary timeframe)
```bash
python3 hsi_analyzer.py
```

### 2. Live Auto-Refresh Dashboard (Refreshes every 15 seconds)
```bash
python3 hsi_analyzer.py --live
```

### 3. Custom Refresh Rate (e.g., every 5 seconds)
```bash
python3 hsi_analyzer.py --live --refresh 5
```

### 4. Fast Scalping Mode (1-minute primary timeframe)
```bash
python3 hsi_analyzer.py --timeframe 1m
```

### 5. Swing Day Trading Mode (15-minute primary timeframe)
```bash
python3 hsi_analyzer.py --timeframe 15m
```

### 6. View Recent Candle History Table
```bash
python3 hsi_analyzer.py --history 5
```

---

## 📊 Indicator & DW Signal Interpretation

| Signal | Market Condition | RSI (14) | MACD | Recommended DW Action |
| :--- | :--- | :--- | :--- | :--- |
| 🟢 **STRONG CALL** | Price > EMA9 > EMA21 | 55 - 70 (Rising) | MACD > Signal & Hist > 0 | **Buy Call DW** on EMA9 dip or R1 breakout |
| 🟢 **CALL BIAS** | Price > EMA21 | 50 - 60 | MACD > Signal | Wait for 5m pullback to EMA9/21 to enter Call |
| 🟡 **STANDBY / CHOP** | Price whipsawing around EMA21 | 45 - 55 (Flat) | MACD ~ Signal | **NO TRADE** — avoid DW Theta (time decay) |
| 🔴 **PUT BIAS** | Price < EMA21 | 40 - 50 | MACD < Signal | Wait for 5m rebound to EMA9/21 rejection to enter Put |
| 🔴 **STRONG PUT** | Price < EMA9 < EMA21 | 30 - 45 (Falling) | MACD < Signal & Hist < 0 | **Buy Put DW** on EMA9 rejection or S1 breakdown |

---

## ⏰ Hong Kong Stock Exchange (HKEX) Trading Hours

| Session | Hong Kong Time (HKT, UTC+8) | Bangkok Time (BKK, UTC+7) | Day Trading Note |
| :--- | :--- | :--- | :--- |
| **Morning Open** | 09:30 - 12:00 | 08:30 - 11:00 | Highest volatility & DW volume |
| **Lunch Break** | 12:00 - 13:00 | 11:00 - 12:00 | Market paused |
| **Afternoon Session** | 13:00 - 16:00 | 12:00 - 15:00 | Trend continuation / Afternoon breakout |
| **Closing Auction** | 16:00 - 16:10 | 15:00 - 15:10 | Day traders should close positions before close |

---

## 💡 Pro Tips for HSI DW Traders

1. **Select High Sensitivity DWs**: Look for DWs with Effective Gearing of 8x–15x and Sensitivity near 1.0 (moves 1 tick per 20–30 HSI points).
2. **Never Hold DWs in Chop**: When the script displays `STANDBY / NO TRADE`, staying in cash preserves capital from Theta decay.
3. **Respect Stop Losses**: Always set stop loss at the indicated support/resistance or ATR level.
4. **Close Intraday**: Avoid holding HSI DW overnight to eliminate overnight gap risk from global markets.
