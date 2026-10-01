import streamlit as st
import pandas as pd
import json
import io
import requests
import plotly.express as px
from datetime import datetime, timedelta, timezone
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

st.set_page_config(page_title="Dashboard Cadre 3D", page_icon="📦", layout="wide")

st.title("📦 Dashboard de Vendas - Cadre 3D")
st.markdown("Acompanhe os seus resultados, pedidos e repasses financeiros exatos da Shopee.")

@st.cache_data(ttl=120)
def carregar_dados_do_drive():
    df_pedidos = pd.DataFrame()
    df_financeiro = pd.DataFrame()
    try:
        cert_info = json.loads(st.secrets["google_credentials"])
        credenciais = service_account.Credentials.from_service_account_info(
            cert_info, scopes=['https://www.googleapis.com/auth/drive.readonly']
        )
        servico = build('drive', 'v3', credentials=credenciais)
        
        pasta_principal_id = '1p0H9A9-0r8QCX34koCd3mrsyXmTtTzUQ'
        
        query_sub = f"'{pasta_principal_id}' in parents and mimeType = 'application/vnd.google-apps.folder' and trashed=false"
        res_sub = servico.files().list(q=query_sub, fields="files(id, name)").execute()
        subpastas = res_sub.get('files', [])
        
        pasta_pedidos_id = None
        pasta_financeiro_id = None
        
        for sp in subpastas:
            nome_sp = sp['name'].strip().lower()
            if 'pedido' in nome_sp:
                pasta_pedidos_id = sp['id']
            elif 'financeiro' in nome_sp or 'finan' in nome_sp:
                pasta_financeiro_id = sp['id']
                
        def ler_pedidos(pasta_id):
            if not pasta_id:
                return []
            q_arq = f"'{pasta_id}' in parents and trashed=false"
            arquivos = servico.files().list(q=q_arq, fields="files(id, name, mimeType)").execute().get('files', [])
            
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
            return dfs

        def ler_financeiro(pasta_id):
            if not pasta_id:
                return []
            q_arq = f"'{pasta_id}' in parents and trashed=false"
            arquivos = servico.files().list(q=q_arq, fields="files(id, name, mimeType)").execute().get('files', [])
            
            dfs = []
            for arq in arquivos:
                nome_arq = arq['name'].strip().lower()
                if nome_arq.startswith('income'):
                    request = servico.files().get_media(fileId=arq['id'])
                    arquivo_baixado = io.BytesIO()
                    downloader = MediaIoBaseDownload(arquivo_baixado, request)
                    done = False
                    while done is False:
                        status, done = downloader.next_chunk()
                    arquivo_baixado.seek(0)
                    
                    try:
                        xls = pd.ExcelFile(arquivo_baixado)
                        sheet_names = xls.sheet_names
                        aba_renda = next((s for s in sheet_names if 'renda' in s.lower()), sheet_names[0])
                        df_bruto = pd.read_excel(xls, sheet_name=aba_renda, header=None)
                        
                        if df_bruto.shape[1] > 1:
                            col_b_str = df_bruto.iloc[:, 1].astype(str).str.strip().str.upper()
                            df_filtrado_linhas = df_bruto[col_b_str == 'SKU'].copy()
                            
                            if not df_filtrado_linhas.empty:
                                df_processado = pd.DataFrame()
                                if df_filtrado_linhas.shape[1] > 2:
                                    df_processado['ID do pedido'] = df_filtrado_linhas.iloc[:, 2].astype(str).str.strip()
                                if df_filtrado_linhas.shape[1] > 11:
                                    df_processado['Quantia total lançada'] = df_filtrado_linhas.iloc[:, 11]
                                if not df_processado.empty:
                                    dfs.append(df_processado)
                    except Exception as e:
                        print(f"Erro financeiro: {e}")
            return dfs

        dfs_pedidos = ler_pedidos(pasta_pedidos_id)
        dfs_financeiro = ler_financeiro(pasta_financeiro_id)
        
        df_pedidos = pd.concat(dfs_pedidos, ignore_index=True) if dfs_pedidos else pd.DataFrame()
        df_financeiro = pd.concat(dfs_financeiro, ignore_index=True) if dfs_financeiro else pd.DataFrame()
        
        if df_pedidos.empty:
            return pd.DataFrame()
            
        df_pedidos.columns = df_pedidos.columns.str.strip()
        df_limpo = df_pedidos.copy()
        
        if not df_financeiro.empty:
            df_financeiro.columns = df_financeiro.columns.str.strip()
            col_id_ped = next((c for c in df_limpo.columns if 'id' in c.lower() and 'pedido' in c.lower()), df_limpo.columns[0])
            col_id_fin = 'ID do pedido' if 'ID do pedido' in df_financeiro.columns else next((c for c in df_financeiro.columns if 'id' in c.lower() and 'pedido' in c.lower()), None)
            col_quantia_fin = 'Quantia total lançada' if 'Quantia total lançada' in df_financeiro.columns else next((c for c in df_financeiro.columns if 'quantia' in c.lower() or 'total' in c.lower()), None)
            
            if col_id_fin and col_quantia_fin:
                def limpar_val_fin(serie):
                    if serie.dtype == object:
                        s_str = serie.astype(str).str.replace('R$', '', regex=False).str.strip()
                        s_str = s_str.str.replace(',', '.', regex=False)
                        return pd.to_numeric(s_str, errors='coerce').fillna(0)
                    else:
                        return pd.to_numeric(serie, errors='coerce').fillna(0)

                fin_dict = dict(zip(
                    df_financeiro[col_id_fin].astype(str).str.strip(), 
                    limpar_val_fin(df_financeiro[col_quantia_fin])
                ))
                df_limpo['Valor_Financeiro_Real'] = df_limpo[col_id_ped].astype(str).str.strip().map(fin_dict)
            else:
                df_limpo['Valor_Financeiro_Real'] = 0.0
        else:
            df_limpo['Valor_Financeiro_Real'] = 0.0
            
        if 'Data de criação do pedido' in df_limpo.columns:
            df_limpo['Data_Criacao'] = pd.to_datetime(df_limpo['Data de criação do pedido'], errors='coerce')
        else:
            df_limpo['Data_Criacao'] = pd.NaT

        if 'Hora do pagamento do pedido' in df_limpo.columns:
            df_limpo['Data_Pagamento'] = pd.to_datetime(df_limpo['Hora do pagamento do pedido'], errors='coerce')
        else:
            df_limpo['Data_Pagamento'] = pd.NaT
            
        def limpar_coluna_valor(serie):
            if serie is None:
                return pd.Series(0.0, index=df_limpo.index)
            if serie.dtype == object:
                s_str = serie.astype(str).str.replace('R$', '', regex=False).str.strip()
                s_str = s_str.str.replace(',', '.', regex=False)
                return pd.to_numeric(s_str, errors='coerce').fillna(0)
            else:
                return pd.to_numeric(serie, errors='coerce').fillna(0)

        total_global = limpar_coluna_valor(df_limpo['Total global']) if 'Total global' in df_limpo.columns else (
            limpar_coluna_valor(df_limpo['Preço acordado']) if 'Preço acordado' in df_limpo.columns else 0.0
        )

        est_frete = limpar_coluna_valor(df_limpo['Valor estimado do frete']) if 'Valor estimado do frete' in df_limpo.columns else 0.0
        desc_frete = limpar_coluna_valor(df_limpo['Desconto de Frete Aproximado']) if 'Desconto de Frete Aproximado' in df_limpo.columns else 0.0
        ajuste_comercial = limpar_coluna_valor(df_limpo['Ajuste por participação em ação comercial']) if 'Ajuste por participação em ação comercial' in df_limpo.columns else 0.0

        df_limpo['Valor_Sujo'] = total_global + ajuste_comercial
        frete_liquido = est_frete - desc_frete
        valor_produto_estimado = total_global - frete_liquido + ajuste_comercial
        
        val_real_limpo = limpar_coluna_valor(df_limpo['Valor_Financeiro_Real'])
        df_limpo['Valor_Liberado'] = val_real_limpo
        df_limpo['Valor_Produto'] = [
            real if real > 0 else est 
            for real, est in zip(val_real_limpo, valor_produto_estimado)
        ]
            
        return df_limpo
            
    except Exception as e:
        st.error(f"Erro de ligação com o Drive: {e}")
        return None

@st.cache_data(ttl=3600)
def carregar_geojson_brasil():
    url = "https://raw.githubusercontent.com/codeforamerica/click_that_hood/master/public/data/brazil-states.geojson"
    try:
        response = requests.get(url)
        if response.status_code == 200:
            return response.json()
    except:
        pass
    return None

col_vazia, col_btn = st.columns([4, 1])
with col_btn:
    if st.button("🔄 Forçar Atualização", use_container_width=True):
        carregar_dados_do_drive.clear()

df = carregar_dados_do_drive()

if df is not None and not df.empty:
    
    st.sidebar.header("🎛️ Navegação")
    pagina_selecionada = st.sidebar.radio("Ir para:", ["Financeiro", "Pedidos", "Estatísticas"])
    
    st.sidebar.divider()
    st.sidebar.header("📅 Filtros do Período")
    coluna_ativa_data = 'Data_Criacao'
    
    opcao_tempo = st.sidebar.selectbox(
        "Período:", 
        ["Hoje", "Ontem", "Últimos 7 dias", "Este mês", "Mês anterior", "Todo o período", "Personalizado"]
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
        elif opcao_tempo == "Mês anterior":
            inicio_mes_atual = hoje.replace(day=1)
            fim_mes_anterior = inicio_mes_atual - pd.Timedelta(days=1)
            inicio_mes_anterior = fim_mes_anterior.replace(day=1)
            df_periodo = df_filtrado[(df_filtrado[coluna_ativa_data] >= inicio_mes_anterior) & (df_filtrado[coluna_ativa_data] < inicio_mes_atual)]
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

    def fmt_val(val):
        return f"R$ {val:,.2f}".replace(',', 'X').replace('.', ',').replace('X', '.')

    tot_produto_val = df_periodo[validados_mask]['Valor_Produto'].sum() if 'Valor_Produto' in df_periodo.columns else 0.0
    tot_liberado_val = df_periodo[validados_mask]['Valor_Liberado'].sum() if 'Valor_Liberado' in df_periodo.columns else 0.0
    tot_sujo_val = df_periodo[validados_mask]['Valor_Sujo'].sum() if 'Valor_Sujo' in df_periodo.columns else 0.0

    # ==================== PÁGINA: FINANCEIRO ====================
    if pagina_selecionada == "Financeiro":
        st.header(f"💰 Seção Financeira ({opcao_tempo})")
        st.markdown("Acompanhe o valor líquido de seus produtos, repasses já liberados e o faturamento bruto.")
        
        col_fat1, col_fat2, col_fat3 = st.columns(3)
        with col_fat1:
            st.metric("🎯 Montante de Produtos (Sua Renda Total)", fmt_val(tot_produto_val))
        with col_fat2:
            st.metric("💰 Valor Liberado (Já Pago / Saldo)", fmt_val(tot_liberado_val))
        with col_fat3:
            st.metric("📦 Montante Bruto / Sujo (Com Frete)", fmt_val(tot_sujo_val))
            
        st.divider()
        st.subheader("🔍 Consultar Pedido por ID (Financeiro)")
        pedido_id_fin = st.text_input("Digite o ID do Pedido para ver os detalhes financeiros:").strip()
        
        if pedido_id_fin:
            if col_id in df.columns:
                resultado = df[df[col_id].astype(str).str.contains(pedido_id_fin, case=False, na=False)]
                if not resultado.empty:
                    st.success("✅ Pedido encontrado:")
                    cols_fin = [c for c in [col_id, 'Nome do Produto', 'Total global', 'Ajuste por participação em ação comercial', 'Valor_Produto', 'Valor_Liberado', 'Valor_Sujo'] if c and c in resultado.columns]
                    res_fmt = resultado[cols_fin].copy()
                    for col_m in ['Valor_Produto', 'Valor_Liberado', 'Valor_Sujo']:
                        if col_m in res_fmt.columns:
                            res_fmt[col_m] = res_fmt[col_m].apply(fmt_val)
                    st.dataframe(res_fmt, use_container_width=True)
                else:
                    st.error("❌ Pedido não encontrado.")

    # ==================== PÁGINA: PEDIDOS ====================
    elif pagina_selecionada == "Pedidos":
        st.header(f"📦 Gestão de Pedidos ({opcao_tempo})")
        
        col1, col2, col3, col4, col5, col6 = st.columns(6)
        col1.metric("📦 Válidos", total_validos)
        col2.metric("⏳ Não pago", nao_pago_cnt)
        col3.metric("📤 A Enviar", a_enviar_cnt)
        col4.metric("🚚 Enviado", enviado_cnt)
        col5.metric("✅ Concluído", concluido_cnt)
        col6.metric("❌ Cancelados", cancelados_cnt)
        
        st.divider()
        
        def calc_aba(mask):
            p = df_periodo[mask]['Valor_Produto'].sum() if 'Valor_Produto' in df_periodo.columns else 0.0
            l = df_periodo[mask]['Valor_Liberado'].sum() if 'Valor_Liberado' in df_periodo.columns else 0.0
            s = df_periodo[mask]['Valor_Sujo'].sum() if 'Valor_Sujo' in df_periodo.columns else 0.0
            return p, l, s

        p_val, l_val, s_val = calc_aba(validados_mask)
        p_naopag, l_naopag, s_naopag = calc_aba(nao_pago_mask)
        p_aenv, l_aenv, s_aenv = calc_aba(a_enviar_mask)
        p_env, l_env, s_env = calc_aba(enviado_mask)
        p_conc, l_conc, s_conc = calc_aba(concluido_mask)
        p_canc, l_canc, s_canc = calc_aba(cancelados_mask)

        tab_val, tab_naopag, tab_aenv, tab_env, tab_conc, tab_canc = st.tabs([
            f"📦 Válidos ({total_validos})",
            f"⏳ Não pago ({nao_pago_cnt})",
            f"📤 A Enviar ({a_enviar_cnt})",
            f"🚚 Enviado ({enviado_cnt})",
            f"✅ Concluído ({concluido_cnt})",
            f"❌ Cancelados ({cancelados_cnt})"
        ])
        
        def exibir_tabela_e_montantes(mask_filtro, prod_val, lib_val, sujo_val, mostrar_motivo=False):
            if mask_filtro.sum() > 0:
                df_show = df_periodo[mask_filtro].copy()
                cols_exibir = [col_id, 'Data de criação do pedido']
                if 'Total global' in df_show.columns:
                    cols_exibir.append('Total global')
                if 'Valor_Produto' in df_show.columns:
                    cols_exibir.append('Valor_Produto')
                if 'Valor_Liberado' in df_show.columns:
                    cols_exibir.append('Valor_Liberado')
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
                    df_show_fmt['Montante Produto'] = df_show_fmt['Valor_Produto'].apply(fmt_val)
                    df_show_fmt = df_show_fmt.drop(columns=['Valor_Produto'])
                if 'Valor_Liberado' in df_show_fmt.columns:
                    df_show_fmt['Valor Liberado'] = df_show_fmt['Valor_Liberado'].apply(fmt_val)
                    df_show_fmt = df_show_fmt.drop(columns=['Valor_Liberado'])
                if 'Valor_Sujo' in df_show_fmt.columns:
                    df_show_fmt['Montante Bruto'] = df_show_fmt['Valor_Sujo'].apply(fmt_val)
                    df_show_fmt = df_show_fmt.drop(columns=['Valor_Sujo'])
                    
                st.dataframe(df_show_fmt, use_container_width=True)
                st.markdown(
                    f"**Resumo da Categoria:** &nbsp;&nbsp; 🎯 **Renda Total:** `{fmt_val(prod_val)}` &nbsp;&nbsp;|&nbsp;&nbsp; 💰 **Valor Liberado:** `{fmt_val(lib_val)}` &nbsp;&nbsp;|&nbsp;&nbsp; 📦 **Bruto:** `{fmt_val(sujo_val)}`",
                    unsafe_allow_html=True
                )
            else:
                st.info("Nenhum pedido encontrado nesta categoria para o período selecionado.")

        with tab_val:
            exibir_tabela_e_montantes(validados_mask, p_val, l_val, s_val)
        with tab_naopag:
            exibir_tabela_e_montantes(nao_pago_mask, p_naopag, l_naopag, s_naopag, mostrar_motivo=True)
        with tab_aenv:
            exibir_tabela_e_montantes(a_enviar_mask, p_aenv, l_aenv, s_aenv)
        with tab_env:
            exibir_tabela_e_montantes(enviado_mask, p_env, l_env, s_env)
        with tab_conc:
            exibir_tabela_e_montantes(concluido_mask, p_conc, l_conc, s_conc)
        with tab_canc:
            exibir_tabela_e_montantes(cancelados_mask, p_canc, l_canc, s_canc, mostrar_motivo=True)

    # ==================== PÁGINA: ESTATÍSTICAS ====================
    elif pagina_selecionada == "Estatísticas":
        st.header(f"📊 Estatísticas Gerais e Mapa Geográfico do Brasil ({opcao_tempo})")
        
        col_est1, col_est2, col_est3 = st.columns(3)
        with col_est1:
            st.metric("📦 Total de Pedidos Válidos", total_validos)
        with col_est2:
            st.metric("❌ Total de Cancelados", cancelados_cnt)
        with col_est3:
            st.metric("🎯 Ticket Médio (Renda por Pedido)", fmt_val(tot_produto_val / total_validos if total_validos > 0 else 0.0))
            
        st.divider()
        st.subheader("🗺️ Mapa Geográfico do Brasil por Estado (UF)")
        
        col_estado = next((c for c in df_periodo.columns if c.strip().upper() == 'UF'), None)
        
        if col_estado:
            df_validados_periodo = df_periodo[validados_mask].copy()
            df_validados_periodo['UF_Normalizada'] = df_validados_periodo[col_estado].astype(str).str.strip().str.upper()
            
            df_mapa = df_validados_periodo.groupby('UF_Normalizada').agg(
                Quantidade=('ID do pedido' if 'ID do pedido' in df_validados_periodo.columns else df_validados_periodo.columns[0], 'nunique'),
                Renda_Total=('Valor_Produto', 'sum')
            ).reset_index()
            
            geojson_brasil = carregar_geojson_brasil()
            
            if geojson_brasil:
                fig = px.choropleth(
                    df_mapa,
                    geojson=geojson_brasil,
                    locations='UF_Normalizada',
                    featureidkey='properties.sigla',
                    color='Quantidade',
                    color_continuous_scale="Blues",
                    hover_name='UF_Normalizada',
                    labels={'Quantidade': 'Volume de Pedidos'}
                )
                fig.update_geos(
                    scope="south america",
                    center={"lat": -14.2350, "lon": -51.9253},
                    projection_scale=3.5,
                    visible=True,
                    showcountries=True, countrycolor="RebeccaPurple",
                    showcoastlines=True, coastlinecolor="RebeccaPurple",
                    showland=True, landcolor="rgb(245, 245, 245)"
                )
                fig.update_layout(margin={"r":0, "t":0, "l":0, "b":0}, height=550)
                
                evento_clique = st.plotly_chart(fig, use_container_width=True, on_select="rerun")
                
                estado_selecionado = None
                try:
                    if evento_clique and "selection" in evento_clique:
                        pontos = evento_clique["selection"].get("points", [])
                        if pontos:
                            estado_selecionado = pontos[0].get("location")
                except:
                    pass
            else:
                st.warning("⚠️ Não foi possível carregar a malha do mapa. Exibindo em formato de barras.")
                fig = px.bar(df_mapa, x='Quantidade', y='UF_Normalizada', orientation='h')
                evento_clique = st.plotly_chart(fig, use_container_width=True, on_select="rerun")
                estado_selecionado = None

            if estado_selecionado:
                st.divider()
                st.subheader(f"📍 Detalhamento para o Estado: {estado_selecionado}")
                
                df_estado = df_validados_periodo[df_validados_periodo['UF_Normalizada'] == estado_selecionado]
                qtd_est = df_estado[col_id].nunique()
                renda_est = df_estado['Valor_Produto'].sum()
                lib_est = df_estado['Valor_Liberado'].sum()
                
                c_est1, c_est2, c_est3 = st.columns(3)
                c_est1.metric("📦 Pedidos no Estado", qtd_est)
                c_est2.metric("🎯 Renda Total", fmt_val(renda_est))
                c_est3.metric("💰 Valor Liberado", fmt_val(lib_est))
                
                st.markdown("##### 🏆 Top Produtos neste Estado")
                col_prod = next((c for c in df_estado.columns if 'nome' in c.lower() and 'produto' in c.lower()), None)
                if col_prod:
                    top_prod = df_estado[col_prod].value_counts().reset_index()
                    top_prod.columns = ['Produto', 'Quantidade Vendida']
                    st.dataframe(top_prod.head(5), use_container_width=True)
                else:
                    st.info("Coluna de nome de produto não identificada para o ranking.")
                    
                st.markdown("##### 📋 Lista de Pedidos do Estado")
                cols_est_show = [col_id, 'Data de criação do pedido', 'Valor_Produto', 'Valor_Liberado']
                if col_prod:
                    cols_est_show.append(col_prod)
                df_est_fmt = df_estado[[c for c in cols_est_show if c in df_estado.columns]].copy()
                if 'Valor_Produto' in df_est_fmt.columns:
                    df_est_fmt['Montante Produto'] = df_est_fmt['Valor_Produto'].apply(fmt_val)
                    df_est_fmt = df_est_fmt.drop(columns=['Valor_Produto'])
                if 'Valor_Liberado' in df_est_fmt.columns:
                    df_est_fmt['Valor Liberado'] = df_est_fmt['Valor_Liberado'].apply(fmt_val)
                    df_est_fmt = df_est_fmt.drop(columns=['Valor_Liberado'])
                st.dataframe(df_est_fmt, use_container_width=True)
            else:
                st.info("💡 **Dica:** Clique em cima de qualquer estado no mapa do Brasil acima para visualizar os pedidos, valores e produtos mais vendidos daquela região.")
        else:
            st.warning("⚠️ Não foi encontrada uma coluna com o título 'UF' nas planilhas de pedidos da Shopee.")

else:
    st.info("A pasta principal ou as subpastas 'pedidos' e 'financeiro' estão vazias ou a aguardar ficheiros no Google Drive!")
