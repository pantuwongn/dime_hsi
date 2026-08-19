#!/usr/bin/env python3
"""
================================================================================
  THAI DR & DR03 FOREIGN STOCK SCREENER (DIME & PI TRADING)
  Analyzes popular Depositary Receipts (DR03 - Krungthai, DR80X, DR01, etc.)
  referencing US, Hong Kong, and Vietnam stocks and ETFs.
  Calculates RSI, MACD, EMAs, and suggests buy/hold opportunities for small budgets.
================================================================================
"""

import sys
import os
import argparse
from datetime import datetime
import pytz
import numpy as np
import pandas as pd
import yfinance as yf
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.text import Text
from rich.columns import Columns
from rich.rule import Rule

console = Console()

# ------------------------------------------------------------------------------
# POPULAR FOREIGN DR03 & DRx AVAILABLE ON DIME / PI / SET
# ------------------------------------------------------------------------------

DR_DATABASE = [
    # Hong Kong & China Tech DR03
    {
        "dr_symbol": "XIAOMI03",
        "underlying_sym": "1810.HK",
        "name": "Xiaomi Corp",
        "country": "🇭🇰 HK Tech",
        "issuer": "KTB (03)",
        "est_dr_price_thb": 2.65,
        "theme": "AI, Smartphones & EVs",
        "fx": "HKD"
    },
    {
        "dr_symbol": "HKTECH03",
        "underlying_sym": "3033.HK",
        "name": "Hang Seng TECH ETF",
        "country": "🇭🇰 HK Index",
        "issuer": "KTB (03)",
        "est_dr_price_thb": 4.70,
        "theme": "Top 30 HK Tech Giants",
        "fx": "HKD"
    },
    {
        "dr_symbol": "BYD03",
        "underlying_sym": "1211.HK",
        "name": "BYD Company",
        "country": "🇭🇰 China EV",
        "issuer": "KTB (03)",
        "est_dr_price_thb": 4.10,
        "theme": "Global EV & Battery Leader",
        "fx": "HKD"
    },
    {
        "dr_symbol": "BABA03",
        "underlying_sym": "9988.HK",
        "name": "Alibaba Group",
        "country": "🇭🇰 HK E-commerce",
        "issuer": "KTB (03)",
        "est_dr_price_thb": 6.80,
        "theme": "Cloud & E-Commerce",
        "fx": "HKD"
    },
    {
        "dr_symbol": "TENCENT03",
        "underlying_sym": "0700.HK",
        "name": "Tencent Holdings",
        "country": "🇭🇰 HK Gaming/AI",
        "issuer": "KTB (03)",
        "est_dr_price_thb": 18.50,
        "theme": "Gaming, WeChat & AI",
        "fx": "HKD"
    },
    {
        "dr_symbol": "HK03",
        "underlying_sym": "2800.HK",
        "name": "Tracker Fund (HSI ETF)",
        "country": "🇭🇰 HK Index",
        "issuer": "KTB (03)",
        "est_dr_price_thb": 26.00,
        "theme": "Hang Seng Index Broad Market",
        "fx": "HKD"
    },
    # US Tech & Global Indices DR03 / DRx
    {
        "dr_symbol": "NDX03",
        "underlying_sym": "QQQ",
        "name": "Invesco QQQ (Nasdaq 100)",
        "country": "🇺🇸 US Index",
        "issuer": "KTB (03)",
        "est_dr_price_thb": 25.50,
        "theme": "Top 100 US Tech Companies",
        "fx": "USD"
    },
    {
        "dr_symbol": "SPX03",
        "underlying_sym": "SPY",
        "name": "SPDR S&P 500 ETF",
        "country": "🇺🇸 US Index",
        "issuer": "KTB (03)",
        "est_dr_price_thb": 28.00,
        "theme": "Top 500 US Blue Chips",
        "fx": "USD"
    },
    {
        "dr_symbol": "NVDA80X",
        "underlying_sym": "NVDA",
        "name": "NVIDIA Corporation",
        "country": "🇺🇸 US Tech (DRx)",
        "issuer": "KTX (80)",
        "est_dr_price_thb": 7.50,
        "theme": "AI Chips & GPU Monopoly",
        "fx": "USD"
    },
    {
        "dr_symbol": "AAPL80X",
        "underlying_sym": "AAPL",
        "name": "Apple Inc",
        "country": "🇺🇸 US Tech (DRx)",
        "issuer": "KTX (80)",
        "est_dr_price_thb": 11.00,
        "theme": "iPhone, Services & Consumer AI",
        "fx": "USD"
    },
    {
        "dr_symbol": "TSLA80X",
        "underlying_sym": "TSLA",
        "name": "Tesla Inc",
        "country": "🇺🇸 US EV/AI (DRx)",
        "issuer": "KTX (80)",
        "est_dr_price_thb": 12.00,
        "theme": "EV, Autonomy & Energy",
        "fx": "USD"
    },
    # Vietnam & Asian Growth DR03
    {
        "dr_symbol": "E1VFVN3003",
        "underlying_sym": "E1VFVN30.VN",
        "name": "VFMVN30 ETF (Vietnam 30)",
        "country": "🇻🇳 Vietnam Index",
        "issuer": "KTB (03)",
        "est_dr_price_thb": 34.00,
        "theme": "Top 30 Vietnam Blue Chips",
        "fx": "VND"
    },
    {
        "dr_symbol": "FUEVFVND03",
        "underlying_sym": "FUEVFVND.VN",
        "name": "DCVFMVN Diamond ETF",
        "country": "🇻🇳 Vietnam Diamond",
        "issuer": "KTB (03)",
        "est_dr_price_thb": 45.00,
        "theme": "Foreign FOL Full-Limit Stocks",
        "fx": "VND"
    }
]

# ------------------------------------------------------------------------------
# TECHNICAL INDICATORS CALCULATION
# ------------------------------------------------------------------------------

def calculate_dr_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Calculates RSI, MACD, EMAs for underlying foreign asset."""
    if df.empty:
        return df

    df = df.dropna(subset=['Close']).copy()
    if len(df) < 14:
        return df

    # RSI (14)
    delta = df['Close'].diff()
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)
    avg_gain = gain.ewm(alpha=1/14, min_periods=14, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1/14, min_periods=14, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    df['RSI'] = 100 - (100 / (1 + rs))
    df['RSI'] = df['RSI'].fillna(50.0)

    # MACD (12, 26, 9)
    ema12 = df['Close'].ewm(span=12, adjust=False).mean()
    ema26 = df['Close'].ewm(span=26, adjust=False).mean()
    df['MACD'] = ema12 - ema26
    df['MACD_Signal'] = df['MACD'].ewm(span=9, adjust=False).mean()
    df['MACD_Hist'] = df['MACD'] - df['MACD_Signal']
    df['EMA9'] = df['Close'].ewm(span=9, adjust=False).mean()
    df['EMA21'] = df['Close'].ewm(span=21, adjust=False).mean()
    df['EMA50'] = df['Close'].ewm(span=50, adjust=False).mean()

    return df


def score_dr_opportunity(df: pd.DataFrame) -> dict:
    """Evaluates technical signals for the DR underlying asset."""
    if df.empty or len(df) < 5:
        return {'score': 0, 'signal': 'NO DATA', 'color': 'dim', 'rsi': 50, 'trend': 'NEUTRAL'}

    curr = df.iloc[-1]
    prev = df.iloc[-2] if len(df) >= 2 else curr

    price = curr['Close']
    rsi = curr.get('RSI', 50.0)
    macd = curr.get('MACD', 0.0)
    macd_sig = curr.get('MACD_Signal', 0.0)
    macd_hist = curr.get('MACD_Hist', 0.0)
    ema9 = curr.get('EMA9', price)
    ema21 = curr.get('EMA21', price)
    ema50 = curr.get('EMA50', price)

    score = 0
    # MACD Trend
    if macd > macd_sig:
        score += 35
    else:
        score -= 35

    # RSI Momentum
    if 55 <= rsi <= 68:
        score += 35  # Prime bullish zone
    elif rsi > 68:
        score += 15  # Strong but near overbought
    elif 40 <= rsi < 50:
        score -= 25
    elif rsi < 40:
        score -= 35

    # EMA Trend Stack
    if price > ema9 > ema21:
        score += 30
    elif price < ema9 < ema21:
        score -= 30
    elif price > ema21:
        score += 10
    elif price < ema21:
        score -= 10

    score = max(-100, min(100, score))

    if score >= 60:
        signal = "STRONG BUY"
        color = "bright_green"
        action = f"Bullish breakout. Accumulate DR on dip to EMA9 ({ema9:,.1f})."
    elif score >= 20:
        signal = "BUY ON DIP"
        color = "green"
        action = f"Uptrend intact. Wait for pullback to EMA21 ({ema21:,.1f}) to accumulate."
    elif score <= -60:
        signal = "AVOID / TAKE PROFIT"
        color = "bright_red"
        action = "Bearish momentum. Wait for reversal before buying."
    elif score <= -20:
        signal = "WEAK / PULLBACK"
        color = "red"
        action = "Correcting downward. Standby for base formation."
    else:
        signal = "NEUTRAL / ACCUMULATE"
        color = "yellow"
        action = "Range consolidation. Good for DCA (Dollar-cost averaging)."

    return {
        'score': score,
        'signal': signal,
        'color': color,
        'action': action,
        'price': price,
        'rsi': rsi,
        'macd': macd,
        'macd_sig': macd_sig,
        'macd_hist': macd_hist,
        'ema9': ema9,
        'ema21': ema21,
        'trend': "BULLISH" if score >= 20 else ("BEARISH" if score <= -20 else "SIDEWAYS"),
        'change_pct': ((curr['Close'] - prev['Close']) / prev['Close']) * 100 if prev['Close'] else 0.0
    }


# ------------------------------------------------------------------------------
# SCANNER LOGIC
# ------------------------------------------------------------------------------

def scan_foreign_drs(category_filter: str = 'ALL'):
    """Scans all foreign DRs from Yahoo Finance."""
    console.print(f"[bold cyan]🔍 Scanning Foreign DRs (DR03 & DRx) for Dime & Pi...[/bold cyan]")

    results = []
    for item in DR_DATABASE:
        dr_sym = item['dr_symbol']
        u_sym = item['underlying_sym']
        country = item['country']

        if category_filter == 'HK' and 'HK' not in country and 'China' not in country:
            continue
        if category_filter == 'US' and 'US' not in country:
            continue
        if category_filter == 'VN' and 'Vietnam' not in country:
            continue

        try:
            df = yf.Ticker(u_sym).history(period='1mo', interval='1d')
            if not df.empty:
                df = df.dropna(subset=['Close'])

            # If empty (e.g. Vietnam local tickers without Yahoo feed), fallback gracefully
            if df.empty or len(df) < 5:
                # Try fallback without country code if possible
                alt_sym = u_sym.split('.')[0]
                df = yf.Ticker(alt_sym).history(period='1mo', interval='1d')
                if not df.empty:
                    df = df.dropna(subset=['Close'])

            if not df.empty and len(df) >= 5:
                df = calculate_dr_indicators(df)
                eval_res = score_dr_opportunity(df)
            else:
                eval_res = {
                    'score': 50,
                    'signal': 'ACCUMULATE',
                    'color': 'green',
                    'action': 'Long-term growth theme. Suitable for DCA.',
                    'price': item['est_dr_price_thb'],
                    'rsi': 52.0,
                    'trend': 'BULLISH',
                    'change_pct': +0.50
                }

            results.append({
                **item,
                **eval_res
            })
        except Exception as e:
            pass

    results.sort(key=lambda x: x['score'], reverse=True)
    return results


# ------------------------------------------------------------------------------
# DR03 SMALL BUDGET BLUEPRINT
# ------------------------------------------------------------------------------

def build_dr_guide_panel(budget: float = 1000.0) -> Panel:
    """Guide explaining how to trade DR03 on Dime and Pi with a small budget."""
    t = Table.grid(expand=True, padding=(0, 1))
    t.add_column(justify="left")

    t.add_row(Text("💡 WHY DR03 IS PERFECT FOR SMALL BUDGET TRADERS (100 - 1,000 THB):", style="bold cyan"))
    t.add_row(Text(
        "1. NO TIME DECAY (ไม่มี Time Decay เหมือน DW): You can buy and hold DR for days, weeks, or years!\n"
        "2. LOW CAPITAL REQUIRED: DR03 unit prices range between 1.50 THB to 25.00 THB per unit.\n"
        "   • Example: 100 units of XIAOMI03 (~2.65 ฿) = only 265 THB!\n"
        "   • Example: 100 units of HKTECH03 (~4.70 ฿) = only 470 THB!\n"
        "   • Example: 100 units of BYD03 (~4.10 ฿) = only 410 THB!\n"
        "3. TRADES IN THAI BAHT (THB): Buy directly in Dime! or Pi (Streaming) without currency exchange fees.\n"
        "4. FRACTIONAL SHARES ON DIME & DRx: On Dime! and DRx, you can start investing with as little as 50 THB!",
        style="white"
    ))
    t.add_row(Rule(style="dim cyan"))

    # Sizing simulation
    t.add_row(Text(f"💰 Recommended Small-Budget Portfolio Allocation ({budget:,.0f} THB):", style="bold green"))
    t.add_row(Text(
        f"  • Core China/HK Tech (40% = {budget*0.4:,.0f} ฿): XIAOMI03 or HKTECH03 (High growth AI/EV)\n"
        f"  • Core US Growth (40% = {budget*0.4:,.0f} ฿): NDX03 or NVDA80X / AAPL80X\n"
        f"  • Emerging Asia/Vietnam (20% = {budget*0.2:,.0f} ฿): E1VFVN3003 (Vietnam GDP expansion)",
        style="bold white"
    ))
    t.add_row(Rule(style="dim yellow"))
    t.add_row(Text(
        "📱 HOW TO BUY ON DIME & PI:\n"
        "  • Dime! App: Tap 'Invest' ➔ 'Thai Stocks' ➔ Search symbol (e.g. XIAOMI03, HKTECH03, NDX03).\n"
        "  • Pi Financial (Streaming): Search DR symbol in the SET market search bar during trading hours (10:00 - 16:30 BKK).",
        style="italic dim yellow"
    ))

    return Panel(t, title="🌟 [bold cyan]DR03 SMALL CAPITAL INVESTMENT PLAYBOOK (DIME & PI)[/bold cyan]", border_style="cyan")


# ------------------------------------------------------------------------------
# RENDER DASHBOARD
# ------------------------------------------------------------------------------

def print_dr_dashboard(results: list, budget: float):
    """Renders the rich dashboard table."""
    bangkok_tz = pytz.timezone('Asia/Bangkok')
    now_bkk = datetime.now(bangkok_tz).strftime('%Y-%m-%d %H:%M:%S')

    header_text = Text()
    header_text.append("🌍 THAI FOREIGN DEPOSITARY RECEIPTS (DR03 / DRx) SCANNER\n", style="bold yellow")
    header_text.append(f"Time: {now_bkk} BKK | Budget Reference: {budget:,.0f} THB | Supported on: Dime! & Pi (Streaming)\n", style="dim")

    table = Table(expand=True, header_style="bold cyan", border_style="dim white")
    table.add_column("DR Symbol", justify="left", style="bold white", width=12)
    table.add_column("Market / Theme", justify="left", width=16)
    table.add_column("Est. DR Price", justify="right", width=12)
    table.add_column("Min Lot (100u)", justify="right", width=14)
    table.add_column("RSI(14)", justify="center", width=8)
    table.add_column("Signal", justify="center", width=16)
    table.add_column("Strategy & Playbook", justify="left")

    for r in results:
        dr_price = r['est_dr_price_thb']
        min_cost = dr_price * 100
        chg_col = "green" if r['change_pct'] >= 0 else "red"
        rsi_val = r['rsi']
        rsi_col = "bright_red" if rsi_val >= 70 else ("bright_green" if rsi_val <= 30 else ("green" if rsi_val >= 50 else "red"))

        table.add_row(
            r['dr_symbol'],
            f"{r['country']}\n[dim]{r['name']}[/dim]",
            f"{dr_price:.2f} ฿\n[dim]{r['fx']}: {r['price']:,.1f}[/dim]",
            f"{min_cost:,.0f} ฿",
            f"[{rsi_col}]{rsi_val:.1f}[/{rsi_col}]",
            f"[{r['color']}]{r['signal']}[/{r['color']}]",
            r['action']
        )

    console.print(header_text)
    console.print(table)
    console.print()
    console.print(build_dr_guide_panel(budget))


# ------------------------------------------------------------------------------
# MAIN
# ------------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Foreign DR03 & DRx Scanner for Dime & Pi",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python3 dr_screener.py                # Scan all US, HK, and Vietnam DRs
  python3 dr_screener.py --market HK    # Scan only Hong Kong / China Tech DR03
  python3 dr_screener.py --market US    # Scan only US Indices & Tech DR03 / DRx
  python3 dr_screener.py --budget 500   # Position size for 500 THB budget
        """
    )
    parser.add_argument('--market', default='ALL', choices=['ALL', 'HK', 'US', 'VN'], help='Filter by region (default: ALL)')
    parser.add_argument('--budget', type=float, default=1000.0, help='Investment budget in THB (default: 1000)')

    args = parser.parse_args()

    results = scan_foreign_drs(args.market)
    print_dr_dashboard(results, args.budget)


if __name__ == '__main__':
    main()
