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
                
            # --- CONVERSÃO DAS DATAS (Validação primária por Data de Criação) ---
            if 'Data de criação do pedido' in df_limpo.columns:
                df_limpo['Data_Criacao'] = pd.to_datetime(df_limpo['Data de criação do pedido'], errors='coerce')
            else:
                df_limpo['Data_Criacao'] = pd.NaT

            if 'Hora do pagamento do pedido' in df_limpo.columns:
                df_limpo['Data_Pagamento'] = pd.to_datetime(df_limpo['Hora do pagamento do pedido'], errors='coerce')
            else:
                df_limpo['Data_Pagamento'] = pd.NaT
                
            # --- TRATAMENTO PRECISO DO VALOR USANDO 'Total global' ---
            if 'Total global' in df_limpo.columns:
                val_col = df_limpo['Total global']
                if val_col.dtype == object:
                    val_str = val_col.astype(str).str.replace('R$', '', regex=False).str.strip()
                    val_str = val_str.str.replace(',', '.', regex=False)
                    val_num = pd.to_numeric(val_str, errors='coerce').fillna(0)
                else:
                    val_num = pd.to_numeric(val_col, errors='coerce').fillna(0)
                df_limpo['Valor_Numerico'] = val_num
            elif 'Preço acordado' in df_limpo.columns:
                p_str = df_limpo['Preço acordado'].astype(str).str.replace('R$', '', regex=False).str.replace(',', '.', regex=False)
                df_limpo['Valor_Numerico'] = pd.to_numeric(p_str, errors='coerce').fillna(0)
            else:
                df_limpo['Valor_Numerico'] = 0.0
                
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
    
    # --- TRATAMENTO INTELIGENTE DE CANCELADOS / NÃO PAGOS ---
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
        
        total_validos = df_periodo[validados_mask][col_id].nunique()
        nao_pago = df_periodo[nao_pago_mask][col_id].nunique()
        a_enviar = df_periodo[validados_mask & s.str.contains('enviar|processando|pronto', na=False)][col_id].nunique()
        enviado = df_periodo[validados_mask & s.str.contains('enviado|trânsito|caminho', na=False)][col_id].nunique()
        concluido = df_periodo[validados_mask & s.str.contains('concluído|concluido|entregue', na=False)][col_id].nunique()
        cancelados = df_periodo[cancelados_mask][col_id].nunique()
    else:
        validados_mask = df_periodo.index.isin(df_periodo.index)
        cancelados_mask = pd.Series(False, index=df_periodo.index)
        total_validos = df_periodo[col_id].nunique()
        nao_pago = 0
        a_enviar = 0
        enviado = 0
        concluido = total_validos
        cancelados = 0

    valor_total = df_periodo[validados_mask]['Valor_Numerico'].sum() if 'Valor_Numerico' in df_periodo.columns else 0.0
    valor_formatado = f"R$ {valor_total:,.2f}".replace(',', 'X').replace('.', ',').replace('X', '.')
    
    # --- EXIBIÇÃO EM MÉTRICAS ESTILO SHOPEE ---
    st.subheader(f"📊 Resumo de Pedidos ({opcao_tempo})")
    
    col1, col2, col3, col4, col5, col6 = st.columns(6)
    col1.metric("📦 Válidos", total_validos)
    col2.metric("⏳ Não pago", nao_pago)
    col3.metric("📤 A Enviar", a_enviar)
    col4.metric("🚚 Enviado", enviado)
    col5.metric("✅ Concluído", concluido)
    col6.metric("❌ Cancelados", cancelados)
    
    st.markdown("<br>", unsafe_allow_html=True)
    st.metric(f"💰 Faturamento Total (Válidos)", valor_formatado)
    
    st.divider()
    
    # --- DETALHAMENTO DE PEDIDOS VÁLIDOS E CANCELADOS DO PERÍODO ---
    st.subheader("📋 Detalhamento dos Pedidos do Período")
    
    tab_val, tab_canc = st.tabs([f"✅ Pedidos Válidos ({total_validos})", f"❌ Pedidos Cancelados ({cancelados})"])
    
    with tab_val:
        if total_validos > 0:
            df_v_show = df_periodo[validados_mask].copy()
            cols_exibir = [col_id, 'Data de criação do pedido']
            if 'Total global' in df_v_show.columns:
                cols_exibir.append('Total global')
            elif 'Preço acordado' in df_v_show.columns:
                cols_exibir.append('Preço acordado')
            if col_status and col_status in df_v_show.columns:
                cols_exibir.append(col_status)
            if 'Nome do Produto' in df_v_show.columns:
                cols_exibir.append('Nome do Produto')
                
            st.dataframe(df_v_show[cols_exibir], use_container_width=True)
        else:
            st.info("Nenhum pedido válido encontrado neste período.")
            
    with tab_canc:
        if cancelados > 0:
            df_c_show = df_periodo[cancelados_mask].copy()
            cols_exibir_c = [col_id, 'Data de criação do pedido']
            if 'Total global' in df_c_show.columns:
                cols_exibir_c.append('Total global')
            elif 'Preço acordado' in df_c_show.columns:
                cols_exibir_c.append('Preço acordado')
            if col_status and col_status in df_c_show.columns:
                cols_exibir_c.append(col_status)
            if col_motivo and col_motivo in df_c_show.columns:
                cols_exibir_c.append(col_motivo)
            if 'Nome do Produto' in df_c_show.columns:
                cols_exibir_c.append('Nome do Produto')
                
            st.dataframe(df_c_show[cols_exibir_c], use_container_width=True)
        else:
            st.success("Nenhum pedido cancelado neste período! 🎉")

    st.divider()
    
    st.subheader("🔍 Consultar Pedido Específico")
    pedido_id = st.text_input("Digite o ID do Pedido (Ex: 230910ABCDEF):").strip()
    
    if pedido_id:
        if col_id in df.columns:
            resultado = df[df[col_id].astype(str).str.contains(pedido_id, case=False, na=False)]
            
            if not resultado.empty:
                st.success(f"✅ Encontrado(s) registo(s) para este ID:")
                cols_mostrar = [c for c in [col_id, col_status, col_motivo, 'Nome do Produto', 'Total global', 'Data de criação do pedido'] if c and c in resultado.columns]
                st.dataframe(resultado[cols_mostrar], use_container_width=True)
            else:
                st.error("❌ Pedido não encontrado.")
        else:
            st.error("A coluna de ID de pedido não existe nas planilhas.")
            
    st.divider()
    with st.expander("Ver lista de pedidos (Tabela Completa do Período)"):
        tabela_visual = df_periodo.drop(columns=['Valor_Numerico'], errors='ignore')
        if 'Data_Criacao' in tabela_visual.columns:
            tabela_visual['Data Criação'] = tabela_visual['Data_Criacao'].dt.strftime('%d/%m/%Y %H:%M')
        st.dataframe(tabela_visual, use_container_width=True)
else:
    st.info("A pasta está vazia ou a aguardar ficheiros. Adicione a sua primeira folha de cálculo no Google Drive!")
