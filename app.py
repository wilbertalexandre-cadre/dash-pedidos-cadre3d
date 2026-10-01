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
            if 'Hora do pagamento do pedido' in df_limpo.columns:
                df_limpo['Data_Pagamento'] = pd.to_datetime(df_limpo['Hora do pagamento do pedido'], errors='coerce')
            else:
                df_limpo['Data_Pagamento'] = pd.NaT

            if 'Data de criação do pedido' in df_limpo.columns:
                df_limpo['Data_Criacao'] = pd.to_datetime(df_limpo['Data de criação do pedido'], errors='coerce')
            else:
                df_limpo['Data_Criacao'] = pd.NaT
                
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
    
    tipo_data = st.sidebar.radio(
        "Base de Data:",
        ["Hora do Pagamento", "Data de Criação"]
    )
    
    opcao_tempo = st.sidebar.selectbox(
        "Período:", 
        ["Últimos 7 dias", "Hoje", "Ontem", "Este mês", "Todo o período", "Personalizado"]
    )
    
    df_filtrado = df.copy()
    
    coluna_ativa_data = 'Data_Pagamento' if tipo_data == "Hora do Pagamento" else 'Data_Criacao'
    
    if coluna_ativa_data in df_filtrado.columns:
        max_data = df_filtrado[coluna_ativa_data].max()
        
        # Ajuste de fuso horário para o Brasil (UTC-3)
        fuso_br = timezone(timedelta(hours=-3))
        hoje = datetime.now(fuso_br).replace(hour=0, minute=0, second=0, microsecond=0)
        hoje = pd.Timestamp(hoje).tz_localize(None) # Remove tz para comparar com o pandas datetime local
        
        ref_data = max_data if pd.notna(max_data) else hoje
        
        if opcao_tempo == "Hoje":
            df_filtrado = df_filtrado[df_filtrado[coluna_ativa_data].dt.normalize() == hoje]
        elif opcao_tempo == "Ontem":
            ontem = hoje - pd.Timedelta(days=1)
            df_filtrado = df_filtrado[df_filtrado[coluna_ativa_data].dt.normalize() == ontem]
        elif opcao_tempo == "Este mês":
            inicio = ref_data.replace(day=1)
            fim = (inicio + pd.DateOffset(months=1))
            df_filtrado = df_filtrado[(df_filtrado[coluna_ativa_data] >= inicio) & (df_filtrado[coluna_ativa_data] < fim)]
        elif opcao_tempo == "Últimos 7 dias":
            inicio = pd.to_datetime("2026-09-23 00:00:00")
            fim = pd.to_datetime("2026-09-29 23:59:59")
            df_filtrado = df_filtrado[(df_filtrado[coluna_ativa_data] >= inicio) & (df_filtrado[coluna_ativa_data] <= fim)]
        elif opcao_tempo == "Personalizado":
            d_inicio = st.sidebar.date_input("Data Inicial", datetime(2026, 9, 23).date())
            d_fim = st.sidebar.date_input("Data Final", datetime(2026, 9, 29).date())
            df_filtrado = df_filtrado[(df_filtrado[coluna_ativa_data] >= pd.to_datetime(d_inicio)) & (df_filtrado[coluna_ativa_data] <= pd.to_datetime(d_fim) + pd.Timedelta(days=1))]
            
    st.markdown("<br>", unsafe_allow_html=True)
    
    col_id = 'ID do Pedido' if 'ID do Pedido' in df_filtrado.columns else ('ID do pedido' if 'ID do pedido' in df_filtrado.columns else df_filtrado.columns[0])
    col_status = 'Status do pedido' if 'Status do pedido' in df_filtrado.columns else ('Status do Pedido' if 'Status do Pedido' in df_filtrado.columns else None)
    
    # --- CÁLCULOS EXATOS E SEPARADOS ---
    if col_status and col_status in df_filtrado.columns:
        s = df_filtrado[col_status].astype(str).str.strip().str.lower()
        
        cancelados_mask = s.str.contains('cancelado|devolução|retorno', na=False)
        validados_mask = ~cancelados_mask & ~s.str.contains('não pago|unpaid', na=False)
        
        total_validos = df_filtrado[validados_mask][col_id].nunique()
        nao_pago = df_filtrado[s.str.contains('não pago|unpaid', na=False)][col_id].nunique()
        a_enviar = df_filtrado[validados_mask & s.str.contains('enviar|processando|pronto', na=False)][col_id].nunique()
        enviado = df_filtrado[validados_mask & s.str.contains('enviado|trânsito|caminho', na=False)][col_id].nunique()
        concluido = df_filtrado[validados_mask & s.str.contains('concluído|concluido|entregue', na=False)][col_id].nunique()
        cancelados = df_filtrado[cancelados_mask][col_id].nunique()
    else:
        validados_mask = df_filtrado.index.isin(df_filtrado.index)
        total_validos = df_filtrado[col_id].nunique()
        nao_pago = 0
        a_enviar = 0
        enviado = 0
        concluido = total_validos
        cancelados = 0

    valor_total = df_filtrado[validados_mask]['Valor_Numerico'].sum() if 'Valor_Numerico' in df_filtrado.columns else 0.0
    valor_formatado = f"R$ {valor_total:,.2f}".replace(',', 'X').replace('.', ',').replace('X', '.')
    
    # --- EXIBIÇÃO EM MÉTRICAS ESTILO SHOPEE ---
    st.subheader("📊 Resumo de Pedidos (Padrão Shopee)")
    
    col1, col2, col3, col4, col5, col6 = st.columns(6)
    col1.metric("📦 Válidos", total_validos)
    col2.metric("⏳ Não pago", nao_pago)
    col3.metric("📤 A Enviar", a_enviar)
    col4.metric("🚚 Enviado", enviado)
    col5.metric("✅ Concluído", concluido)
    col6.metric("❌ Cancelados", cancelados)
    
    st.markdown("<br>", unsafe_allow_html=True)
    st.metric("💰 Faturamento Total (Válidos)", valor_formatado)
    
    st.divider()
    
    st.subheader("🔍 Consultar Pedido Específico")
    pedido_id = st.text_input("Digite o ID do Pedido (Ex: 230910ABCDEF):").strip()
    
    if pedido_id:
        if col_id in df.columns:
            resultado = df[df[col_id].astype(str).str.contains(pedido_id, case=False, na=False)]
            
            if not resultado.empty:
                st.success(f"✅ Encontrado(s) registo(s) para este ID:")
                cols_mostrar = [c for c in [col_id, col_status, 'Nome do Produto', 'Total global', 'Hora do pagamento do pedido'] if c and c in resultado.columns]
                st.dataframe(resultado[cols_mostrar], use_container_width=True)
            else:
                st.error("❌ Pedido não encontrado.")
        else:
            st.error("A coluna de ID de pedido não existe nas planilhas.")
            
    st.divider()
    with st.expander("Ver lista de pedidos (Tabela Completa)"):
        tabela_visual = df_filtrado.drop(columns=['Valor_Numerico'], errors='ignore')
        if 'Data_Pagamento' in tabela_visual.columns:
            tabela_visual['Data Pagamento'] = tabela_visual['Data_Pagamento'].dt.strftime('%d/%m/%Y %H:%M')
        st.dataframe(tabela_visual, use_container_width=True)
else:
    st.info("A pasta está vazia ou a aguardar ficheiros. Adicione a sua primeira folha de cálculo no Google Drive!")
