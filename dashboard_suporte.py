import streamlit as st

# 🔧 DEVE SER A PRIMEIRA CHAMADA DE ST, ANTES DE TUDO
st.set_page_config(page_title="Dashboard Helpdesk ERP SAG", layout="wide")

# Agora sim, pode importar o restante
import pandas as pd
import xmlrpc.client
import time

from streamlit_autorefresh import st_autorefresh

# Atualização automática a cada 60 segundos (para tickets)
st_autorefresh(interval=60 * 1000, key="refresh_dashboard", limit=None)

st.markdown("""
    <style>
        .block-container {padding-top: 0.7rem !important;}
        h1 {font-size: 2.3rem !important;}
    </style>
""", unsafe_allow_html=True)
st.title("📺 Dashboard - Equipe Suporte")

# Cache apenas para imagens (1 hora)
@st.cache_data(ttl=3600)
def carregar_fotos(_models, _db, _uid, _password, user_ids):
    imagens = {}
    for user_id in user_ids:
        try:
            dados_user = _models.execute_kw(
                _db, _uid, _password, 'res.users', 'read',
                [[int(user_id)]], {'fields': ['image_1920']}
            )
            imagens[user_id] = dados_user[0].get('image_1920')
        except:
            imagens[user_id] = None
    return imagens

def carregar_dados():
    url = "https://suporte.sag.com.br"
    db = "helpdesk-erp"
    username = "uelinton.silva@sag.com.br"
    password = "Dia@28_04#"

    common = xmlrpc.client.ServerProxy(f'{url}/xmlrpc/2/common')
    uid = common.authenticate(db, username, password, {})
    models = xmlrpc.client.ServerProxy(f'{url}/xmlrpc/2/object')

    estagios_excluidos = ['Cancelado/Recusado', 'Encerrado', 'Faturado', 'Notificado']

    id_estagios_validos = models.execute_kw(
        db, uid, password, 'helpdesk.stage', 'search',
        [[['name', 'not in', estagios_excluidos]]]
    )

    id_equipe = models.execute_kw(
        db, uid, password, 'helpdesk.team', 'search',
        [[['name', '=', 'Suporte']]]
    )[0]

    tickets_fields = ['ticket_ref', 'stage_id', 'user_id', 'team_id', 'x_studio_prioridade']

    id_tickets = models.execute_kw(
        db, uid, password, 'helpdesk.ticket', 'search',
        [[
            ['stage_id', 'in', id_estagios_validos],
            ['team_id', '=', id_equipe]
        ]],
        {'limit': 1000, 'order': 'create_date desc'}
    )

    tickets_dados = models.execute_kw(
        db, uid, password, 'helpdesk.ticket', 'read',
        [id_tickets], {'fields': tickets_fields}
    )

    return pd.DataFrame(tickets_dados), models, db, uid, password


def tratar_dados(df):
    df['agente'] = df['user_id'].apply(lambda x: x[1] if isinstance(x, list) and len(x) > 1 else 'Sem Atribuição')
    df['user_id_num'] = df['user_id'].apply(
        lambda x: int(x[0]) if isinstance(x, list) and len(x) > 0 and isinstance(x[0], (int, float)) else None
    )
    df['estagio'] = df['stage_id'].apply(lambda x: x[1] if isinstance(x, list) and len(x) > 1 else 'Desconhecido')
    df['equipe'] = df['team_id'].apply(lambda x: x[1] if isinstance(x, list) and len(x) > 1 else 'Desconhecida')
    df['prioridade'] = df['x_studio_prioridade'].astype(str)
    return df[['id', 'ticket_ref', 'estagio', 'agente', 'equipe', 'prioridade', 'user_id', 'user_id_num']]


def extrair_primeiro_e_segundo_nome(nome):
    partes = nome.split()
    return " ".join(partes[:2]) if len(partes) >= 2 else nome


def gerar_prioridade_emojis(df_agente):
    prioridades = df_agente['prioridade'].value_counts().to_dict()
    ordem = ['Urgente', 'Alta', 'Média', 'Baixa']
    emojis = {
        'Urgente': '🚨',
        'Alta': '🔴',
        'Média': '🟡',
        'Baixa': '🔵'
    }
    linha = ''
    for p in ordem:
        if p in prioridades:
            linha += f"{emojis[p]} {prioridades[p]} "
    return f"<div style='margin-top:6px'>{linha.strip()}</div>"


def mostrar_fotos_agentes(df, models, db, uid, password):
    df['agente'] = df['agente'].apply(extrair_primeiro_e_segundo_nome)
    df_grouped = df.groupby(['agente', 'user_id_num'])
    grupos_ordenados = sorted(df_grouped, key=lambda x: len(x[1]), reverse=True)
    user_ids = [id_user for (_, id_user), _ in grupos_ordenados if id_user is not None]
    imagens_cache = carregar_fotos(models, db, uid, password, user_ids)

    n_colunas = 5
    card_style = """
        background-color: rgba(0,0,0,0.04);
        border-radius: 16px;
        padding: 12px 6px 8px 6px;   /* Menos padding */
        box-shadow: 0 1px 6px 0 rgba(0,0,0,0.06);
        border: 1.2px solid #bbb;
        text-align: center;
        min-height: 172px;
        margin-bottom: 8px;          /* Menos espaço vertical */
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

    prioridade_emojis = {
        'Urgente': '🚨',
        'Alta': '🔴',
        'Média': '🟡',
        'Baixa': '🔵'
    }

    for i, ((agente, id_user), df_agente) in enumerate(grupos_ordenados):
        total_tickets = len(df_agente)
        col_idx = i % n_colunas
        if col_idx == 0:
            cols = st.columns(n_colunas, gap="small")  # gap pequeno
        col = cols[col_idx]

        with col:
            # Imagem do agente
            if id_user is None:
                img_html = f'<img src="https://cdn-icons-png.flaticon.com/512/1828/1828843.png" style="{img_style}">'
            else:
                img_base64 = imagens_cache.get(id_user)
                if img_base64:
                    img_html = f'<img src="data:image/png;base64,{img_base64}" style="{img_style}">'
                else:
                    img_html = f'<img src="https://via.placeholder.com/85?text=Foto" style="{img_style}">'
            prioridades = df_agente['prioridade'].value_counts().to_dict()
            ordem = ['Urgente', 'Alta', 'Média', 'Baixa']
            prioridade_html = ' '.join(f"{prioridade_emojis[p]} {prioridades[p]}" for p in ordem if p in prioridades)

            st.markdown(
                f"""
                <div style="{card_style}">
                    {img_html}
                    <div style="font-weight:600;font-size:1.01em;margin-bottom:1px;">{agente}</div>
                    <div style="font-size:0.93em;margin-bottom:3px;">🎟️ <b>{total_tickets}</b> tickets</div>
                    <hr style="border:0;border-top:1.1px dashed #bbb;margin:7px 0 7px 0;width:90%;">
                    <div style="font-size:0.99em;">{prioridade_html}</div>
                </div>
                """,
                unsafe_allow_html=True
            )


def exibir_dashboard(df, models, db, uid, password):
    # st.title("📺 Dashboard ERP Helpdesk - Equipe Suporte")
    # st.caption(f"Atualizado em: {time.strftime('%d/%m/%Y %H:%M:%S')}")
    mostrar_fotos_agentes(df, models, db, uid, password)


# Execução principal
try:
    df_raw, models, db, uid, password = carregar_dados()
    df_tratado = tratar_dados(df_raw)
    exibir_dashboard(df_tratado, models, db, uid, password)
except Exception as e:
    st.error(f"Erro ao carregar dados: {e}")