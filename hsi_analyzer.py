#!/usr/bin/env python3
"""
================================================================================
  HSI DAY TRADING ANALYZER & DW SIGNAL DASHBOARD
  Real-time Hang Seng Index Analysis (RSI, MACD, EMAs, Pivots, Multi-Timeframe)
  Designed for Call / Put DW (Derivative Warrant) Day Traders.
================================================================================
"""

import sys
import os
import time
import argparse
from datetime import datetime
import pytz
import numpy as np
import pandas as pd
import yfinance as yf
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.layout import Layout
from rich.text import Text
from rich.columns import Columns
from rich.align import Align
from rich.live import Live
from rich.rule import Rule

console = Console()

# ------------------------------------------------------------------------------
# TECHNICAL INDICATOR CALCULATIONS (Pure Pandas / NumPy)
# ------------------------------------------------------------------------------

def calculate_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """
    Computes RSI, MACD, EMAs, Bollinger Bands, and ATR on an OHLCV DataFrame.
    """
    if df.empty:
        return df

    df = df.dropna(subset=['Close']).copy()
    if len(df) < 26:
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

    # 3. Exponential Moving Averages (EMA 9, 21, 50, 200)
    df['EMA9'] = df['Close'].ewm(span=9, adjust=False).mean()
    df['EMA21'] = df['Close'].ewm(span=21, adjust=False).mean()
    df['EMA50'] = df['Close'].ewm(span=50, adjust=False).mean()
    if len(df) >= 200:
        df['EMA200'] = df['Close'].ewm(span=200, adjust=False).mean()
    else:
        df['EMA200'] = np.nan

    # 4. Bollinger Bands (20, 2)
    sma20 = df['Close'].rolling(window=20).mean()
    std20 = df['Close'].rolling(window=20).std()
    df['BB_Upper'] = sma20 + (2 * std20)
    df['BB_Lower'] = sma20 - (2 * std20)
    df['BB_Mid'] = sma20

    # 5. ATR (14) - Average True Range for volatility & stop loss sizing
    high_low = df['High'] - df['Low']
    high_close = (df['High'] - df['Close'].shift(1)).abs()
    low_close = (df['Low'] - df['Close'].shift(1)).abs()
    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    df['ATR'] = tr.ewm(alpha=1/14, min_periods=14, adjust=False).mean()

    return df


def calculate_pivot_points(daily_df: pd.DataFrame) -> dict:
    """
    Calculates Classic Floor Pivot Points from daily High, Low, Close.
    """
    if daily_df.empty or len(daily_df) < 2:
        return {}

    # Use previous completed day if today is still active, or latest 2 days
    prev_day = daily_df.iloc[-2] if len(daily_df) >= 2 else daily_df.iloc[-1]
    h = prev_day['High']
    l = prev_day['Low']
    c = prev_day['Close']

    p = (h + l + c) / 3.0
    r1 = (2 * p) - l
    s1 = (2 * p) - h
    r2 = p + (h - l)
    s2 = p - (h - l)
    r3 = h + 2 * (p - l)
    s3 = l - 2 * (h - p)

    return {
        'R3': r3,
        'R2': r2,
        'R1': r1,
        'P': p,
        'S1': s1,
        'S2': s2,
        'S3': s3,
        'prev_high': h,
        'prev_low': l,
        'prev_close': c
    }


# ------------------------------------------------------------------------------
# DATA FETCHER
# ------------------------------------------------------------------------------

def fetch_data(ticker_symbol: str = '^HSI', primary_interval: str = '5m'):
    """
    Fetches real-time intraday & daily data for multi-timeframe analysis.
    """
    ticker = yf.Ticker(ticker_symbol)

    tf_configs = {
        '1m': {'period': '1d', 'interval': '1m'},
        '5m': {'period': '5d', 'interval': '5m'},
        '15m': {'period': '5d', 'interval': '15m'},
        '60m': {'period': '1mo', 'interval': '60m'},
        '1D': {'period': '1mo', 'interval': '1d'},
    }

    # Ensure requested primary interval is in the fetch list
    if primary_interval not in tf_configs:
        tf_configs[primary_interval] = {'period': '5d', 'interval': primary_interval}

    data_map = {}
    for tf, cfg in tf_configs.items():
        try:
            df = ticker.history(period=cfg['period'], interval=cfg['interval'])
            if not df.empty:
                df = df.dropna(subset=['Close'])
                df = calculate_indicators(df)
                data_map[tf] = df
        except Exception as e:
            pass

    return data_map


# ------------------------------------------------------------------------------
# SIGNAL & DW SCORING ENGINE
# ------------------------------------------------------------------------------

def evaluate_timeframe(df: pd.DataFrame, tf_name: str) -> dict:
    """
    Evaluates indicators for a single timeframe and returns trend & subscore.
    """
    if df.empty or len(df) < 5:
        return {'score': 0, 'trend': 'NEUTRAL', 'summary': 'Insufficient Data'}

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

    score = 0
    signals = []

    # 1. MACD Analysis (Weight: ~35 pts)
    is_macd_bullish = macd > macd_sig
    is_golden_cross = (prev['MACD'] <= prev['MACD_Signal']) and (macd > macd_sig)
    is_death_cross = (prev['MACD'] >= prev['MACD_Signal']) and (macd < macd_sig)
    is_hist_expanding_pos = macd_hist > 0 and macd_hist > macd_hist_prev
    is_hist_expanding_neg = macd_hist < 0 and macd_hist < macd_hist_prev

    if is_golden_cross:
        score += 35
        signals.append("MACD Golden Cross (Fresh Bullish Trigger)")
    elif is_death_cross:
        score -= 35
        signals.append("MACD Death Cross (Fresh Bearish Trigger)")
    elif is_macd_bullish:
        if is_hist_expanding_pos:
            score += 25
            signals.append("MACD Bullish & Momentum Accelerating")
        else:
            score += 15
            signals.append("MACD Bullish (Momentum Slowing)")
    else:
        if is_hist_expanding_neg:
            score -= 25
            signals.append("MACD Bearish & Momentum Accelerating")
        else:
            score -= 15
            signals.append("MACD Bearish (Momentum Weakening)")

    # 2. RSI Analysis (Weight: ~30 pts)
    if rsi >= 75:
        score += 5  # Strong momentum but extreme caution
        signals.append(f"RSI Overbought ({rsi:.1f}) - High Call Pullback Risk")
    elif 60 <= rsi < 75:
        score += 25
        signals.append(f"RSI Strong Bullish ({rsi:.1f}) - Healthy Momentum")
    elif 50 <= rsi < 60:
        score += 15
        signals.append(f"RSI Bullish ({rsi:.1f}) - Above Centerline")
    elif 40 <= rsi < 50:
        score -= 15
        signals.append(f"RSI Bearish ({rsi:.1f}) - Below Centerline")
    elif 25 < rsi < 40:
        score -= 25
        signals.append(f"RSI Strong Bearish ({rsi:.1f}) - Heavy Selling")
    else:
        score -= 5
        signals.append(f"RSI Oversold ({rsi:.1f}) - High Put Bounce Risk")

    # 3. EMA Trend Structure (Weight: ~35 pts)
    if price > ema9 > ema21:
        if price > ema50:
            score += 30
            signals.append("Price > EMA9 > EMA21 > EMA50 (Full Bullish Stack)")
        else:
            score += 20
            signals.append("Price > EMA9 > EMA21 (Short-term Bullish)")
    elif price < ema9 < ema21:
        if price < ema50:
            score -= 30
            signals.append("Price < EMA9 < EMA21 < EMA50 (Full Bearish Stack)")
        else:
            score -= 20
            signals.append("Price < EMA9 < EMA21 (Short-term Bearish)")
    elif price > ema21:
        score += 10
        signals.append("Price above EMA21 Support")
    elif price < ema21:
        score -= 10
        signals.append("Price below EMA21 Resistance")

    # Clamp score between -100 and +100
    score = max(-100, min(100, score))

    if score >= 50:
        trend = "STRONG BULLISH"
    elif score >= 20:
        trend = "BULLISH"
    elif score <= -50:
        trend = "STRONG BEARISH"
    elif score <= -20:
        trend = "BEARISH"
    else:
        trend = "NEUTRAL / CHOP"

    return {
        'score': score,
        'trend': trend,
        'rsi': rsi,
        'macd': macd,
        'macd_sig': macd_sig,
        'macd_hist': macd_hist,
        'ema9': ema9,
        'ema21': ema21,
        'ema50': ema50,
        'price': price,
        'signals': signals
    }


def compute_overall_dw_decision(data_map: dict, primary_tf: str = '5m', ticker_symbol: str = '^HSI') -> dict:
    """
    Aggregates multi-timeframe evaluation into an actionable Call / Put DW recommendation.
    """
    weights = {'1m': 0.15, '5m': 0.35, '15m': 0.30, '60m': 0.20}
    tf_results = {}
    weighted_score = 0.0
    total_weight = 0.0

    for tf, df in data_map.items():
        if tf in weights and not df.empty:
            res = evaluate_timeframe(df, tf)
            tf_results[tf] = res
            weighted_score += res['score'] * weights[tf]
            total_weight += weights[tf]

    if total_weight > 0:
        composite_score = weighted_score / total_weight
    else:
        composite_score = 0.0

    primary_df = data_map.get(primary_tf, pd.DataFrame())
    if primary_df.empty and len(data_map) > 0:
        primary_tf = list(data_map.keys())[0]
        primary_df = data_map[primary_tf]

    latest_row = primary_df.iloc[-1]
    curr_price = latest_row['Close']
    atr = latest_row.get('ATR', curr_price * 0.015)
    ema9 = latest_row.get('EMA9', curr_price)
    ema21 = latest_row.get('EMA21', curr_price)

    # Pivot Points calculation
    daily_df = data_map.get('1D', pd.DataFrame())
    pivots = calculate_pivot_points(daily_df)

    # Dynamic strike and buffer offsets based on price magnitude
    strike_step = max(0.05, curr_price * 0.02)
    is_thai = ticker_symbol.endswith('.BK') or ('^SET' in ticker_symbol)

    # Decision Matrix for DW
    if composite_score >= 55:
        recommendation = "BUY CALL DW"
        color = "bright_green"
        bias = "STRONG BULLISH"
        action_plan = (
            f"• Target Call DW strike near current or slightly OTM (e.g., {curr_price + strike_step:.2f} - {curr_price + (strike_step * 2):.2f})\n"
            f"• Entry Zone: Enter on dip near EMA9 ({ema9:.2f}) or EMA21 ({ema21:.2f})\n"
            f"• Stop Loss: Cut Call if price breaks below {curr_price - (atr * 0.8):.2f} (or EMA21 breakdown)\n"
            f"• Profit Targets: TP1 @ {pivots.get('R1', curr_price + atr):.2f} | TP2 @ {pivots.get('R2', curr_price + (atr * 2)):.2f}"
        )
    elif composite_score >= 20:
        recommendation = "CALL BIAS (Wait For Pullback)"
        color = "green"
        bias = "MODERATE BULLISH"
        action_plan = (
            f"• Trend favors CALL DW, but avoid chasing highs at resistance.\n"
            f"• Entry: Wait for pullback to EMA9 ({ema9:.2f}) with RSI bouncing > 50.\n"
            f"• Stop Loss: {curr_price - atr:.2f}\n"
            f"• Profit Target: {pivots.get('R1', curr_price + atr):.2f}"
        )
    elif composite_score <= -55:
        recommendation = "BUY PUT DW"
        color = "bright_red"
        bias = "STRONG BEARISH"
        action_plan = (
            f"• Target Put DW strike near current or slightly OTM (e.g., {curr_price - strike_step:.2f} - {curr_price - (strike_step * 2):.2f})\n"
            f"• Entry Zone: Enter on rebound rejection near EMA9 ({ema9:.2f}) or EMA21 ({ema21:.2f})\n"
            f"• Stop Loss: Cut Put if price breaks above {curr_price + (atr * 0.8):.2f} (or EMA21 breakout)\n"
            f"• Profit Targets: TP1 @ {pivots.get('S1', curr_price - atr):.2f} | TP2 @ {pivots.get('S2', curr_price - (atr * 2)):.2f}"
        )
    elif composite_score <= -20:
        recommendation = "PUT BIAS (Wait For Rebound)"
        color = "red"
        bias = "MODERATE BEARISH"
        action_plan = (
            f"• Trend favors PUT DW, but avoid shorting into extended support.\n"
            f"• Entry: Wait for intraday bounce to EMA9/21 ({ema9:.2f} - {ema21:.2f}) and MACD rejection.\n"
            f"• Stop Loss: {curr_price + atr:.2f}\n"
            f"• Profit Target: {pivots.get('S1', curr_price - atr):.2f}"
        )
    else:
        recommendation = "STANDBY / NO TRADE (Chop)"
        color = "yellow"
        bias = "NEUTRAL / SIDEWAYS"
        action_plan = (
            f"• Conflicting signals or low momentum. DW Time Decay (Theta) will erode profits.\n"
            f"• Wait for clean breakout above EMA21 ({ema21:.2f}) for Call or below for Put.\n"
            f"• Range bounds: Support @ {pivots.get('S1', curr_price - atr):.2f} | Resistance @ {pivots.get('R1', curr_price + atr):.2f}"
        )

    # Confidence calculation (0 to 100%)
    confidence = abs(composite_score)

    return {
        'composite_score': composite_score,
        'confidence': confidence,
        'recommendation': recommendation,
        'color': color,
        'bias': bias,
        'action_plan': action_plan,
        'tf_results': tf_results,
        'pivots': pivots,
        'primary_tf': primary_tf,
        'curr_price': curr_price,
        'atr': atr
    }


# ------------------------------------------------------------------------------
# HONG KONG MARKET HOURS HELPER
# ------------------------------------------------------------------------------

def get_hsi_market_status():
    """
    Returns the current status of Hong Kong Stock Exchange (HKEX).
    HKT is UTC+8.
    Morning Session:   09:30 - 12:00 HKT (08:30 - 11:00 Bangkok)
    Lunch Break:       12:00 - 13:00 HKT (11:00 - 12:00 Bangkok)
    Afternoon Session: 13:00 - 16:00 HKT (12:00 - 15:00 Bangkok)
    Closing Auction:   16:00 - 16:10 HKT
    """
    hkt = pytz.timezone('Asia/Hong_Kong')
    now_hkt = datetime.now(hkt)
    weekday = now_hkt.weekday()  # 0=Monday, 6=Sunday
    h_m = (now_hkt.hour, now_hkt.minute)

    if weekday >= 5:
        return "🔴 Market Closed (Weekend)", "red", now_hkt

    if (9, 30) <= h_m < (12, 0):
        return "🟢 Morning Session (Active)", "green", now_hkt
    elif (12, 0) <= h_m < (13, 0):
        return "🟡 Lunch Break (12:00 - 13:00 HKT)", "yellow", now_hkt
    elif (13, 0) <= h_m < (16, 0):
        return "🟢 Afternoon Session (Active)", "green", now_hkt
    elif (16, 0) <= h_m < (16, 10):
        return "🟡 Closing Auction (16:00 - 16:10 HKT)", "yellow", now_hkt
    else:
        return "🔴 Market Closed", "red", now_hkt


# ------------------------------------------------------------------------------
# TERMINAL DASHBOARD RENDERING (Rich UI)
# ------------------------------------------------------------------------------

def build_dashboard(ticker_symbol: str, primary_interval: str = '5m', history_count: int = 0) -> Panel:
    """
    Fetches latest data and compiles full Rich terminal UI.
    """
    data_map = fetch_data(ticker_symbol, primary_interval)
    if not data_map or primary_interval not in data_map:
        return Panel(Text(f"❌ Error: Unable to fetch market data for {ticker_symbol}. Check internet or ticker.", style="bold red"))

    eval_data = compute_overall_dw_decision(data_map, primary_interval, ticker_symbol)
    primary_df = data_map[primary_interval]
    latest = primary_df.iloc[-1]
    prev_close = primary_df.iloc[-2]['Close'] if len(primary_df) >= 2 else latest['Open']

    curr_price = latest['Close']
    change_pts = curr_price - prev_close
    change_pct = (change_pts / prev_close) * 100 if prev_close else 0.0

    # Daily high/low from daily or intraday
    daily_df = data_map.get('1D', primary_df)
    day_high = daily_df['High'].iloc[-1] if not daily_df.empty else primary_df['High'].max()
    day_low = daily_df['Low'].iloc[-1] if not daily_df.empty else primary_df['Low'].min()
    day_open = daily_df['Open'].iloc[-1] if not daily_df.empty else primary_df['Open'].iloc[0]

    market_status, status_color, now_hkt = get_hsi_market_status()

    # 1. HEADER TITLE & MARKET OVERVIEW
    change_sign = "+" if change_pts >= 0 else ""
    change_color = "bright_green" if change_pts >= 0 else "bright_red"

    is_thai = ticker_symbol.endswith('.BK') or ('^SET' in ticker_symbol)
    title_flag = "🇹🇭" if is_thai else "🇭🇰"
    title_name = f"THAI STOCK ({ticker_symbol}) / SET50" if is_thai else "HANG SENG INDEX (HSI)"

    header_text = Text()
    header_text.append(f"{title_flag} {title_name} DAY TRADING DASHBOARD\n", style="bold cyan")
    header_text.append(f" Ticker: {ticker_symbol} | Time: {now_hkt.strftime('%Y-%m-%d %H:%M:%S')} | Status: ", style="dim")
    header_text.append(f"{market_status}\n", style=f"bold {status_color}")

    # Price stats row
    stats_table = Table(box=None, expand=True, show_header=False, padding=(0, 1))
    stats_table.add_column("Price", justify="left", style="bold white")
    stats_table.add_column("Change", justify="center")
    stats_table.add_column("Day Range", justify="center", style="dim white")
    stats_table.add_column("ATR", justify="right", style="bold cyan")

    stats_table.add_row(
        f"Price: {curr_price:,.2f}",
        f"Change: [{change_color}]{change_sign}{change_pts:,.2f} ({change_sign}{change_pct:.2f}%)[/{change_color}]",
        f"Day Range: {day_low:,.2f} - {day_high:,.2f}",
        f"ATR(14): {eval_data['atr']:.1f} pts"
    )

    # 2. MAIN TIME-FRAME INDICATORS (RSI, MACD, EMAs)
    pri_eval = eval_data['tf_results'].get(primary_interval, {})
    rsi_val = pri_eval.get('rsi', 50.0)
    macd_val = pri_eval.get('macd', 0.0)
    macd_sig = pri_eval.get('macd_sig', 0.0)
    macd_hist = pri_eval.get('macd_hist', 0.0)
    ema9_val = pri_eval.get('ema9', curr_price)
    ema21_val = pri_eval.get('ema21', curr_price)
    ema50_val = pri_eval.get('ema50', curr_price)

    # RSI Visual Bar (20 characters)
    rsi_fill = int((rsi_val / 100) * 20)
    rsi_bar = "█" * rsi_fill + "░" * (20 - rsi_fill)
    if rsi_val >= 70:
        rsi_style = "bright_red bold"
        rsi_tag = "OVERBOUGHT (>70)"
    elif rsi_val <= 30:
        rsi_style = "bright_green bold"
        rsi_tag = "OVERSOLD (<30)"
    elif rsi_val >= 55:
        rsi_style = "green bold"
        rsi_tag = "BULLISH BIAS"
    elif rsi_val <= 45:
        rsi_style = "red bold"
        rsi_tag = "BEARISH BIAS"
    else:
        rsi_style = "yellow bold"
        rsi_tag = "NEUTRAL (45-55)"

    # MACD Visual Status
    macd_cross_tag = "▲ Bullish Cross (MACD > Sig)" if macd_val > macd_sig else "▼ Bearish Cross (MACD < Sig)"
    macd_style = "bright_green" if macd_val > macd_sig else "bright_red"
    hist_style = "green" if macd_hist >= 0 else "red"

    tech_table = Table(title=f"📊 Primary Timeframe Details ({primary_interval})", expand=True, box=None)
    tech_table.add_column("Indicator", style="cyan", width=18)
    tech_table.add_column("Value / Level", style="bold white", width=26)
    tech_table.add_column("Status / Visual Gauge", width=36)

    tech_table.add_row(
        "RSI (14)",
        f"{rsi_val:.2f}",
        f"[{rsi_style}][{rsi_bar}] {rsi_tag}[/{rsi_style}]"
    )
    tech_table.add_row(
        "MACD (12,26,9)",
        f"MACD: {macd_val:+.2f} | Sig: {macd_sig:+.2f}",
        f"[{macd_style}]{macd_cross_tag} (Hist: {macd_hist:+.2f})[/{macd_style}]"
    )
    tech_table.add_row(
        "Moving Averages",
        f"EMA9: {ema9_val:,.1f} | EMA21: {ema21_val:,.1f}",
        f"Trend: [{macd_style}]{pri_eval.get('trend', 'NEUTRAL')}[/{macd_style}] | "
        f"[{'green' if curr_price > ema21_val else 'red'}]{'Price > EMA21' if curr_price > ema21_val else 'Price < EMA21'}[/]"
    )

    # 3. MULTI-TIMEFRAME MATRIX
    mtf_table = Table(title="⏱️ Multi-Timeframe Alignment Matrix", expand=True, header_style="bold magenta")
    mtf_table.add_column("Timeframe", justify="center", style="bold cyan")
    mtf_table.add_column("Price", justify="right")
    mtf_table.add_column("RSI(14)", justify="center")
    mtf_table.add_column("MACD Trend", justify="center")
    mtf_table.add_column("EMA Alignment", justify="center")
    mtf_table.add_column("TF Verdict", justify="center", style="bold")

    for tf in ['1m', '5m', '15m', '60m']:
        tf_data = eval_data['tf_results'].get(tf)
        if tf_data:
            tf_r = tf_data['rsi']
            tf_r_color = "bright_red" if tf_r >= 70 else ("bright_green" if tf_r <= 30 else ("green" if tf_r >= 50 else "red"))
            tf_macd_str = "▲ BULLISH" if tf_data['macd'] > tf_data['macd_sig'] else "▼ BEARISH"
            tf_macd_col = "green" if tf_data['macd'] > tf_data['macd_sig'] else "red"
            
            p = tf_data['price']
            e9 = tf_data['ema9']
            e21 = tf_data['ema21']
            ema_str = "P > 9 > 21 (Bull)" if p > e9 > e21 else ("P < 9 < 21 (Bear)" if p < e9 < e21 else "Mixed")
            ema_col = "green" if "Bull" in ema_str else ("red" if "Bear" in ema_str else "yellow")

            v_color = "bright_green" if "BULLISH" in tf_data['trend'] else ("bright_red" if "BEARISH" in tf_data['trend'] else "yellow")

            mtf_table.add_row(
                tf,
                f"{p:,.1f}",
                f"[{tf_r_color}]{tf_r:.1f}[/{tf_r_color}]",
                f"[{tf_macd_col}]{tf_macd_str}[/{tf_macd_col}]",
                f"[{ema_col}]{ema_str}[/{ema_col}]",
                f"[{v_color}]{tf_data['trend']}[/{v_color}]"
            )

    # 4. INTRADAY PIVOT POINTS CARD
    piv = eval_data['pivots']
    piv_table = Table(title="🎯 Floor Pivot Points & Key S/R Levels", expand=True, header_style="bold blue")
    piv_table.add_column("Level", justify="center", style="bold")
    piv_table.add_column("Target Price", justify="right")
    piv_table.add_column("Distance", justify="right")
    piv_table.add_column("Role", justify="left")

    if piv:
        piv_levels = [
            ("Resistance 2 (R2)", piv.get('R2', 0), "Major Bullish Target / Breakout Zone"),
            ("Resistance 1 (R1)", piv.get('R1', 0), "First Target for Call DW"),
            ("Pivot Point (P)", piv.get('P', 0), "Intraday Bull / Bear Baseline"),
            ("Support 1 (S1)", piv.get('S1', 0), "First Target for Put DW"),
            ("Support 2 (S2)", piv.get('S2', 0), "Major Bearish Target / Breakdown Zone"),
        ]
        for name, lvl, role in piv_levels:
            dist = lvl - curr_price
            dist_col = "bright_green" if dist > 0 else "bright_red"
            is_curr = abs(dist) < 40
            row_style = "bold yellow" if is_curr else None
            piv_table.add_row(
                name,
                f"{lvl:,.1f}",
                f"[{dist_col}]{dist:+,.1f} pts[/{dist_col}]",
                role,
                style=row_style
            )

    # 5. DERIVATIVE WARRANT (DW) ACTION CARD
    rec_color = eval_data['color']
    rec_title = eval_data['recommendation']
    conf = eval_data['confidence']

    conf_fill = int((conf / 100) * 25)
    conf_bar = "█" * conf_fill + "░" * (25 - conf_fill)

    playbook_content = Table.grid(expand=True, padding=(0, 1))
    playbook_content.add_column(justify="left")

    header_bar = Table.grid(expand=True)
    header_bar.add_column(justify="center")
    header_bar.add_row(Text(f"🎯 TRADING SIGNAL: {rec_title} ({eval_data['bias']})", style=f"bold {rec_color} reverse"))
    header_bar.add_row(Text(f"Signal Strength / Confluence: [{conf_bar}] {conf:.0f}%\n", style=f"bold {rec_color}"))

    playbook_content.add_row(header_bar)
    playbook_content.add_row(Text(eval_data['action_plan'], style="bold white"))
    playbook_content.add_row(Rule(style="dim yellow"))
    playbook_content.add_row(
        Text("⚠️  DW RISK REMINDER: Set tight stop losses. Sideways action causes Theta (time decay) loss.\n"
             "    Trade with high sensitivity & volume DWs. Avoid holding overnight for pure day trades.",
             style="italic dim yellow")
    )

    dw_panel = Panel(playbook_content, title=f"⚡ [bold {rec_color}]DW DAY TRADING PLAYBOOK[/]", border_style=rec_color)

    # 6. RECENT CANDLE HISTORY (OPTIONAL)
    if history_count > 0:
        hist_table = Table(title=f"📜 Recent {history_count} Candles ({primary_interval})", expand=True, header_style="bold yellow", box=None)
        hist_table.add_column("Time", justify="center", style="dim", width=7)
        hist_table.add_column("Open", justify="right", width=9)
        hist_table.add_column("High", justify="right", width=9)
        hist_table.add_column("Low", justify="right", width=9)
        hist_table.add_column("Close", justify="right", style="bold white", width=9)
        hist_table.add_column("RSI", justify="center", width=7)
        hist_table.add_column("MACD", justify="right", width=8)
        hist_table.add_column("Signal", justify="right", width=8)
        hist_table.add_column("Hist", justify="right", width=8)

        recent_df = primary_df.tail(history_count)
        for idx, row in recent_df.iterrows():
            # Format timestamp nicely
            ts_str = idx.strftime('%H:%M') if hasattr(idx, 'strftime') else str(idx)
            r = row.get('RSI', 50.0)
            r_col = "bright_red" if r >= 70 else ("bright_green" if r <= 30 else ("green" if r >= 50 else "red"))
            h = row.get('MACD_Hist', 0.0)
            h_col = "green" if h >= 0 else "red"
            c_col = "green" if row['Close'] >= row['Open'] else "red"

            hist_table.add_row(
                ts_str,
                f"{row['Open']:.1f}",
                f"{row['High']:.1f}",
                f"{row['Low']:.1f}",
                f"[{c_col}]{row['Close']:.1f}[/{c_col}]",
                f"[{r_col}]{r:.1f}[/{r_col}]",
                f"{row.get('MACD', 0):+.2f}",
                f"{row.get('MACD_Signal', 0):+.2f}",
                f"[{h_col}]{h:+.2f}[/{h_col}]"
            )

    # Combine everything into clean master panel
    main_layout = Table.grid(expand=True, padding=(1, 0))
    main_layout.add_row(header_text)
    main_layout.add_row(stats_table)
    main_layout.add_row(Rule(style="dim cyan"))
    main_layout.add_row(tech_table)
    main_layout.add_row(mtf_table)
    main_layout.add_row(piv_table)
    main_layout.add_row(dw_panel)
    if history_count > 0:
        main_layout.add_row(hist_table)

    return Panel(main_layout, border_style="cyan", padding=(1, 2))


# ------------------------------------------------------------------------------
# CLI ENTRY POINT & MODES
# ------------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Hang Seng Index (HSI) Day Trading Analysis & DW Decision Tool",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python3 hsi_analyzer.py                  # Single snapshot analysis (5m primary)
  python3 hsi_analyzer.py --timeframe 1m   # High frequency 1-minute view
  python3 hsi_analyzer.py --timeframe 15m  # Swing day-trade 15-minute view
  python3 hsi_analyzer.py --history 5      # Show last 5 candles table
  python3 hsi_analyzer.py --live           # Continuous live update mode (every 15s)
  python3 hsi_analyzer.py --live --refresh 10 # Live mode refreshing every 10 seconds
        """
    )
    parser.add_argument('--ticker', default='^HSI', help='Yahoo Finance ticker (default: ^HSI)')
    parser.add_argument('--timeframe', default='5m', choices=['1m', '2m', '5m', '15m', '30m', '60m'], help='Primary timeframe (default: 5m)')
    parser.add_argument('--history', type=int, default=0, help='Show table of last N candles with indicators (e.g., --history 5)')
    parser.add_argument('--live', action='store_true', help='Run in live auto-refresh dashboard mode')
    parser.add_argument('--refresh', type=int, default=15, help='Refresh interval in seconds for live mode (default: 15)')

    args = parser.parse_args()

    if args.live:
        console.clear()
        console.print(f"[bold cyan]Starting Live HSI DW Day Trading Dashboard... (Refresh every {args.refresh}s)[/bold cyan]")
        try:
            with Live(console=console, screen=True, refresh_per_second=1) as live:
                while True:
                    panel = build_dashboard(args.ticker, args.timeframe, args.history)
                    live.update(panel)
                    time.sleep(args.refresh)
        except KeyboardInterrupt:
            console.print("\n[bold yellow]Exited Live Monitor mode.[/bold yellow]")
    else:
        panel = build_dashboard(args.ticker, args.timeframe, args.history)
        console.print(panel)


if __name__ == '__main__':
    main()
