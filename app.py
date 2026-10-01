import streamlit as st
import pandas as pd
import json
import io
from datetime import datetime, timedelta, timezone
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

st.set_page_config(page_title="Dashboard Cadre 3D", page_icon="📦", layout="wide")

st.title("📦 Dashboard de Vendas - Cadre 3D")
st.markdown("Acompanhe os seus resultados e consulte o estado dos pedidos exatamente como na Shopee.")

@st.cache_data(ttl=120)
def carregar_dados_do_drive():
    try:
        cert_info = json.loads(st.secrets["google_credentials"])
        credenciais = service_account.Credentials.from_service_account_info(
            cert_info, scopes=['https://www.googleapis.com/auth/drive.readonly']
        )
        servico = build('drive', 'v3', credentials=credenciais)
        
        pasta_id = '1p0H9A9-0r8QCX34koCd3mrsyXmTtTzUQ'
        query = f"'{pasta_id}' in parents and trashed=false"
        resultados = servico.files().list(q=query, fields="files(id, name, mimeType)").execute()
        arquivos = resultados.get('files', [])
        
        if not arquivos:
            return pd.DataFrame()
            
        dfs = []
        for arq in arquivos:
            request = servico.files().get_media(fileId=arq['id'])
            
            if arq['mimeType'] == 'application/vnd.google-apps.spreadsheet':
                request = servico.files().export_media(fileId=arq['id'], mimeType='text/csv')
                arquivo_baixado = io.BytesIO(request.execute())
                df = pd.read_csv(arquivo_baixado)
            else:
                arquivo_baixado = io.BytesIO()
                downloader = MediaIoBaseDownload(arquivo_baixado, request)
                done = False
                while done is False:
                    status, done = downloader.next_chunk()
                arquivo_baixado.seek(0)
                
                if arq['name'].endswith('.csv'):
                    df = pd.read_csv(arquivo_baixado)
                else:
                    df = pd.read_excel(arquivo_baixado)
                    
            dfs.append(df)
            
        if dfs:
            df_completo = pd.concat(dfs, ignore_index=True)
            df_completo.columns = df_completo.columns.str.strip() 
            
            df_limpo = df_completo.copy()
                
            # --- CONVERSÃO DAS DATAS ---
            if 'Data de criação do pedido' in df_limpo.columns:
                df_limpo['Data_Criacao'] = pd.to_datetime(df_limpo['Data de criação do pedido'], errors='coerce')
            else:
                df_limpo['Data_Criacao'] = pd.NaT

            if 'Hora do pagamento do pedido' in df_limpo.columns:
                df_limpo['Data_Pagamento'] = pd.to_datetime(df_limpo['Hora do pagamento do pedido'], errors='coerce')
            else:
                df_limpo['Data_Pagamento'] = pd.NaT
                
            # --- FUNÇÃO PARA LIMPEZA DE VALORES ---
            def limpar_coluna_valor(serie):
                if serie is None:
                    return pd.Series(0.0, index=df_limpo.index)
                if serie.dtype == object:
                    s_str = serie.astype(str).str.replace('R$', '', regex=False).str.strip()
                    s_str = s_str.str.replace(',', '.', regex=False)
                    return pd.to_numeric(s_str, errors='coerce').fillna(0)
                else:
                    return pd.to_numeric(serie, errors='coerce').fillna(0)

            # 1. Total Global (com frete - Montante Sujo)
            total_global = limpar_coluna_valor(df_limpo['Total global']) if 'Total global' in df_limpo.columns else (
                limpar_coluna_valor(df_limpo['Preço acordado']) if 'Preço acordado' in df_limpo.columns else 0.0
            )

            # 2. Componentes de Frete para dedução
            est_frete = limpar_coluna_valor(df_limpo['Valor estimado do frete']) if 'Valor estimado do frete' in df_limpo.columns else 0.0
            desc_frete = limpar_coluna_valor(df_limpo['Desconto de Frete Aproximado']) if 'Desconto de Frete Aproximado' in df_limpo.columns else 0.0

            # 3. Ajuste por participação em ação comercial
            ajuste_comercial = limpar_coluna_valor(df_limpo['Ajuste por participação em ação comercial']) if 'Ajuste por participação em ação comercial' in df_limpo.columns else 0.0

            # --- CÁLCULOS FINAIS POR PEDIDO ---
            df_limpo['Valor_Sujo'] = total_global + ajuste_comercial
            frete_liquido = est_frete - desc_frete
            df_limpo['Valor_Produto'] = total_global - frete_liquido + ajuste_comercial
                
            return df_limpo
            
    except Exception as e:
        st.error(f"Erro de ligação com o Drive: {e}")
        return None

col_vazia, col_btn = st.columns([4, 1])
with col_btn:
    if st.button("🔄 Forçar Atualização", use_container_width=True):
        carregar_dados_do_drive.clear()

df = carregar_dados_do_drive()

if df is not None and not df.empty:
    
    st.sidebar.header("🎛️ Filtros do Painel")
    coluna_ativa_data = 'Data_Criacao'
    
    opcao_tempo = st.sidebar.selectbox(
        "Período:", 
        ["Hoje", "Ontem", "Últimos 7 dias", "Este mês", "Todo o período", "Personalizado"]
    )
    
    df_filtrado = df.copy()
    
    if coluna_ativa_data in df_filtrado.columns:
        fuso_br = timezone(timedelta(hours=-3))
        hoje = datetime.now(fuso_br).replace(hour=0, minute=0, second=0, microsecond=0)
        hoje = pd.Timestamp(hoje).tz_localize(None)
        
        if opcao_tempo == "Hoje":
            df_periodo = df_filtrado[df_filtrado[coluna_ativa_data].dt.normalize() == hoje]
        elif opcao_tempo == "Ontem":
            ontem = hoje - pd.Timedelta(days=1)
            df_periodo = df_filtrado[df_filtrado[coluna_ativa_data].dt.normalize() == ontem]
        elif opcao_tempo == "Últimos 7 dias":
            inicio_7d = hoje - pd.Timedelta(days=6)
            df_periodo = df_filtrado[(df_filtrado[coluna_ativa_data] >= inicio_7d) & (df_filtrado[coluna_ativa_data] < (hoje + pd.Timedelta(days=1)))]
        elif opcao_tempo == "Este mês":
            inicio_mes = hoje.replace(day=1)
            proximo_mes = (inicio_mes + pd.DateOffset(months=1))
            df_periodo = df_filtrado[(df_filtrado[coluna_ativa_data] >= inicio_mes) & (df_filtrado[coluna_ativa_data] < proximo_mes)]
        elif opcao_tempo == "Todo o período":
            df_periodo = df_filtrado.copy()
        elif opcao_tempo == "Personalizado":
            d_inicio = st.sidebar.date_input("Data Inicial", (hoje - pd.Timedelta(days=7)).date())
            d_fim = st.sidebar.date_input("Data Final", hoje.date())
            df_periodo = df_filtrado[(df_filtrado[coluna_ativa_data] >= pd.to_datetime(d_inicio)) & (df_filtrado[coluna_ativa_data] <= pd.to_datetime(d_fim) + pd.Timedelta(days=1))]
    else:
        df_periodo = df_filtrado.copy()
            
    st.markdown("<br>", unsafe_allow_html=True)
    
    col_id = 'ID do Pedido' if 'ID do Pedido' in df_periodo.columns else ('ID do pedido' if 'ID do pedido' in df_periodo.columns else df_periodo.columns[0])
    col_status = 'Status do pedido' if 'Status do pedido' in df_periodo.columns else ('Status do Pedido' if 'Status do Pedido' in df_periodo.columns else None)
    col_motivo = 'Cancelar Motivo' if 'Cancelar Motivo' in df_periodo.columns else None
    
    # --- MÁSCARAS DE CLASSIFICAÇÃO RIGOROSA ---
    if col_status and col_status in df_periodo.columns:
        s = df_periodo[col_status].astype(str).str.strip().str.lower()
        
        if col_motivo and col_motivo in df_periodo.columns:
            motivo = df_periodo[col_motivo].astype(str).str.strip().str.lower()
            automatico_mask = motivo.str.contains('automático|automatico|sistema', na=False)
        else:
            automatico_mask = pd.Series(False, index=df_periodo.index)
            
        cancelados_mask = (s.eq('cancelado') | s.str.contains('pedido cancelado|reembolsado', na=False)) & (~automatico_mask)
        nao_pago_mask = s.str.contains('não pago|unpaid', na=False) | automatico_mask
        validados_mask = ~cancelados_mask & ~nao_pago_mask
        
        a_enviar_mask = validados_mask & s.str.contains('enviar|processando|pronto', na=False)
        enviado_mask = validados_mask & s.str.contains('enviado|trânsito|caminho', na=False)
        concluido_mask = validados_mask & s.str.contains('concluído|concluido|entregue|o comprador pode pedir', na=False)
        
        total_validos = df_periodo[validados_mask][col_id].nunique()
        nao_pago_cnt = df_periodo[nao_pago_mask][col_id].nunique()
        a_enviar_cnt = df_periodo[a_enviar_mask][col_id].nunique()
        enviado_cnt = df_periodo[enviado_mask][col_id].nunique()
        concluido_cnt = df_periodo[concluido_mask][col_id].nunique()
        cancelados_cnt = df_periodo[cancelados_mask][col_id].nunique()
    else:
        validados_mask = df_periodo.index.isin(df_periodo.index)
        cancelados_mask = pd.Series(False, index=df_periodo.index)
        nao_pago_mask = pd.Series(False, index=df_periodo.index)
        a_enviar_mask = pd.Series(False, index=df_periodo.index)
        enviado_mask = pd.Series(False, index=df_periodo.index)
        concluido_mask = validados_mask
        
        total_validos = df_periodo[col_id].nunique()
        nao_pago_cnt = 0
        a_enviar_cnt = 0
        enviado_cnt = 0
        concluido_cnt = total_validos
        cancelados_cnt = 0

    # Função de formatação para Real (R$)
    def fmt_val(val):
        return f"R$ {val:,.2f}".replace(',', 'X').replace('.', ',').replace('X', '.')

    # Totais gerais (Válidos)
    tot_produto_val = df_periodo[validados_mask]['Valor_Produto'].sum() if 'Valor_Produto' in df_periodo.columns else 0.0
    tot_sujo_val = df_periodo[validados_mask]['Valor_Sujo'].sum() if 'Valor_Sujo' in df_periodo.columns else 0.0
    
    # --- EXIBIÇÃO EM MÉTRICAS ---
    st.subheader(f"📊 Resumo de Pedidos ({opcao_tempo})")
    
    col1, col2, col3, col4, col5, col6 = st.columns(6)
    col1.metric("📦 Válidos", total_validos)
    col2.metric("⏳ Não pago", nao_pago_cnt)
    col3.metric("📤 A Enviar", a_enviar_cnt)
    col4.metric("🚚 Enviado", enviado_cnt)
    col5.metric("✅ Concluído", concluido_cnt)
    col6.metric("❌ Cancelados", cancelados_cnt)
    
    st.markdown("<br>", unsafe_allow_html=True)
    
    col_fat1, col_fat2 = st.columns(2)
    with col_fat1:
        st.metric("🎯 Montante de Produtos (Sem Frete / Sua Renda)", fmt_val(tot_produto_val))
    with col_fat2:
        st.metric("📦 Montante Bruto / Sujo (Com Frete)", fmt_val(tot_sujo_val))
    
    st.divider()
    
    # --- CÁLCULOS POR ABA ---
    def calc_aba(mask):
        p = df_periodo[mask]['Valor_Produto'].sum() if 'Valor_Produto' in df_periodo.columns else 0.0
        s = df_periodo[mask]['Valor_Sujo'].sum() if 'Valor_Sujo' in df_periodo.columns else 0.0
        return p, s

    p_val, s_val = calc_aba(validados_mask)
    p_naopag, s_naopag = calc_aba(nao_pago_mask)
    p_aenv, s_aenv = calc_aba(a_enviar_mask)
    p_env, s_env = calc_aba(enviado_mask)
    p_conc, s_conc = calc_aba(concluido_mask)
    p_canc, s_canc = calc_aba(cancelados_mask)

    # --- DETALHAMENTO INTERATIVO POR ABAS (TABS) LIMPAS ---
    st.subheader("📋 Detalhamento dos Pedidos do Período")
    
    tab_val, tab_naopag, tab_aenv, tab_env, tab_conc, tab_canc = st.tabs([
        f"📦 Válidos ({total_validos})",
        f"⏳ Não pago ({nao_pago_cnt})",
        f"📤 A Enviar ({a_enviar_cnt})",
        f"🚚 Enviado ({enviado_cnt})",
        f"✅ Concluído ({concluido_cnt})",
        f"❌ Cancelados ({cancelados_cnt})"
    ])
    
    def exibir_tabela_e_montantes(mask_filtro, prod_val, sujo_val, mostrar_motivo=False):
        if mask_filtro.sum() > 0:
            df_show = df_periodo[mask_filtro].copy()
            cols_exibir = [col_id, 'Data de criação do pedido']
            if 'Total global' in df_show.columns:
                cols_exibir.append('Total global')
            if 'Ajuste por participação em ação comercial' in df_show.columns:
                cols_exibir.append('Ajuste por participação em ação comercial')
            if 'Valor_Produto' in df_show.columns:
                cols_exibir.append('Valor_Produto')
            if 'Valor_Sujo' in df_show.columns:
                cols_exibir.append('Valor_Sujo')
            if col_status and col_status in df_show.columns:
                cols_exibir.append(col_status)
            if mostrar_motivo and col_motivo and col_motivo in df_show.columns:
                cols_exibir.append(col_motivo)
            if 'Nome do Produto' in df_show.columns:
                cols_exibir.append('Nome do Produto')
                
            df_show_fmt = df_show[cols_exibir].copy()
            if 'Valor_Produto' in df_show_fmt.columns:
                df_show_fmt['Montante Produto (Sem Frete)'] = df_show_fmt['Valor_Produto'].apply(fmt_val)
                df_show_fmt = df_show_fmt.drop(columns=['Valor_Produto'])
            if 'Valor_Sujo' in df_show_fmt.columns:
                df_show_fmt['Montante Bruto (Com Frete)'] = df_show_fmt['Valor_Sujo'].apply(fmt_val)
                df_show_fmt = df_show_fmt.drop(columns=['Valor_Sujo'])
                
            st.dataframe(df_show_fmt, use_container_width=True)
            
            # Exibe os montantes abaixo da tabela
            st.markdown(
                f"**Resumo da Categoria:** &nbsp;&nbsp; 🎯 **Montante de Produtos:** `{fmt_val(prod_val)}` &nbsp;&nbsp;|&nbsp;&nbsp; 📦 **Montante Bruto:** `{fmt_val(sujo_val)}`",
                unsafe_allow_html=True
            )
        else:
            st.info("Nenhum pedido encontrado nesta categoria para o período selecionado.")

    with tab_val:
        exibir_tabela_e_montantes(validados_mask, p_val, s_val)
        
    with tab_naopag:
        exibir_tabela_e_montantes(nao_pago_mask, p_naopag, s_naopag, mostrar_motivo=True)
        
    with tab_aenv:
        exibir_tabela_e_montantes(a_enviar_mask, p_aenv, s_aenv)
        
    with tab_env:
        exibir_tabela_e_montantes(enviado_mask, p_env, s_env)
        
    with tab_conc:
        exibir_tabela_e_montantes(concluido_mask, p_conc, s_conc)
        
    with tab_canc:
        exibir_tabela_e_montantes(cancelados_mask, p_canc, s_canc, mostrar_motivo=True)

    st.divider()
    
    st.subheader("🔍 Consultar Pedido Específico")
    pedido_id = st.text_input("Digite o ID do Pedido (Ex: 230910ABCDEF):").strip()
    
    if pedido_id:
        if col_id in df.columns:
            resultado = df[df[col_id].astype(str).str.contains(pedido_id, case=False, na=False)]
            
            if not resultado.empty:
                st.success(f"✅ Encontrado(s) registo(s) para este ID:")
                cols_mostrar = [c for c in [col_id, col_status, col_motivo, 'Nome do Produto', 'Total global', 'Ajuste por participação em ação comercial', 'Valor_Produto', 'Valor_Sujo', 'Data de criação do pedido'] if c and c in resultado.columns]
                res_fmt = resultado[cols_mostrar].copy()
                if 'Valor_Produto' in res_fmt.columns:
                    res_fmt['Montante Produto'] = res_fmt['Valor_Produto'].apply(fmt_val)
                    res_fmt = res_fmt.drop(columns=['Valor_Produto'])
                if 'Valor_Sujo' in res_fmt.columns:
                    res_fmt['Montante Bruto'] = res_fmt['Valor_Sujo'].apply(fmt_val)
                    res_fmt = res_fmt.drop(columns=['Valor_Sujo'])
                st.dataframe(res_fmt, use_container_width=True)
            else:
                st.error("❌ Pedido não encontrado.")
        else:
            st.error("A coluna de ID de pedido não existe nas planilhas.")
            
    st.divider()
    with st.expander("Ver lista de pedidos (Tabela Completa do Período)"):
        tabela_visual = df_periodo.drop(columns=['Valor_Sujo', 'Valor_Produto'], errors='ignore')
        if 'Data_Criacao' in tabela_visual.columns:
            tabela_visual['Data Criação'] = tabela_visual['Data_Criacao'].dt.strftime('%d/%m/%Y %H:%M')
        st.dataframe(tabela_visual, use_container_width=True)
else:
    st.info("A pasta está vazia ou a aguardar ficheiros. Adicione a sua primeira folha de cálculo no Google Drive!")
