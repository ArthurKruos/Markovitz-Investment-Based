# streamlit_markowitz_crypto.py
import streamlit as st
import pandas as pd
import numpy as np
import yfinance as yf
import os
from scipy.optimize import minimize

# ---------- Funções de Cálculo ----------
def annualize_returns(mean_daily_returns, periods_per_year=252):
    return mean_daily_returns * periods_per_year

def annualize_cov(cov_daily, periods_per_year=252):
    return cov_daily * periods_per_year

## MODIFICADO: A função agora aceita mais parâmetros para as novas restrições
def min_variance_weights(target_return, mu, cov, all_tickers, stock_syms, crypto_syms,
                         allow_short=False, max_weight=1.0, min_asset_weight=0.0,
                         min_stock_pct=0.0, min_crypto_pct=0.0):
    n = len(mu)
    x0 = np.repeat(1/n, n)
    
    ## MODIFICADO: O limite inferior agora é customizável
    bounds = None if allow_short else [(min_asset_weight, max_weight) for _ in range(n)]
    
    # Restrições base (soma dos pesos e retorno alvo)
    cons = [
        {'type': 'eq', 'fun': lambda w: np.sum(w) - 1},
        {'type': 'eq', 'fun': lambda w: w.dot(mu) - target_return}
    ]
    
    ## NOVO: Adiciona a restrição de % mínimo em ações, se ativada
    if min_stock_pct > 0 and len(stock_syms) > 0:
        # Cria um "vetor-máscara" (1 para ações, 0 para o resto)
        is_stock_mask = np.array([1 if ticker in stock_syms else 0 for ticker in all_tickers])
        stock_constraint = {
            'type': 'ineq', # g(x) >= 0
            'fun': lambda w: w.dot(is_stock_mask) - min_stock_pct
        }
        cons.append(stock_constraint)

    ## NOVO: Adiciona a restrição de % mínimo em cripto, se ativada
    if min_crypto_pct > 0 and len(crypto_syms) > 0:
        is_crypto_mask = np.array([1 if ticker in crypto_syms else 0 for ticker in all_tickers])
        crypto_constraint = {
            'type': 'ineq', # g(x) >= 0
            'fun': lambda w: w.dot(is_crypto_mask) - min_crypto_pct
        }
        cons.append(crypto_constraint)
    
    def portfolio_var(w):
        return float(w.T.dot(cov).dot(w))
        
    res = minimize(portfolio_var, x0, method='SLSQP', bounds=bounds, constraints=cons)
    
    if not res.success:
        raise ValueError("Otimização falhou: " + res.message)
        
    return res.x

# ---------- Interface do Streamlit ----------
st.set_page_config(layout="wide")
st.title("Otimizador de Carteira de Markowitz (Ações e Cripto)")

# --- Colunas para Inputs ---
col1, col2 = st.columns(2)

with col1:
    st.markdown("#### 1. Selecione os Ativos")
    input_stocks = st.text_input("Tickers das Ações (Yahoo Finance)", value="PETR4.SA,VALE3.SA,ITUB4.SA", help="Exemplo: PETR4.SA, VALE3.SA, MGLU3.SA")
    input_cryptos = st.text_input("Tickers das Criptomoedas (Yahoo Finance)", value="BTC-USD,ETH-USD", help="Exemplo: BTC-USD, ETH-USD, SOL-USD")

with col2:
    st.markdown("#### 2. Escolha o Período e Retorno")
    years_back = st.number_input("Anos de histórico para análise", value=3, min_value=1, max_value=20)
    target_return_annual = st.number_input("Retorno anual alvo (%)", value=20.0, step=1.0) / 100.0

# --- Parâmetros de Otimização ---
st.markdown("#### 3. Parâmetros de Otimização")
allow_short = st.checkbox("Permitir venda a descoberto (short)?", value=False)
max_weight = st.slider("Peso máximo por ativo", min_value=0.05, max_value=1.0, value=0.35, step=0.05)


## NOVO: Expander para as restrições avançadas e opcionais
with st.expander("Restrições Avançadas (Opcional)"):
    
    use_min_asset_weight = st.checkbox("Definir um peso MÍNIMO por ativo?", help="Força o otimizador a alocar pelo menos essa porcentagem em cada ativo da carteira final.")
    min_asset_weight = st.slider("Peso mínimo por ativo", min_value=0.0, max_value=0.2, value=0.01, step=0.005, disabled=not use_min_asset_weight) if use_min_asset_weight else 0.0

    st.markdown("---")
    
    use_category_constraints = st.checkbox("Definir alocação MÍNIMA por categoria (Ações/Cripto)?")
    if use_category_constraints:
        min_stock_pct = st.slider("Mínimo em Ações (%)", min_value=0, max_value=100, value=50, step=5) / 100.0
        min_crypto_pct = st.slider("Mínimo em Cripto (%)", min_value=0, max_value=100, value=10, step=5) / 100.0
    else:
        min_stock_pct = 0.0
        min_crypto_pct = 0.0


if st.button("Executar Otimização", type="primary"):
    
    with st.spinner("Aguarde... Baixando dados e calculando o portfólio ótimo..."):
        
        # --- 1. Preparação dos Tickers e Datas ---
        stock_syms = [s.strip().upper() for s in input_stocks.split(",") if s.strip() != '']
        crypto_syms = [s.strip().upper() for s in input_cryptos.split(",") if s.strip() != '']
        
        tickers = sorted(list(set(stock_syms + crypto_syms)))

        if not tickers:
            st.warning("Por favor, insira pelo menos um ticker de ação ou criptomoeda.")
            st.stop()

        end_date = pd.Timestamp.today()
        start_date = end_date - pd.DateOffset(years=years_back)
        
        # --- 2. Cache Inteligente e Download de Dados ---
        os.makedirs("data", exist_ok=True)
        cache_filename = f"{'_'.join(tickers)}_{start_date.date()}_{end_date.date()}.csv"
        cache_path = os.path.join("data", cache_filename)

        if os.path.exists(cache_path):
            prices_all = pd.read_csv(cache_path, index_col=0, parse_dates=True)
        else:
            data = yf.download(tickers, start=start_date, end=end_date, progress=False)
            prices_all = data['Close']
            prices_all.dropna(axis=1, how='all', inplace=True)

            if prices_all.empty:
                st.error("Nenhum dado foi baixado. Verifique os tickers.")
                st.stop()
            
            prices_all.to_csv(cache_path)

        # --- 3. Cálculos de Retorno e Covariância ---
        returns = prices_all.pct_change().dropna()
        
        if returns.empty:
            st.error("Não foi possível calcular os retornos.")
            st.stop()
        
        # Atualiza a lista de tickers para apenas aqueles que têm dados
        valid_tickers = returns.columns.tolist()
        valid_stock_syms = [s for s in stock_syms if s in valid_tickers]
        valid_crypto_syms = [c for c in crypto_syms if c in valid_tickers]

        mu_daily = returns.mean()
        cov_daily = returns.cov()
        mu_annual = annualize_returns(mu_daily)
        cov_annual = annualize_cov(cov_daily)

        # --- 4. Execução da Otimização ---
        try:
            ## MODIFICADO: Passa todos os novos parâmetros para a função de otimização
            weights = min_variance_weights(
                target_return=target_return_annual, 
                mu=mu_annual.values, 
                cov=cov_annual.values,
                all_tickers=valid_tickers,
                stock_syms=valid_stock_syms,
                crypto_syms=valid_crypto_syms,
                allow_short=allow_short, 
                max_weight=max_weight,
                min_asset_weight=min_asset_weight,
                min_stock_pct=min_stock_pct,
                min_crypto_pct=min_crypto_pct
            )
            
            w_series = pd.Series(weights, index=mu_annual.index)

            # --- 5. Exibição dos Resultados ---
            st.success("Otimização concluída com sucesso!")
            
            port_ret = float(w_series.dot(mu_annual))
            port_var = float(w_series.T.dot(cov_annual).dot(w_series))
            port_std = np.sqrt(port_var)

            st.markdown("### Resultados da Otimização")
            res_col1, res_col2 = st.columns(2)
            
            with res_col1:
                st.markdown("#### Alocação da Carteira")
                st.dataframe(w_series[w_series > 0.0001].sort_values(ascending=False).to_frame("Peso (%)").applymap(lambda x: f"{x:.2%}"))

            with res_col2:
                st.markdown("#### Métricas do Portfólio")
                st.metric(label="Retorno Anual Esperado", value=f"{port_ret:.2%}")
                st.metric(label="Volatilidade Anual (Risco)", value=f"{port_std:.2%}")
                st.metric(label="Índice de Sharpe (aprox.)", value=f"{port_ret / port_std:.2f}" if port_std > 0 else "N/A", help="Considerando taxa livre de risco de 0%")

        except Exception as e:
            st.error(f"Não foi possível encontrar uma carteira para as restrições definidas.")
            st.error(f"Detalhe do erro: {e}")
            st.warning("Tente relaxar as restrições (ex: diminuir o retorno alvo, aumentar o peso máximo, etc.).")