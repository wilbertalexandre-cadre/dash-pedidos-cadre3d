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
                
            # --- TRATAMENTO DA DATA OFICIAL: Hora do pagamento do pedido ---
            if 'Hora do pagamento do pedido' in df_limpo.columns:
                df_limpo['Data'] = pd.to_datetime(df_limpo['Hora do pagamento do pedido'], errors='coerce')
            elif 'Data de criação do pedido' in df_limpo.columns:
                df_limpo['Data'] = pd.to_datetime(df_limpo['Data de criação do pedido'], errors='coerce')
            elif 'Data' in df_limpo.columns:
                df_limpo['Data'] = pd.to_datetime(df_limpo['Data'], dayfirst=True, errors='coerce')
                
            # CÁLCULO DO VALOR: Preço acordado * Quantidade
            if 'Preço acordado' in df_limpo.columns and 'Quantidade' in df_limpo.columns:
                preco = df_limpo['Preço acordado'].astype(str).str.replace('R$', '', regex=False)
                preco = preco.str.replace('.', '', regex=False)
                preco = preco.str.replace(',', '.', regex=False)
                preco = pd.to_numeric(preco, errors='coerce').fillna(0)
                
                qtd = pd.to_numeric(df_limpo['Quantidade'], errors='coerce').fillna(0)
                df_limpo['Valor_Numerico'] = preco * qtd
            elif 'Valor' in df_limpo.columns:
                valor_seg = df_limpo['Valor'].astype(str).str.replace('R$', '', regex=False).str.replace('.', '', regex=False).str.replace(',', '.', regex=False)
                df_limpo['Valor_Numerico'] = pd.to_numeric(valor_seg, errors='coerce').fillna(0)
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
    
    if 'Data' not in df.columns:
        st.warning("⚠️️ Atenção: Não foi encontrada coluna de data válida. Verifique se a coluna 'Hora do pagamento do pedido' está presente nas planilhas.")
        df_filtrado = df
    else:
        st.subheader("📊 Visão Geral")
        
        col_filtro, col_data, _ = st.columns([2, 2, 2])
        
        with col_filtro:
            opcao_tempo = st.selectbox(
                "Filtrar por período (com base na Hora do Pagamento):", 
                ["Todo o período", "Esta semana", "Últimos 7 dias", "Este mês", "Últimos 30 dias", "Período personalizado"]
            )
        
        hoje = pd.Timestamp.today().normalize()
        df_filtrado = df.copy()
        
        if opcao_tempo == "Esta semana":
            inicio = hoje - pd.Timedelta(days=hoje.weekday())
            df_filtrado = df[df['Data'] >= inicio]
        elif opcao_tempo == "Últimos 7 dias":
            inicio = hoje - pd.Timedelta(days=7)
            df_filtrado = df[df['Data'] >= inicio]
        elif opcao_tempo == "Este mês":
            inicio = hoje.replace(day=1)
            df_filtrado = df[df['Data'] >= inicio]
        elif opcao_tempo == "Últimos 30 dias":
            inicio = hoje - pd.Timedelta(days=30)
            df_filtrado = df[df['Data'] >= inicio]
        elif opcao_tempo == "Período personalizado":
            with col_data:
                datas = st.date_input("Selecione o intervalo:", [hoje - pd.Timedelta(days=7), hoje])
            if len(datas) == 2:
                df_filtrado = df[(df['Data'] >= pd.to_datetime(datas[0])) & (df['Data'] <= pd.to_datetime(datas[1]))]
                
    st.markdown("<br>", unsafe_allow_html=True)
    
    total_pedidos_unicos = df_filtrado['ID do Pedido'].nunique() if 'ID do Pedido' in df_filtrado.columns else len(df_filtrado)
    total_itens_vendidos = len(df_filtrado)
    valor_total = df_filtrado['Valor_Numerico'].sum() if 'Valor_Numerico' in df_filtrado.columns else 0
    valor_formatado = f"R$ {valor_total:,.2f}".replace(',', 'X').replace('.', ',').replace('X', '.')
    
    col_m1, col_m2, col_m3 = st.columns(3)
    col_m1.metric("📦 Pedidos Únicos (Shopee)", total_pedidos_unicos)
    col_m2.metric("🏷️ Total de Itens/Linhas", total_itens_vendidos)
    col_m3.metric("💰 Faturamento Total", valor_formatado)
    
    st.divider()
    
    st.subheader("🔍 Consultar Pedido Específico")
    pedido_id = st.text_input("Digite o ID do Pedido (Ex: 230910ABCDEF):").strip()
    
    if pedido_id:
        if 'ID do Pedido' in df.columns:
            resultado = df[df['ID do Pedido'].astype(str).str.contains(pedido_id, case=False, na=False)]
            
            if not resultado.empty:
                st.success(f"✅ Encontrado(s) {len(resultado)} registo(s) para este ID:")
                st.dataframe(resultado[['ID do Pedido', 'Status do pedido', 'Nome do Produto', 'Preço acordado', 'Quantidade', 'Hora do pagamento do pedido']], use_container_width=True)
            else:
                st.error("❌ Pedido não encontrado.")
        else:
            st.error("A coluna 'ID do Pedido' não existe nas planilhas.")
            
    st.divider()
    with st.expander("Ver lista de pedidos (Tabela Completa)"):
        tabela_visual = df_filtrado.drop(columns=['Valor_Numerico'], errors='ignore')
        if 'Data' in tabela_visual.columns:
            tabela_visual['Data'] = tabela_visual['Data'].dt.strftime('%d/%m/%Y %H:%M')
        st.dataframe(tabela_visual, use_container_width=True)
else:
    st.info("A pasta está vazia ou a aguardar ficheiros. Adicione a sua primeira folha de cálculo no Google Drive!")
