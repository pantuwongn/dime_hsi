#!/usr/bin/env python3
"""
================================================================================
  THAI STOCK & SET50 DW SCREENER & DAY TRADING ANALYZER
  Scans SET50 and active Thai DW underlying stocks.
  Calculates RSI, MACD, EMAs, and suggests Call / Put DW trading opportunities
  specifically tailored for small-budget traders.
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
# POPULAR THAI STOCKS WITH ACTIVE DERIVATIVE WARRANTS (DWs)
# ------------------------------------------------------------------------------

WATCHLIST_SET50 = [
    {"symbol": "^SET.BK", "name": "SET50 Index", "sector": "Benchmark Index", "tier": "S50 DW"},
    {"symbol": "DELTA.BK", "name": "DELTA", "sector": "Tech / Electronics", "tier": "High Volatility"},
    {"symbol": "GULF.BK", "name": "GULF", "sector": "Energy / Power", "tier": "SET50 Leader"},
    {"symbol": "ADVANC.BK", "name": "ADVANC", "sector": "Telecom", "tier": "SET50 Leader"},
    {"symbol": "KBANK.BK", "name": "KBANK", "sector": "Banking", "tier": "SET50 Leader"},
    {"symbol": "CPALL.BK", "name": "CPALL", "sector": "Commerce", "tier": "SET50 Leader"},
    {"symbol": "PTTEP.BK", "name": "PTTEP", "sector": "Energy / Oil", "tier": "Commodity Play"},
    {"symbol": "PTT.BK", "name": "PTT", "sector": "Energy / Oil", "tier": "SET50 Leader"},
    {"symbol": "SCB.BK", "name": "SCB", "sector": "Banking", "tier": "SET50 Leader"},
    {"symbol": "KTB.BK", "name": "KTB", "sector": "Banking", "tier": "Active DW"},
    {"symbol": "BDMS.BK", "name": "BDMS", "sector": "Healthcare", "tier": "Defensive"},
    {"symbol": "AOT.BK", "name": "AOT", "sector": "Tourism / Airport", "tier": "SET50 Leader"},
    {"symbol": "TRUE.BK", "name": "TRUE", "sector": "Telecom", "tier": "Mid Price (~13 THB)"},
    {"symbol": "HANA.BK", "name": "HANA", "sector": "Electronics", "tier": "High Beta Play"},
    {"symbol": "KCE.BK", "name": "KCE", "sector": "Electronics", "tier": "High Beta Play"},
    {"symbol": "MINT.BK", "name": "MINT", "sector": "Hotel / Food", "tier": "Tourism Play"},
    {"symbol": "BANPU.BK", "name": "BANPU", "sector": "Energy / Coal", "tier": "Mid Price (~5 THB)"},
    {"symbol": "WHA.BK", "name": "WHA", "sector": "Industrial Estate", "tier": "Low Price (~4.9 THB)"},
    {"symbol": "TTB.BK", "name": "TTB", "sector": "Banking", "tier": "Low Price (~2.8 THB)"},
    {"symbol": "SIRI.BK", "name": "SIRI", "sector": "Property", "tier": "Penny Stock (~1.5 THB)"},
    {"symbol": "BTS.BK", "name": "BTS", "sector": "Transport", "tier": "Mid Price (~2.1 THB)"},
]

# ------------------------------------------------------------------------------
# TECHNICAL INDICATORS
# ------------------------------------------------------------------------------

def calculate_technical_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Calculates RSI, MACD, EMAs, and ATR for a stock dataframe."""
    if df.empty:
        return df

    df = df.dropna(subset=['Close']).copy()
    if len(df) < 15:
        return df

    # 1. RSI (14-period Wilder's Smoothing)
    delta = df['Close'].diff()
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)
    avg_gain = gain.ewm(alpha=1/14, min_periods=14, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1/14, min_periods=14, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    df['RSI'] = 100 - (100 / (1 + rs))
    df['RSI'] = df['RSI'].fillna(50.0)

    # 2. MACD (12, 26, 9)
    ema12 = df['Close'].ewm(span=12, adjust=False).mean()
    ema26 = df['Close'].ewm(span=26, adjust=False).mean()
    df['MACD'] = ema12 - ema26
    df['MACD_Signal'] = df['MACD'].ewm(span=9, adjust=False).mean()
    df['MACD_Hist'] = df['MACD'] - df['MACD_Signal']
    df['MACD_Hist_Prev'] = df['MACD_Hist'].shift(1).fillna(0.0)

    # 3. EMAs (9, 21, 50)
    df['EMA9'] = df['Close'].ewm(span=9, adjust=False).mean()
    df['EMA21'] = df['Close'].ewm(span=21, adjust=False).mean()
    df['EMA50'] = df['Close'].ewm(span=50, adjust=False).mean()

    # 4. ATR (14)
    high_low = df['High'] - df['Low']
    high_close = (df['High'] - df['Close'].shift(1)).abs()
    low_close = (df['Low'] - df['Close'].shift(1)).abs()
    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    df['ATR'] = tr.ewm(alpha=1/14, min_periods=14, adjust=False).mean()

    return df


def score_stock_opportunity(df: pd.DataFrame) -> dict:
    """Evaluates stock technicals and generates a DW trading recommendation."""
    if df.empty or len(df) < 5:
        return {'score': 0, 'signal': 'NO DATA', 'color': 'dim', 'rsi': 50, 'macd_trend': 'FLAT'}

    curr = df.iloc[-1]
    prev = df.iloc[-2] if len(df) >= 2 else curr

    price = curr['Close']
    rsi = curr.get('RSI', 50.0)
    macd = curr.get('MACD', 0.0)
    macd_sig = curr.get('MACD_Signal', 0.0)
    macd_hist = curr.get('MACD_Hist', 0.0)
    macd_hist_prev = curr.get('MACD_Hist_Prev', 0.0)
    ema9 = curr.get('EMA9', price)
    ema21 = curr.get('EMA21', price)
    ema50 = curr.get('EMA50', price)
    atr = curr.get('ATR', price * 0.02)

    score = 0

    # MACD momentum
    if prev['MACD'] <= prev['MACD_Signal'] and macd > macd_sig:
        score += 40  # Fresh golden cross
    elif prev['MACD'] >= prev['MACD_Signal'] and macd < macd_sig:
        score -= 40  # Fresh death cross
    elif macd > macd_sig:
        score += 25 if macd_hist > macd_hist_prev else 15
    else:
        score -= 25 if macd_hist < macd_hist_prev else 15

    # RSI momentum
    if 55 <= rsi < 72:
        score += 30  # Healthy bullish trend
    elif rsi >= 72:
        score += 5   # Overbought caution
    elif 30 < rsi <= 45:
        score -= 30  # Healthy bearish trend
    elif rsi <= 30:
        score -= 5   # Oversold caution
    else:
        score += 0   # Neutral (45-55)

    # EMA alignment
    if price > ema9 > ema21:
        score += 30
    elif price < ema9 < ema21:
        score -= 30
    elif price > ema21:
        score += 10
    elif price < ema21:
        score -= 10

    score = max(-100, min(100, score))

    if score >= 55:
        signal = "BUY CALL DW"
        color = "bright_green"
        action = f"Bullish momentum. Enter Call DW. Stop Loss: {price - (atr * 0.8):.2f}"
    elif score >= 20:
        signal = "CALL BIAS"
        color = "green"
        action = f"Uptrend intact. Wait for pullback to EMA9 ({ema9:.2f}) to buy Call."
    elif score <= -55:
        signal = "BUY PUT DW"
        color = "bright_red"
        action = f"Bearish breakdown. Enter Put DW. Stop Loss: {price + (atr * 0.8):.2f}"
    elif score <= -20:
        signal = "PUT BIAS"
        color = "red"
        action = f"Downtrend intact. Wait for bounce to EMA9 ({ema9:.2f}) to buy Put."
    else:
        signal = "NEUTRAL / WAIT"
        color = "yellow"
        action = "Sideways chop. Avoid trading DW to prevent Theta (time decay) loss."

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
        'ema50': ema50,
        'atr': atr,
        'change_pct': ((curr['Close'] - prev['Close']) / prev['Close']) * 100 if prev['Close'] else 0.0
    }


# ------------------------------------------------------------------------------
# SCANNER LOGIC
# ------------------------------------------------------------------------------

def scan_thai_stocks(timeframe: str = '15m', cheap_only: bool = False):
    """Fetches data and scans all watchlist stocks."""
    console.print(f"[bold cyan]🔍 Scanning SET50 & Thai DW stocks on {timeframe} timeframe...[/bold cyan]")

    results = []
    period = '5d' if timeframe in ['5m', '15m', '30m'] else '1mo'

    for item in WATCHLIST_SET50:
        sym = item['symbol']
        name = item['name']
        try:
            df = yf.Ticker(sym).history(period=period, interval=timeframe)
            if not df.empty:
                df = df.dropna(subset=['Close'])
            if not df.empty and len(df) >= 15:
                df = calculate_technical_indicators(df)
                eval_res = score_stock_opportunity(df)
                price = eval_res['price']

                # Filter if cheap_only is requested (< 5.0 THB)
                if cheap_only and price >= 5.0:
                    continue

                results.append({
                    **item,
                    **eval_res,
                    'df': df
                })
        except Exception as e:
            pass

    # Sort results by absolute score (strongest opportunities first)
    results.sort(key=lambda x: x['score'], reverse=True)
    return results


# ------------------------------------------------------------------------------
# SMALL BUDGET DW GUIDE & BUDGET CALCULATOR
# ------------------------------------------------------------------------------

def build_budget_guide_panel(budget: float = 1000.0) -> Panel:
    """Generates the educational guide explaining DW trading on a small budget."""
    t = Table.grid(expand=True, padding=(0, 1))
    t.add_column(justify="left")

    t.add_row(Text("💡 WHY SMALL BUDGET TRADERS CAN TRADE DWS ON HIGH-PRICED STOCKS:", style="bold cyan"))
    t.add_row(Text(
        "• In the Thai stock market, Derivative Warrants (DWs) trade at only ~0.15 - 0.80 THB per unit.\n"
        "• 1 Board Lot = 100 units. That means the minimum order cost is only ~15 - 80 THB!\n"
        "• Even for high-priced stocks like DELTA (264 THB) or ADVANC (362 THB), their DWs (e.g. DELT01C..., ADVA13P...)\n"
        "  only cost around 0.25 - 0.50 THB per unit. You do NOT need 26,000 THB to trade DELTA!",
        style="white"
    ))
    t.add_row(Rule(style="dim cyan"))

    # Position sizing simulation for given budget
    avg_dw_price = 0.35  # Typical DW price in THB
    units_affordable = int((budget / avg_dw_price) // 100) * 100  # Rounded to 100 lots
    actual_cost = units_affordable * avg_dw_price

    calc_text = (
        f"📊 Example Position Sizing for {budget:,.0f} THB Budget:\n"
        f"  • Estimated DW unit price: {avg_dw_price:.2f} THB (Typical ATM DW)\n"
        f"  • Units you can buy: {units_affordable:,.0f} units ({units_affordable // 100} lots)\n"
        f"  • Total Capital Used: {actual_cost:,.2f} THB\n"
        f"  • If underlying moves +2% (with ~5x Gearing): DW moves ~+10% ➔ Profit = +{actual_cost * 0.10:,.2f} THB\n"
        f"  • Stop Loss Rule (-5% on DW): Max Risk = -{actual_cost * 0.05:,.2f} THB"
    )
    t.add_row(Text(calc_text, style="bold green"))
    t.add_row(Rule(style="dim yellow"))

    t.add_row(Text("🎯 4 GOLDEN RULES FOR SMALL BUDGET DW TRADERS:", style="bold yellow"))
    t.add_row(Text(
        "1. Never hold DWs overnight: Avoid time decay (Theta) and overnight gap risk.\n"
        "2. Choose DWs with Sensitivity ~1.0: 1 tick change in stock = 1 tick change in DW.\n"
        "3. Check Expiration: Trade DWs with at least 3-4 weeks before Last Trading Day.\n"
        "4. Strict Cut Loss: Never average down a losing DW position. Cut loss immediately if trend breaks.",
        style="dim white"
    ))

    return Panel(t, title="💰 [bold cyan]SMALL BUDGET DW TRADING BLUEPRINT[/bold cyan]", border_style="cyan")


# ------------------------------------------------------------------------------
# DASHBOARD RENDERING
# ------------------------------------------------------------------------------

def print_scanner_dashboard(results: list, timeframe: str, budget: float):
    """Renders the full rich scanner table and trading suggestions."""
    bangkok_tz = pytz.timezone('Asia/Bangkok')
    now_bkk = datetime.now(bangkok_tz).strftime('%Y-%m-%d %H:%M:%S')

    header_text = Text()
    header_text.append("🇹🇭 SET50 & THAI STOCK DERIVATIVE WARRANT (DW) SCANNER\n", style="bold yellow")
    header_text.append(f"Time: {now_bkk} BKK | Timeframe: {timeframe} | Budget Reference: {budget:,.0f} THB\n", style="dim")

    # Table of scanned opportunities
    table = Table(expand=True, header_style="bold cyan", border_style="dim white")
    table.add_column("Stock", justify="left", style="bold white", width=8)
    table.add_column("Price (THB)", justify="right", width=11)
    table.add_column("Chg %", justify="right", width=8)
    table.add_column("RSI(14)", justify="center", width=8)
    table.add_column("MACD Trend", justify="center", width=12)
    table.add_column("DW Recommendation", justify="center", width=16)
    table.add_column("Action / Setup Note", justify="left")

    call_candidates = []
    put_candidates = []

    for r in results:
        p_str = f"{r['price']:,.2f}"
        chg_col = "green" if r['change_pct'] >= 0 else "red"
        chg_str = f"[{chg_col}]{r['change_pct']:+.2f}%[/{chg_col}]"

        rsi = r['rsi']
        rsi_col = "bright_red" if rsi >= 70 else ("bright_green" if rsi <= 30 else ("green" if rsi >= 50 else "red"))
        rsi_str = f"[{rsi_col}]{rsi:.1f}[/{rsi_col}]"

        macd_str = "▲ BULLISH" if r['macd'] > r['macd_sig'] else "▼ BEARISH"
        macd_col = "green" if r['macd'] > r['macd_sig'] else "red"

        sig_str = f"[{r['color']}]{r['signal']}[/{r['color']}]"

        table.add_row(
            r['name'],
            p_str,
            chg_str,
            rsi_str,
            f"[{macd_col}]{macd_str}[/{macd_col}]",
            sig_str,
            r['action']
        )

        if "CALL" in r['signal']:
            call_candidates.append(r)
        elif "PUT" in r['signal']:
            put_candidates.append(r)

    console.print(header_text)
    console.print(table)
    console.print()

    # Top Highlights Row
    top_call = call_candidates[0] if call_candidates else None
    top_put = put_candidates[-1] if put_candidates else (put_candidates[0] if put_candidates else None)

    summary_grid = Table.grid(expand=True, padding=(0, 2))
    summary_grid.add_column()
    summary_grid.add_column()

    call_box = Text()
    if top_call:
        call_box.append(f"🟢 TOP CALL DW PICK: {top_call['name']} ({top_call['price']:.2f} THB)\n", style="bold bright_green")
        call_box.append(f"• Setup: Score +{top_call['score']} | RSI: {top_call['rsi']:.1f} | Trend: Bullish\n", style="white")
        call_box.append(f"• Search DW code: {top_call['name'][:4]}01C... or {top_call['name'][:4]}13C...\n", style="cyan")
        call_box.append(f"• Strategy: {top_call['action']}", style="dim green")
    else:
        call_box.append("🟢 TOP CALL DW PICK: None currently qualified (Market in neutral/pullback)", style="dim")

    put_box = Text()
    if top_put:
        put_box.append(f"🔴 TOP PUT DW PICK: {top_put['name']} ({top_put['price']:.2f} THB)\n", style="bold bright_red")
        put_box.append(f"• Setup: Score {top_put['score']} | RSI: {top_put['rsi']:.1f} | Trend: Bearish\n", style="white")
        put_box.append(f"• Search DW code: {top_put['name'][:4]}01P... or {top_put['name'][:4]}13P...\n", style="cyan")
        put_box.append(f"• Strategy: {top_put['action']}", style="dim red")
    else:
        put_box.append("🔴 TOP PUT DW PICK: None currently qualified", style="dim")

    summary_grid.add_row(
        Panel(call_box, title="[bold bright_green]CALL DW HIGHLIGHT[/]", border_style="green"),
        Panel(put_box, title="[bold bright_red]PUT DW HIGHLIGHT[/]", border_style="red")
    )

    console.print(summary_grid)
    console.print()
    console.print(build_budget_guide_panel(budget))


# ------------------------------------------------------------------------------
# MAIN
# ------------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="SET50 & Thai Stock DW Screener and Day Trading Tool",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python3 thai_dw_screener.py                      # Scan all SET50 & active Thai DW stocks (15m)
  python3 thai_dw_screener.py --timeframe 5m       # Fast 5-minute intraday scan
  python3 thai_dw_screener.py --timeframe 1d       # Daily swing trend scan
  python3 thai_dw_screener.py --cheap-only         # Only scan low-priced underlying stocks (< 5 THB)
  python3 thai_dw_screener.py --budget 2000        # Simulate position sizing for 2,000 THB budget
        """
    )
    parser.add_argument('--timeframe', default='15m', choices=['1m', '5m', '15m', '30m', '60m', '1d'], help='Scanning timeframe (default: 15m)')
    parser.add_argument('--cheap-only', action='store_true', help='Only scan underlying stocks trading under 5 THB (e.g. SIRI, TTB, WHA, BTS)')
    parser.add_argument('--budget', type=float, default=1000.0, help='Investment budget in THB (default: 1000)')

    args = parser.parse_args()

    results = scan_thai_stocks(args.timeframe, args.cheap_only)
    if not results:
        console.print("[bold red]No stock data could be fetched. Please check your internet connection.[/bold red]")
        return

    print_scanner_dashboard(results, args.timeframe, args.budget)


if __name__ == '__main__':
    main()
