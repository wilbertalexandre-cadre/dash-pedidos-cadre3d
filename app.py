import streamlit as st
import pandas as pd
import json
import io
from datetime import datetime, timedelta
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

st.set_page_config(page_title="Dashboard Cadre 3D", page_icon="📦", layout="wide")

st.title("📦 Dashboard de Vendas - Cadre 3D")
st.markdown("Acompanhe os seus resultados e consulte o estado dos pedidos.")

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
                
            # --- TRATAMENTO DA DATA OFICIAL: Hora do pagamento do pedido (Coluna L) ---
            if 'Hora do pagamento do pedido' in df_limpo.columns:
                df_limpo['Data'] = pd.to_datetime(df_limpo['Hora do pagamento do pedido'], errors='coerce')
            elif 'Data de criação do pedido' in df_limpo.columns:
                df_limpo['Data'] = pd.to_datetime(df_limpo['Data de criação do pedido'], errors='coerce')
            elif 'Data' in df_limpo.columns:
                df_limpo['Data'] = pd.to_datetime(df_limpo['Data'], dayfirst=True, errors='coerce')
                
            # CÁLCULO DO VALOR UNITÁRIO DA LINHA: Preço acordado (R) * Quantidade (S)
            if 'Preço acordado' in df_limpo.columns and 'Quantidade' in df_limpo.columns:
                preco = df_limpo['Preço acordado'].astype(str).str.replace('R$', '', regex=False)
                preco = preco.str.replace('.', '', regex=False)
                preco = preco.str.replace(',', '.', regex=False)
                preco = pd.to_numeric(preco, errors='coerce').fillna(0)
                
                qtd = pd.to_numeric(df_limpo['Quantidade'], errors='coerce').fillna(0)
                df_limpo['Valor_Item'] = preco * qtd
            elif 'Valor' in df_limpo.columns:
                valor_seg = df_limpo['Valor'].astype(str).str.replace('R$', '', regex=False).str.replace('.', '', regex=False).str.replace(',', '.', regex=False)
                df_limpo['Valor_Item'] = pd.to_numeric(valor_seg, errors='coerce').fillna(0)
            else:
                df_limpo['Valor_Item'] = 0.0
                
            # --- AGRUPAMENTO POR ID DO PEDIDO (Considera 1 pedido por ID, soma valores e mantém a data de pagamento) ---
            if 'ID do Pedido' in df_limpo.columns:
                # Vamos consolidar por ID do pedido
                regras_agrupamento = {
                    'Valor_Item': 'sum',
                    'Data': 'first'
                }
                if 'Status do pedido' in df_limpo.columns:
                    regras_agrupamento['Status do pedido'] = 'first'
                if 'Nome do Produto' in df_limpo.columns:
                    regras_agrupamento['Nome do Produto'] = lambda x: ' + '.join(x.dropna().astype(str).unique())
                
                df_agrupado = df_limpo.groupby('ID do Pedido', as_index=False).agg(regras_agrupamento)
                df_agrupado.rename(columns={'Valor_Item': 'Valor_Numerico'}, inplace=True)
                return df_agrupado
            else:
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
    
    if 'Data' not in df.columns:
        st.warning("⚠ Atenção: Não foi encontrada coluna de data válida.")
        df_filtrado = df
    else:
        st.sidebar.header("🎛️ Filtros do Painel")
        
        opcao_tempo = st.sidebar.selectbox(
            "Período (Base: Pagamento):", 
            ["Todo o período", "Este mês", "Últimos 30 dias", "Últimos 7 dias", "Personalizado"]
        )
        
        filtro_status = st.sidebar.selectbox(
            "Estado dos pedidos:",
            ["Apenas Concluídos (Padrão Shopee)", "Todos (Geral)"]
        )
        
        hoje = pd.Timestamp.today().normalize()
        df_filtrado = df.copy()
        
        # Filtro de Tempo
        if opcao_tempo == "Este mês":
            inicio = hoje.replace(day=1)
            df_filtrado = df_filtrado[df_filtrado['Data'] >= inicio]
        elif opcao_tempo == "Últimos 30 dias":
            inicio = hoje - pd.Timedelta(days=30)
            df_filtrado = df_filtrado[df_filtrado['Data'] >= inicio]
        elif opcao_tempo == "Últimos 7 dias":
            inicio = hoje - pd.Timedelta(days=7)
            df_filtrado = df_filtrado[df_filtrado['Data'] >= inicio]
        elif opcao_tempo == "Personalizado":
            d_inicio = st.sidebar.date_input("Data Inicial", hoje - pd.Timedelta(days=30))
            d_fim = st.sidebar.date_input("Data Final", hoje)
            df_filtrado = df_filtrado[(df_filtrado['Data'] >= pd.to_datetime(d_inicio)) & (df_filtrado['Data'] <= pd.to_datetime(d_fim) + pd.Timedelta(days=1))]
                
        # Filtro de Status
        if filtro_status == "Apenas Concluídos (Padrão Shopee)" and 'Status do pedido' in df_filtrado.columns:
            df_filtrado = df_filtrado[df_filtrado['Status do pedido'].str.lower() == 'concluído']
                
    st.subheader("📊 Visão Geral (Consolidado por Pedido)")
    
    # Cada linha agora é um ID de pedido único consolidado
    total_pedidos = len(df_filtrado)
    valor_total = df_filtrado['Valor_Numerico'].sum() if 'Valor_Numerico' in df_filtrado.columns else 0
    valor_formatado = f"R$ {valor_total:,.2f}".replace(',', 'X').replace('.', ',').replace('X', '.')
    
    col_m1, col_m2 = st.columns(2)
    col_m1.metric("📦 Total de Pedidos (IDs Únicos)", total_pedidos)
    col_m2.metric("💰 Faturamento Total Consolidado", valor_formatado)
    
    st.divider()
    
    st.subheader("🔍 Consultar Pedido Específico")
    pedido_id = st.text_input("Digite o ID do Pedido (Ex: 230910ABCDEF):").strip()
    
    if pedido_id:
        if 'ID do Pedido' in df.columns:
            resultado = df[df['ID do Pedido'].astype(str).str.contains(pedido_id, case=False, na=False)]
            
            if not resultado.empty:
                st.success(f"✅ Encontrado(s) registo(s) para este ID:")
                st.dataframe(resultado, use_container_width=True)
            else:
                st.error("❌ Pedido não encontrado.")
        else:
            st.error("A coluna 'ID do Pedido' não existe nas planilhas.")
            
    st.divider()
    with st.expander("Ver lista consolidada de pedidos"):
        tabela_visual = df_filtrado.drop(columns=['Valor_Numerico'], errors='ignore')
        if 'Data' in tabela_visual.columns:
            tabela_visual['Data'] = tabela_visual['Data'].dt.strftime('%d/%m/%Y %H:%M')
        st.dataframe(tabela_visual, use_container_width=True)
else:
    st.info("A pasta está vazia ou a aguardar ficheiros. Adicione a sua primeira folha de cálculo no Google Drive!")
