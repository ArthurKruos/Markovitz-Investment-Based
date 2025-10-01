# streamlit_markowitz_crypto.py
import streamlit as st
import pandas as pd
import numpy as np
import yfinance as yf
import os
import time
from datetime import timedelta
from scipy.optimize import minimize

# ---------- Returns and alignment ----------
def prices_to_simple_returns(price_series):
    return price_series.pct_change().dropna()

def align_and_merge_returns(stock_returns_df, crypto_returns_dict):
    df = stock_returns_df.copy()
    for sym, series in crypto_returns_dict.items():
        df[sym] = series
    df = df.dropna(how='any')  # manter apenas datas em comum
    return df

# ---------- Markowitz optimization ----------
def annualize_returns(mean_daily_returns, periods_per_year=252):
    return mean_daily_returns * periods_per_year

def annualize_cov(cov_daily, periods_per_year=252):
    return cov_daily * periods_per_year

def min_variance_weights(target_return, mu, cov, allow_short=False, max_weight=1.0):
    n = len(mu)
    x0 = np.repeat(1/n, n)
    bounds = None if allow_short else [(0.0, max_weight) for _ in range(n)]
    cons = (
        {'type': 'eq', 'fun': lambda w: np.sum(w) - 1},
        {'type': 'eq', 'fun': lambda w: w.dot(mu) - target_return}
    )
    def portfolio_var(w):
        return float(w.T.dot(cov).dot(w))
    res = minimize(portfolio_var, x0, method='SLSQP', bounds=bounds, constraints=cons)
    if not res.success:
        raise ValueError("Optimization failed: " + res.message)
    return res.x

# ---------- Streamlit UI ----------
st.title("Markowitz + Criptomoedas (integração com yfinance e cache CSV)")

# 1) carregar retornos das ações
st.markdown("**1. Carregar retornos das ações (CSV)**")
csv_path = "data/retornos_acoes_ibovespa_2024.csv"
st.write(f"Carregando: `{csv_path}`")
stock_returns = pd.read_csv(csv_path, index_col=0, parse_dates=True)
st.write("Amostra dos retornos (primeiras linhas):")
st.dataframe(stock_returns.head())

# 2) selecionar ações
tickers = list(stock_returns.columns)
selected_stocks = st.multiselect("Escolha ações para incluir", tickers, default=tickers[:10])
if len(selected_stocks) == 0:
    st.stop()
stock_returns_sel = stock_returns[selected_stocks]

# 3) adicionar criptos
st.markdown("**2. Adicionar criptomoedas (via yfinance)**")
st.write("Digite símbolos do Yahoo Finance (ex.: BTC-USD, ETH-USD, SOL-USD).")
input_syms = st.text_input("Símbolos", value="BTC-USD,ETH-USD")
crypto_syms = [s.strip().upper() for s in input_syms.split(",") if s.strip()!='']

# arquivo cache local
crypto_cache_path = "data/crypto_prices.csv"

# 4) buscar preços das criptos
if st.button("Buscar dados das criptos e rodar otimização"):
    from_dt = stock_returns.index.min()
    to_dt = stock_returns.index.max()
    st.write(f"Janela: {from_dt.date()} até {to_dt.date()}")

    crypto_returns = {}

    # Se já existe cache, usa
    if os.path.exists(crypto_cache_path):
        st.success(f"Lendo dados de {crypto_cache_path}")
        prices_all = pd.read_csv(crypto_cache_path, index_col=0, parse_dates=True)
    else:
        st.warning("Baixando dados do Yahoo Finance (isso pode demorar e pode sofrer rate limit)...")
        prices_all = pd.DataFrame()
        for sym in crypto_syms:
            try:
                data = yf.download(
                    sym,
                    start=from_dt - timedelta(days=5),
                    end=to_dt + timedelta(days=1),
                    interval="1d"
                )
                prices_all[sym] = data['Adj Close']
                st.write(f"{sym} baixado com {len(data)} registros.")
                time.sleep(2)  # evitar bloqueio do Yahoo
            except Exception as e:
                st.error(f"Falha ao baixar {sym}: {e}")
        # salva cache
        os.makedirs("data", exist_ok=True)
        prices_all.to_csv(crypto_cache_path)
        st.success(f"Dados salvos em cache: {crypto_cache_path}")

    # calcular retornos
    for sym in crypto_syms:
        if sym in prices_all.columns:
            ret = prices_to_simple_returns(prices_all[sym].dropna())
            ret.index = pd.to_datetime(ret.index.date)
            crypto_returns[sym] = ret

    if len(crypto_returns) == 0:
        st.error("Nenhuma cripto válida para incluir. Pare.")
        st.stop()

    # merge returns
    merged = align_and_merge_returns(stock_returns_sel, crypto_returns)
    st.write("Dados combinados (últimas linhas):")
    st.dataframe(merged.iloc[-5:])

    # estatísticas
    mu_daily = merged.mean()
    cov_daily = merged.cov()
    mu_annual = annualize_returns(mu_daily)
    cov_annual = annualize_cov(cov_daily)

    st.write("Retornos anuais esperados (estimados):")
    st.dataframe(mu_annual.sort_values(ascending=False).to_frame("Retorno anual"))

    # parâmetros
    st.markdown("**Parâmetros de otimização**")
    target_return_annual = st.number_input("Retorno alvo anual (%)", value=12.0) / 100.0
    allow_short = st.checkbox("Permitir short?", value=False)
    max_weight = st.number_input("Peso máximo por ativo (0-1)", value=0.3, min_value=0.0, max_value=1.0)

    # otimização
    try:
        weights = min_variance_weights(target_return_annual, mu_annual.values, cov_annual.values,
                                       allow_short=allow_short, max_weight=max_weight)
        w_series = pd.Series(weights, index=merged.columns)
        st.write("Pesos ótimos (min variância):")
        st.dataframe(w_series.sort_values(ascending=False).to_frame("peso"))
        port_var = float(w_series.T.dot(cov_annual).dot(w_series))
        port_std = np.sqrt(port_var)
        port_ret = float(w_series.dot(mu_annual))
        st.write(f"Retorno esperado (anual): {port_ret:.2%}, Volatilidade anual: {port_std:.2%}")
    except Exception as e:
        st.error("Erro na otimização: " + str(e))
