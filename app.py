import streamlit as st
import pandas as pd
import json
import io
from datetime import datetime, timedelta
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

# Alterei o layout para 'wide' para o dashboard ter mais espaço
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
            
            # Remover duplicados pelo ID do Pedido
            if 'ID do Pedido' in df_completo.columns:
                df_limpo = df_completo.drop_duplicates(subset=['ID do Pedido'], keep='last').copy()
            else:
                df_limpo = df_completo.copy()
                
            # --- LIMPEZA DE DADOS PARA OS CÁLCULOS ---
            # 1. Transformar a coluna 'Data' em formato de Data real (se a coluna existir)
            if 'Data' in df_limpo.columns:
                df_limpo['Data'] = pd.to_datetime(df_limpo['Data'], dayfirst=True, errors='coerce')
                
            # 2. Limpar a coluna 'Valor' (tirar R$, pontos e transformar vírgula em ponto para o Python somar)
            if 'Valor' in df_limpo.columns:
                df_limpo['Valor_Numerico'] = df_limpo['Valor'].astype(str).str.replace('R$', '', regex=False)
                df_limpo['Valor_Numerico'] = df_limpo['Valor_Numerico'].str.replace('.', '', regex=False)
                df_limpo['Valor_Numerico'] = df_limpo['Valor_Numerico'].str.replace(',', '.', regex=False)
                df_limpo['Valor_Numerico'] = pd.to_numeric(df_limpo['Valor_Numerico'], errors='coerce').fillna(0)
                
            return df_limpo
            
    except Exception as e:
        st.error(f"Erro de ligação com o Drive: {e}")
        return None

# --- TOP BAR COM BOTÃO DE ATUALIZAÇÃO ---
col_vazia, col_btn = st.columns([4, 1])
with col_btn:
    if st.button("🔄 Forçar Atualização dos Ficheiros", use_container_width=True):
        carregar_dados_do_drive.clear()

# Carregar os dados
df = carregar_dados_do_drive()

if df is not None and not df.empty:
    
    # Verificação de segurança: A coluna Data existe?
    if 'Data' not in df.columns:
        st.warning("⚠️ Atenção: Não foi encontrada uma coluna chamada 'Data' nos seus ficheiros. Os filtros de tempo e resumos precisam dessa coluna para funcionar (ex: 30/09/2026).")
        df_filtrado = df
    else:
        # --- ÁREA DE FILTROS ---
        st.subheader("📊 Visão Geral")
        
        col_filtro, col_data, _ = st.columns([2, 2, 2])
        
        with col_filtro:
            opcao_tempo = st.selectbox(
                "Filtrar por período:", 
                ["Todo o período", "Esta semana", "Últimos 7 dias", "Este mês", "Últimos 30 dias", "Período personalizado"]
            )
        
        hoje = pd.Timestamp.today().normalize()
        df_filtrado = df.copy()
        
        if opcao_tempo == "Esta semana":
            # Assume que a semana começa à segunda-feira
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
                datas = st.date_input("Selecione o intervalo (Início - Fim):", [hoje - pd.Timedelta(days=7), hoje])
            
            if len(datas) == 2:
                # Converte as datas selecionadas
                data_inicio = pd.to_datetime(datas[0])
                data_fim = pd.to_datetime(datas[1])
                df_filtrado = df[(df['Data'] >= data_inicio) & (df['Data'] <= data_fim)]
            else:
                st.info("Por favor, selecione a data de fim.")
                
    # --- ÁREA DE MÉTRICAS (CARTÕES) ---
    st.markdown("<br>", unsafe_allow_html=True) # Espaço visual
    
    qtd_pedidos = len(df_filtrado)
    
    # Soma os valores se a coluna numérica existir
    valor_total = 0
    if 'Valor_Numerico' in df_filtrado.columns:
        valor_total = df_filtrado['Valor_Numerico'].sum()
        
    # Formatação do valor para padrão brasileiro/português (1.234,56)
    valor_formatado = f"R$ {valor_total:,.2f}".replace(',', 'X').replace('.', ',').replace('X', '.')
    
    col_metric1, col_metric2, col_metric3 = st.columns(3)
    col_metric1.metric("📦 Quantidade de Pedidos", qtd_pedidos)
    col_metric2.metric("💰 Valor Total", valor_formatado)
    
    st.divider()
    
    # --- ÁREA DE PESQUISA INDIVIDUAL ---
    st.subheader("🔍 Consultar Pedido Específico")
    pedido_id = st.text_input("Digite o ID do Pedido (Ex: 230910ABCDEF):").strip()
    
    if pedido_id:
        if 'ID do Pedido' in df.columns:
            resultado = df[df['ID do Pedido'].astype(str).str.contains(pedido_id, case=False, na=False)]
            
            if not resultado.empty:
                st.success("✅ Pedido localizado!")
                info = resultado.iloc[0]
                
                col_res1, col_res2, col_res3 = st.columns(3)
                col_res1.metric("Valor", f"R$ {info.get('Valor', 'N/A')}")
                col_res2.metric("Status", info.get('Status', 'N/A'))
                col_res3.metric("ID", info.get('ID do Pedido', 'N/A'))
                
                if 'Observações' in info and pd.notna(info['Observações']):
                    st.info(f"Observações: {info['Observações']}")
            else:
                st.error("❌ Pedido não encontrado.")
        else:
            st.error("A coluna 'ID do Pedido' não existe nas planilhas.")
            
    st.divider()
    with st.expander("Ver lista de pedidos (Tabela Completa)"):
        # Mostra a tabela sem a coluna técnica que criámos
        tabela_visual = df_filtrado.drop(columns=['Valor_Numerico'], errors='ignore')
        
        # Formatar a data para ficar bonita na tabela antes de mostrar
        if 'Data' in tabela_visual.columns:
            tabela_visual['Data'] = tabela_visual['Data'].dt.strftime('%d/%m/%Y')
            
        st.dataframe(tabela_visual, use_container_width=True)
else:
    st.info("A pasta está vazia ou a aguardar ficheiros. Adicione a sua primeira folha de cálculo no Google Drive!")
