import streamlit as st
import pandas as pd
import json
import io
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

st.set_page_config(page_title="Dashboard Cadre 3D", page_icon="📦", layout="centered")
st.title("📦 Controle de Pedidos - Cadre 3D")
st.markdown("Consulta automática de recebimentos direto do Google Drive.")

@st.cache_data(ttl=120) # Atualiza automaticamente a cada 2 minutos
def carregar_dados_do_drive():
    try:
        # Puxa a chave secreta que vamos configurar no Streamlit
        cert_info = json.loads(st.secrets["google_credentials"])
        credenciais = service_account.Credentials.from_service_account_info(
            cert_info, scopes=['https://www.googleapis.com/auth/drive.readonly']
        )
        servico = build('drive', 'v3', credentials=credenciais)
        
        # ID da sua pasta de vendas
        pasta_id = '1p0H9A9-0r8QCX34koCd3mrsyXmTtTzUQ'
        query = f"'{pasta_id}' in parents and trashed=false"
        resultados = servico.files().list(q=query, fields="files(id, name, mimeType)").execute()
        arquivos = resultados.get('files', [])
        
        if not arquivos:
            return pd.DataFrame()
            
        dfs = []
        for arq in arquivos:
            request = servico.files().get_media(fileId=arq['id'])
            
            # Se for uma Planilha nativa do Google
            if arq['mimeType'] == 'application/vnd.google-apps.spreadsheet':
                request = servico.files().export_media(fileId=arq['id'], mimeType='text/csv')
                arquivo_baixado = io.BytesIO(request.execute())
                df = pd.read_csv(arquivo_baixado)
            # Se for um arquivo Excel (.xlsx) ou CSV que você subiu
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
            
            # Remove duplicatas mantendo o status mais atualizado
            if 'ID do Pedido' in df_completo.columns:
                df_limpo = df_completo.drop_duplicates(subset=['ID do Pedido'], keep='last')
                return df_limpo
            return df_completo
            
    except Exception as e:
        st.error(f"Erro de conexão com o Drive: {e}")
        return None

# Interface do Dashboard
df = carregar_dados_do_drive()

if df is not None and not df.empty:
    st.divider()
    pedido_id = st.text_input("🔍 Digite o ID do Pedido (Ex: 230910ABCDEF):").strip()
    
    if pedido_id:
        resultado = df[df['ID do Pedido'].astype(str).str.contains(pedido_id, case=False, na=False)]
        
        if not resultado.empty:
            st.success("✅ Pedido localizado!")
            info = resultado.iloc[0]
            
            col1, col2, col3 = st.columns(3)
            col1.metric("Valor", f"R$ {info.get('Valor', 'N/A')}")
            col2.metric("Status", info.get('Status', 'N/A'))
            col3.metric("ID", info['Perfeito, pode enviar! É só fazer o upload ou colar o conteúdo dele aqui. 

Me diga também o que vamos aprontar com ele hoje — seja analisar métricas de atendimento, converter alguma etiqueta, ou qualquer outra tarefa que você precise.