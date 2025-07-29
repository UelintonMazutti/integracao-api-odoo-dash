import streamlit as st
import pandas as pd
import pickle
import os
from streamlit_autorefresh import st_autorefresh

st.set_page_config(page_title="Dashboard Helpdesk ERP SAG", layout="wide")

st_autorefresh(interval=10 * 1000, key="refresh_dashboard", limit=None)

st.markdown("""
    <style>
        .block-container {padding-top: 0.7rem !important;}
        h1 {font-size: 2.3rem !important;}
    </style>
""", unsafe_allow_html=True)

def carregar_cache_local():
    if not os.path.exists("dados_cache.pkl"):
        st.error("⚠️ Cache ainda não foi gerado. Aguarde ou rode o atualizador.")
        st.stop()
    with open("dados_cache.pkl", "rb") as f:
        dados = pickle.load(f)
    df_abertos = pd.DataFrame(dados['tickets_abertos'])
    df_fechados = pd.DataFrame(dados['tickets_fechados_mes'])
    imagens = dados.get('imagens', {})
    return df_abertos, df_fechados, imagens

def tratar_dados(df):
    df['agente'] = df['user_id'].apply(lambda x: x[1] if isinstance(x, list) and len(x) > 1 else 'Sem Atribuição')
    df['user_id_num'] = df['user_id'].apply(lambda x: int(x[0]) if isinstance(x, list) and len(x) > 0 and isinstance(x[0], (int, float)) else None)
    df['estagio'] = df['stage_id'].apply(lambda x: x[1] if isinstance(x, list) and len(x) > 1 else 'Desconhecido')
    df['equipe'] = df['team_id'].apply(lambda x: x[1] if isinstance(x, list) and len(x) > 1 else 'Desconhecida')
    df['prioridade'] = df['x_studio_prioridade'].astype(str)
    return df[['id', 'ticket_ref', 'estagio', 'agente', 'equipe', 'prioridade', 'user_id', 'user_id_num']]

def extrair_primeiro_e_segundo_nome(nome):
    partes = nome.split()
    return " ".join(partes[:2]) if len(partes) >= 2 else nome

def mostrar_fotos_agentes(df, df_fechados_mes, imagens_cache):
    df['agente'] = df['agente'].apply(extrair_primeiro_e_segundo_nome)
    df_grouped = df.groupby(['agente', 'user_id_num'])
    grupos_ordenados = sorted(df_grouped, key=lambda x: len(x[1]), reverse=True)

    n_colunas = 5
    card_style = """
        background-color: rgba(0,0,0,0.04);
        border-radius: 16px;
        padding: 12px 6px 8px 6px;
        box-shadow: 0 1px 6px 0 rgba(0,0,0,0.06);
        border: 1.2px solid #bbb;
        text-align: center;
        min-height: 172px;
        margin-bottom: 8px;
        display: flex;
        flex-direction: column;
        align-items: center;
    """
    img_style = """
        width: 85px;
        height: 85px;
        object-fit: cover;
        border-radius: 50%;
        border: 2px solid #aaa;
        background: #f3f3f3;
        margin-bottom: 6px;
    """

    prioridade_emojis = {'Urgente': '🚨', 'Alta': '🔴', 'Média': '🟡', 'Baixa': '🔵'}
    ordem = ['Urgente', 'Alta', 'Média', 'Baixa']

    df_sem = df[df['user_id_num'].isnull()]
    total_fechados_sem = len(df_fechados_mes[df_fechados_mes['user_id_num'].isnull()])
    if not df_sem.empty:
        cols = st.columns(n_colunas, gap="small")
        col = cols[0]
        with col:
            img_html = f'<img src="https://cdn-icons-png.flaticon.com/512/1828/1828843.png" style="{img_style}">'
            prioridades = df_sem['prioridade'].value_counts().to_dict()
            prioridade_html = ' '.join(f"{prioridade_emojis[p]} {prioridades[p]}" for p in ordem if p in prioridades)
            st.markdown(f"""
                <div style="{card_style}">
                    {img_html}
                    <div style="font-weight:600;font-size:1.01em;margin-bottom:1px;">Sem Atribuição</div>
                    <div style="font-size:0.93em;margin-bottom:3px;">🎟️ <b>{len(df_sem)}</b> abertos / ✅ <b>{total_fechados_sem}</b> fechados</div>
                    <hr style="border:0;border-top:1.1px dashed #bbb;margin:7px 0 7px 0;width:90%;">
                    <div style="font-size:0.99em;">{prioridade_html}</div>
                </div>
            """, unsafe_allow_html=True)

    for i, ((agente, id_user), df_agente) in enumerate(grupos_ordenados):
        if id_user is None:
            continue
        total_abertos = len(df_agente)
        total_fechados = len(df_fechados_mes[df_fechados_mes['user_id_num'] == id_user])

        idx_offset = 1 if not df_sem.empty else 0
        col_idx = (i + idx_offset) % n_colunas
        if col_idx == 0:
            cols = st.columns(n_colunas, gap="small")
        col = cols[col_idx]

        with col:
            img_base64 = imagens_cache.get(id_user)
            img_html = f'<img src="data:image/png;base64,{img_base64}" style="{img_style}">' if img_base64 else f'<img src="https://via.placeholder.com/85?text=Foto" style="{img_style}">'
            prioridades = df_agente['prioridade'].value_counts().to_dict()
            prioridade_html = ' '.join(f"{prioridade_emojis[p]} {prioridades[p]}" for p in ordem if p in prioridades)
            st.markdown(f"""
                <div style="{card_style}">
                    {img_html}
                    <div style="font-weight:600;font-size:1.01em;margin-bottom:1px;">{agente}</div>
                    <div style="font-size:0.93em;margin-bottom:3px;">🎟️ <b>{total_abertos}</b> abertos / ✅ <b>{total_fechados}</b> fechados</div>
                    <hr style="border:0;border-top:1.1px dashed #bbb;margin:7px 0 7px 0;width:90%;">
                    <div style="font-size:0.99em;">{prioridade_html}</div>
                </div>
            """, unsafe_allow_html=True)

def exibir_dashboard(df, df_fechados_mes, imagens):
    total_abertos = len(df)
    total_fechados = len(df_fechados_mes)
    st.title(f"📺 Dashboard - Equipe Suporte | 🎟️ Abertos: {total_abertos} | ✅ Fechados no mês: {total_fechados}")
    st.markdown("Todos os tickets do ***Suporte***, exceto os ***Cancelados***, ***Encerrados***, ***Notificados*** ou ***Faturados***.")
    mostrar_fotos_agentes(df, df_fechados_mes, imagens)

    # with st.expander("📊 Visualizar dados em tabela"):
    #     df_tabela = df.copy()
    #     df_tabela = df_tabela[['ticket_ref', 'agente', 'estagio', 'prioridade', 'equipe']]
    #     df_tabela = df_tabela.rename(columns={
    #         'ticket_ref': 'Código',
    #         'agente': 'Agente',
    #         'estagio': 'Estágio',
    #         'prioridade': 'Prioridade',
    #         'equipe': 'Equipe'
    #     })
    #     st.dataframe(df_tabela.sort_values(by='Agente'), use_container_width=True)

# Execução principal
try:
    df_raw, df_fechados_mes, imagens = carregar_cache_local()
    df_tratado = tratar_dados(df_raw)
    df_fechados_mes['user_id_num'] = df_fechados_mes['user_id'].apply(lambda x: int(x[0]) if isinstance(x, list) else None)
    exibir_dashboard(df_tratado, df_fechados_mes, imagens)
except Exception as e:
    st.error(f"Erro ao carregar dados: {e}")
