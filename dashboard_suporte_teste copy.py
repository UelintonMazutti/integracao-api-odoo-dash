import streamlit as st

st.set_page_config(page_title="Dashboard Helpdesk ERP SAG", layout="wide")

import pandas as pd
import xmlrpc.client
import time
import os
import base64
from datetime import datetime, date, time as dtime, timedelta
import platform
from streamlit_autorefresh import st_autorefresh

# 🔁 Mantém refresh ativo sempre (1 minuto)
st_autorefresh(interval=60 * 1000, key="refresh_dashboard", limit=None)

# 🕒 Função de controle de horário
def dentro_do_horario():
    agora = datetime.now()
    dia_semana = agora.weekday()  # 0 = segunda, 6 = domingo
    hora = agora.time()
    return dia_semana < 5 and (
        dtime(8, 0) <= hora <= dtime(12, 0)
        or dtime(13, 20) <= hora <= dtime(18, 0)
    )

# ---------- Utilidades de sessão ----------
def _hoje_str():
    return date.today().strftime("%Y-%m-%d")

def _reset_flags_se_novo_dia():
    if "run_date" not in st.session_state or st.session_state.run_date != _hoje_str():
        st.session_state.run_date = _hoje_str()
        st.session_state.primeira_execucao_hoje = True
        st.session_state.cache_abertos_df = None
        st.session_state.cache_fechados_mes_df = None

_reset_flags_se_novo_dia()
if "primeira_execucao_hoje" not in st.session_state:
    st.session_state.primeira_execucao_hoje = True
if "dados_cache" not in st.session_state:
    st.session_state.dados_cache = None
if "fechados_cache" not in st.session_state:
    st.session_state.fechados_cache = None

# 🧠 Lógica principal
if dentro_do_horario():
    st.markdown("""
        <style>
            .block-container {padding-top: 0.7rem !important;}
            h1 {font-size: 2.3rem !important;}
            .element-container { transition: opacity 0.3s ease; }
        </style>
    """, unsafe_allow_html=True)

    # ----------------------------
    # 🔌 Conexão e parâmetros Odoo
    # ----------------------------
    def _odoo_clients():
        url = "https://suporte.sag.com.br"
        db = "helpdesk-erp"
        username = "uelinton.silva@sag.com.br"
        password = "Dia@28_04#"

        common = xmlrpc.client.ServerProxy(f'{url}/xmlrpc/2/common')
        uid = common.authenticate(db, username, password, {})
        models = xmlrpc.client.ServerProxy(f'{url}/xmlrpc/2/object')
        return models, db, uid, password

    def _estagios_validos(models, db, uid, password):
        estagios_excluidos = ['Cancelado/Recusado', 'Encerrado', 'Faturado', 'Notificado']
        return models.execute_kw(
            db, uid, password, 'helpdesk.stage', 'search',
            [[['name', 'not in', estagios_excluidos]]]
        )

    def _estagios_fechados(models, db, uid, password):
        estagios_fechados = ['Encerrado', 'Notificado', 'Faturado']
        return models.execute_kw(
            db, uid, password, 'helpdesk.stage', 'search',
            [[['name', 'in', estagios_fechados]]]
        )

    # ----------------------------
    # 🔧 Util: upsert seguro
    # ----------------------------
    def _ensure_cols(df, cols):
        for c in cols:
            if c not in df.columns:
                df[c] = pd.NA
        return df

    def _upsert_row(cache, key, row: pd.Series):
        # Garante todas as colunas do row no cache
        cache = _ensure_cols(cache, list(row.index))
        # Garante todas as colunas do cache no row (para alinhamento)
        row = row.reindex(cache.columns)
        # Se a linha não existir, cria vazia
        if key not in cache.index:
            cache.loc[key] = [pd.NA] * len(cache.columns)
        # Atribui por colunas (evita mismatch len keys/value)
        for col, val in row.items():
            cache.at[key, col] = val
        return cache

    # ----------------------------
    # 🧩 Merge de delta (abertos)
    # ----------------------------
    def _merge_delta_abertos(cache_df, delta_df, id_estagios_validos):
        """
        Aplica o delta:
        - Atualiza/inclui registros do delta.
        - Remove do cache tickets cujo stage atual NÃO está em válidos.
        - Mantém no cache os que não apareceram no delta (pois não mudaram hoje).
        """
        if cache_df is None or cache_df.empty:
            if delta_df is None or delta_df.empty:
                return pd.DataFrame(columns=['id','ticket_ref','stage_id','user_id','team_id','x_studio_prioridade','write_date'])
            base = delta_df.copy()
            # filtra válidos
            def _stage_ok(x):
                try:
                    return (isinstance(x, list) and len(x) > 0 and x[0] in id_estagios_validos)
                except Exception:
                    return False
            base = base[base['stage_id'].apply(_stage_ok)].copy()
            return base

        cache = cache_df.copy()
        if 'id' not in cache.columns:
            cache['id'] = pd.NA
        cache = cache.set_index('id', drop=False)

        # Normaliza delta
        if delta_df is None:
            delta_df = pd.DataFrame(columns=cache.columns)
        for _, row in delta_df.iterrows():
            ticket_id = row.get('id')
            if pd.isna(ticket_id):
                continue
            stage = None
            if isinstance(row.get('stage_id'), list) and row['stage_id']:
                stage = row['stage_id'][0]

            if stage in id_estagios_validos:
                cache = _upsert_row(cache, ticket_id, row)
            else:
                if ticket_id in cache.index:
                    cache = cache.drop(ticket_id)

        return cache.reset_index(drop=True)

    # ----------------------------
    # 🧩 Merge de delta (fechados no mês)
    # ----------------------------
    def _merge_delta_fechados_mes(cache_df, delta_df, id_stages_fechados, primeiro_dia, proximo_dia_1):
        if cache_df is None or cache_df.empty:
            cache = pd.DataFrame(columns=['id', 'user_id', 'user_id_num'])
        else:
            cache = cache_df.copy()

        if 'id' not in cache.columns:
            cache['id'] = pd.NA
        cache = cache.set_index('id', drop=False)

        def _in_month(write_date_str):
            try:
                d = pd.to_datetime(write_date_str)
                ds = d.strftime('%Y-%m-%d')
                return (ds >= primeiro_dia) and (ds < proximo_dia_1)
            except Exception:
                return False

        if delta_df is None:
            delta_df = pd.DataFrame()

        for _, row in delta_df.iterrows():
            ticket_id = row.get('id')
            if pd.isna(ticket_id):
                continue
            write_date = row.get('write_date')
            if not _in_month(write_date):
                # Fora do mês ⇒ só removemos se reabriu e já existe no cache
                stage = None
                if isinstance(row.get('stage_id'), list) and row['stage_id']:
                    stage = row['stage_id'][0]
                if stage not in id_stages_fechados and ticket_id in cache.index:
                    cache = cache.drop(ticket_id)
                continue

            stage = None
            if isinstance(row.get('stage_id'), list) and row['stage_id']:
                stage = row['stage_id'][0]

            if stage in id_stages_fechados:
                # garante colunas
                cache = _ensure_cols(cache, ['user_id', 'user_id_num'])
                user_id_num = int(row['user_id'][0]) if isinstance(row.get('user_id'), list) and row['user_id'] else None
                if ticket_id not in cache.index:
                    cache.loc[ticket_id] = [pd.NA] * len(cache.columns)
                cache.at[ticket_id, 'id'] = ticket_id
                cache.at[ticket_id, 'user_id'] = row.get('user_id')
                cache.at[ticket_id, 'user_id_num'] = user_id_num
            else:
                if ticket_id in cache.index:
                    cache = cache.drop(ticket_id)

        return cache.reset_index(drop=True)

    # ----------------------------------------
    # 🔎 Função 1 — carregar_dados (Abertos)
    # ----------------------------------------
    def carregar_dados():
        # cache leve 25s
        if st.session_state.dados_cache and time.time() - st.session_state.dados_cache['timestamp'] < 25:
            c = st.session_state.dados_cache
            return c['df'], c['models'], c['db'], c['uid'], c['password']

        models, db, uid, password = _odoo_clients()
        id_estagios_validos = _estagios_validos(models, db, uid, password)

        tickets_fields = ['id', 'ticket_ref', 'stage_id', 'user_id', 'team_id', 'x_studio_prioridade', 'write_date']

        if st.session_state.primeira_execucao_hoje:
            # FULL
            id_tickets = models.execute_kw(
                db, uid, password, 'helpdesk.ticket', 'search',
                [[
                    ['stage_id', 'in', id_estagios_validos],
                    ['team_id', '=', 1]
                ]],
                {'limit': 5000, 'order': 'create_date desc'}
            )
            dados = [] if not id_tickets else models.execute_kw(
                db, uid, password, 'helpdesk.ticket', 'read', [id_tickets],
                {'fields': tickets_fields}
            )
            df_full = pd.DataFrame(dados) if dados else pd.DataFrame(columns=tickets_fields)
            st.session_state.cache_abertos_df = df_full.copy()
            st.session_state.primeira_execucao_hoje = False
            df_final = df_full
        else:
            # DELTA do dia
            hoje = _hoje_str()
            id_delta = models.execute_kw(
                db, uid, password, 'helpdesk.ticket', 'search',
                [[
                    ['team_id', '=', 1]
                    ['write_date', '>=', hoje]
                ]],
                {'limit': 5000, 'order': 'write_date desc'}
            )
            delta = [] if not id_delta else models.execute_kw(
                db, uid, password, 'helpdesk.ticket', 'read', [id_delta],
                {'fields': tickets_fields}
            )
            df_delta = pd.DataFrame(delta) if delta else pd.DataFrame(columns=tickets_fields)

            st.session_state.cache_abertos_df = _merge_delta_abertos(
                st.session_state.cache_abertos_df, df_delta, id_estagios_validos
            )
            df_final = st.session_state.cache_abertos_df

        st.session_state.dados_cache = {
            'df': df_final,
            'models': models,
            'db': db,
            'uid': uid,
            'password': password,
            'timestamp': time.time()
        }
        return df_final, models, db, uid, password

    # ------------------------------------------------------
    # 🔎 Função 2 — carregar_tickets_fechados_mes (Fechados)
    # ------------------------------------------------------
    def carregar_tickets_fechados_mes(models, db, uid, password):
        # cache leve 25s
        if st.session_state.fechados_cache and time.time() - st.session_state.fechados_cache['timestamp'] < 25:
            return st.session_state.fechados_cache['df']

        hoje_dt = datetime.now()
        primeiro_dia_dt = hoje_dt.replace(day=1)
        primeiro_dia = primeiro_dia_dt.strftime('%Y-%m-%d')
        proximo_mes = (hoje_dt.replace(day=28) + timedelta(days=4)).replace(day=1)
        proximo_dia_1 = proximo_mes.strftime('%Y-%m-%d')

        id_stages_fechados = _estagios_fechados(models, db, uid, password)
        tickets_fields = ['id', 'user_id', 'stage_id', 'write_date']

        if st.session_state.cache_fechados_mes_df is None:
            # FULL mês
            ticket_ids = models.execute_kw(
                db, uid, password, 'helpdesk.ticket', 'search',
                [[
                    ['stage_id', 'in', id_stages_fechados],
                    ['write_date', '>=', primeiro_dia],
                    ['write_date', '<', proximo_dia_1],
                    ['team_id', '=', 1]
                ]],
                {'limit': 5000}
            )
            if not ticket_ids:
                df_full = pd.DataFrame(columns=['id', 'user_id', 'user_id_num'])
            else:
                tickets_data = models.execute_kw(
                    db, uid, password, 'helpdesk.ticket', 'read',
                    [ticket_ids], {'fields': tickets_fields}
                )
                df_full = pd.DataFrame(tickets_data)
                df_full['user_id_num'] = df_full['user_id'].apply(
                    lambda x: int(x[0]) if isinstance(x, list) else None
                )
                df_full = df_full[['id', 'user_id', 'user_id_num']]

            st.session_state.cache_fechados_mes_df = df_full.copy()
            df_final = df_full
        else:
            # DELTA do dia
            hoje = _hoje_str()
            id_delta = models.execute_kw(
                db, uid, password, 'helpdesk.ticket', 'search',
                [[
                    ['team_id', '=', 1],
                    ['write_date', '>=', hoje]
                ]],
                {'limit': 5000, 'order': 'write_date desc'}
            )
            delta = [] if not id_delta else models.execute_kw(
                db, uid, password, 'helpdesk.ticket', 'read', [id_delta],
                {'fields': tickets_fields}
            )
            df_delta = pd.DataFrame(delta) if delta else pd.DataFrame(columns=tickets_fields)

            st.session_state.cache_fechados_mes_df = _merge_delta_fechados_mes(
                st.session_state.cache_fechados_mes_df, df_delta, id_stages_fechados, primeiro_dia, proximo_dia_1
            )
            df_final = st.session_state.cache_fechados_mes_df

        st.session_state.fechados_cache = {
            'df': df_final,
            'timestamp': time.time()
        }
        return df_final

    # ----------------------------
    # ✨ Restante do código (inalterado)
    # ----------------------------
    def tratar_dados(df):
        if df is None or df.empty:
            return pd.DataFrame(columns=['id','ticket_ref','estagio','agente','equipe','prioridade','user_id','user_id_num'])
        df = df.copy()
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

    def mostrar_fotos_agentes(df, df_fechados_mes, *_):
        placeholder = st.empty()
        with placeholder.container():
            df = df.copy()
            df['agente'] = df['agente'].apply(extrair_primeiro_e_segundo_nome)
            df_grouped = df.groupby(['agente', 'user_id_num'])
            grupos_ordenados = sorted(df_grouped, key=lambda x: len(x[1]), reverse=True)

            def carregar_imagens_local(user_ids):
                imagens = {}
                base_dir = os.path.dirname(os.path.abspath(__file__))
                for user_id in user_ids:
                    nome_arquivo = f"{int(float(user_id))}.png"
                    caminho = os.path.join(base_dir, "assets", "fotos_agentes", nome_arquivo)
                    if os.path.isfile(caminho):
                        with open(caminho, "rb") as f:
                            imagens[user_id] = base64.b64encode(f.read()).decode("utf-8")
                    else:
                        imagens[user_id] = None
                return imagens

            user_ids = [id_user for (_, id_user), _ in grupos_ordenados if id_user is not None]
            if "imagens_cache" not in st.session_state:
                st.session_state.imagens_cache = carregar_imagens_local(user_ids)
            imagens_cache = st.session_state.imagens_cache

            if "fechados_anteriores" not in st.session_state:
                st.session_state.fechados_anteriores = {}
            if "tendencia_icone_estado" not in st.session_state:
                st.session_state.tendencia_icone_estado = {}

            n_colunas = 5
            card_style_base = """
                background-color: rgba(0,0,0,0.04);
                border-radius: 30px;
                padding: 10px 6px 6px 6px;
                box-shadow: 0 1px 6px 0 rgba(0,0,0,0.06);
                border: 2px solid #bbb;
                text-align: center;
                min-height: 172px;
                margin-bottom: 8px;
                display: flex;
                flex-direction: column;
                align-items: center;
            """
            img_style_base = """
                width: 85px;
                height: 85px;
                object-fit: cover;
                border-radius: 50%;
                border: 2px solid #bbb;
                background: #f3f3f3;
                margin-bottom: 3px;
            """

            prioridade_emojis = {'Urgente': '🚨', 'Alta': '🔴', 'Média': '🟡', 'Baixa': '🔵', 'False': '⚪', 'Não definida': '⚪'}
            ordem = ['Urgente', 'Alta', 'Média', 'Baixa', 'False', 'Não definida']
            medalhas = ['🥇', '🥈', '🥉']

            df_sem = df[df['user_id_num'].isnull()]
            if not df_sem.empty:
                cols = st.columns(n_colunas, gap="small")
                col = cols[0]
                with col:
                    img_html = f'<img src="https://cdn-icons-png.flaticon.com/512/1828/1828843.png" style="{img_style_base}">'
                    prioridades = df_sem['prioridade'].value_counts().to_dict()
                    prioridade_html = ' '.join(f"{prioridade_emojis[p]} {prioridades[p]}" for p in ordem if p in prioridades)
                    st.markdown(f"""
                        <div style="{card_style_base}">
                            {img_html}
                            <div style="font-weight:600;font-size:1.01em;margin-bottom:1px;">Sem Atribuição</div>
                            <div style="font-size:0.93em;margin-bottom:3px;">🎟️ <b>{len(df_sem)}</b> abertos / ✅ <b>0</b> fechados</div>
                            <hr style="border:0;border-top:1.1px dashed #bbb;margin:7px 0 7px 0;width:90%;">
                            <div style="font-size:0.99em;">{prioridade_html}</div>
                        </div>
                    """, unsafe_allow_html=True)

            for i, ((agente, id_user), df_agente) in enumerate(grupos_ordenados):
                if id_user is None:
                    continue

                total_abertos = len(df_agente)
                total_fechados = 0 if df_fechados_mes.empty else len(df_fechados_mes[df_fechados_mes['user_id_num'] == id_user])

                fechados_anterior = st.session_state.fechados_anteriores.get(id_user, None)

                if fechados_anterior is not None:
                    if total_fechados > fechados_anterior:
                        st.session_state.tendencia_icone_estado[id_user] = {"icone": " 🔼 ", "contador": 3}
                    elif total_fechados < fechados_anterior:
                        st.session_state.tendencia_icone_estado[id_user] = {"icone": " 🔽 ", "contador": 3}
                    else:
                        if id_user in st.session_state.tendencia_icone_estado:
                            if st.session_state.tendencia_icone_estado[id_user]["contador"] > 0:
                                st.session_state.tendencia_icone_estado[id_user]["contador"] -= 1
                            else:
                                st.session_state.tendencia_icone_estado[id_user] = {"icone": "", "contador": 0}
                else:
                    st.session_state.tendencia_icone_estado[id_user] = {"icone": "", "contador": 0}

                st.session_state.fechados_anteriores[id_user] = total_fechados

                estado_tendencia = st.session_state.tendencia_icone_estado.get(id_user, {"icone": "", "contador": 0})
                tendencia_icone = estado_tendencia["icone"] if estado_tendencia["contador"] > 0 else ""

                idx_offset = 1 if not df_sem.empty else 0
                col_idx = (i + idx_offset) % n_colunas
                if col_idx == 0:
                    cols = st.columns(n_colunas, gap="small")
                col = cols[col_idx]

                if tendencia_icone == " 🔼 ":
                    cor_borda = "#3ecf8e"
                elif tendencia_icone == " 🔽 ":
                    cor_borda = "#f45e5e"
                else:
                    cor_borda = "#bbb"

                card_style = f"""
                    background-color: rgba(0,0,0,0.04);
                    border-radius: 30px;
                    padding: 10px 6px 6px 6px;
                    box-shadow: 0 1px 6px 0 rgba(0,0,0,0.06);
                    border: 3px solid {cor_borda};
                    text-align: center;
                    min-height: 172px;
                    margin-bottom: 8px;
                    display: flex;
                    flex-direction: column;
                    align-items: center;
                """
                img_style = f"""
                    width: 85px;
                    height: 85px;
                    object-fit: cover;
                    border-radius: 50%;
                    border: 3px solid {cor_borda};
                    background: #f3f3f3;
                    margin-bottom: 3px;
                """

                with col:
                    img_base64 = imagens_cache.get(id_user)
                    img_html = f'<img src="data:image/png;base64,{img_base64}" style="{img_style}">' if img_base64 else f'<img src="https://i.ibb.co/wrskMjQK/FotoGalo.png" style="{img_style}">'
                    prioridades = df_agente['prioridade'].value_counts().to_dict()
                    prioridade_html = ' '.join(f"{prioridade_emojis[p]} {prioridades[p]}" for p in ordem if p in prioridades)
                    medalhas = ['🥇', '🥈', '🥉']
                    medalha = medalhas[i] if i < 3 else ''

                    st.markdown(f"""
                        <div style="{card_style}">
                            {img_html}
                            <div style="font-weight:600;font-size:1.01em;margin-bottom:1px;">{medalha} {agente} {tendencia_icone}</div>
                            <div style="font-size:0.93em;margin-bottom:3px;">🎟️ <b>{total_abertos}</b> abertos / ✅ <b>{total_fechados}</b> fechados</div>
                            <hr style="border:0;border-top:1.1px dashed  {cor_borda};margin:7px 0 7px 0;width:90%;">
                            <div style="font-size:0.99em;">{prioridade_html}</div>
                        </div>
                    """, unsafe_allow_html=True)

    def tocar_audio(audio_file):
        if platform.system() == "Windows":
            comando = f'powershell -c (New-Object Media.SoundPlayer "{audio_file}").PlaySync();'
            os.system(comando)
        elif platform.system() == "Darwin":
            os.system(f'afplay "{audio_file}"')
        else:
            os.system(f'xdg-open "{audio_file}"')

    def exibir_dashboard(df, df_fechados_mes, models, db, uid, password):
        total_abertos = 0 if df is None else len(df)
        total_fechados = 0 if df_fechados_mes is None else len(df_fechados_mes)

        audio_file_feliz = os.path.join(os.path.dirname(os.path.abspath(__file__)), "feliz.wav")
        audio_file_triste = os.path.join(os.path.dirname(os.path.abspath(__file__)), "triste.wav")

        total_fechados_anterior = st.session_state.get("total_fechados_anterior")

        st.title(f"📺 Dashboard - Equipe Suporte | 🎟️ Abertos: {total_abertos} | ✅ Fechados no mês: {total_fechados}")
        st.badge("🎟️ Tickets Abertos: Todos exceto os Cancelados/Encerrados/Notificados/Faturados. ✅ Fechados: Encerrados/Notificados/Faturados com atualização no mês atual.")

        mostrar_fotos_agentes(df, df_fechados_mes, models, db, uid, password)

        if total_fechados_anterior is not None:
            if total_fechados > total_fechados_anterior:
                st.balloons()
                tocar_audio(audio_file_feliz)
            elif total_fechados < total_fechados_anterior:
                st.snow()
                tocar_audio(audio_file_triste)

        st.session_state["total_fechados_anterior"] = total_fechados

    try:
        main_placeholder = st.empty()
        with main_placeholder.container():
            df_raw, models, db, uid, password = carregar_dados()
            df_tratado = tratar_dados(df_raw)
            df_fechados_mes = carregar_tickets_fechados_mes(models, db, uid, password)
            exibir_dashboard(df_tratado, df_fechados_mes, models, db, uid, password)
    except Exception as e:
        st.error(f"Erro ao carregar dados: {e}")

else:
    st.warning("⏸️ Dashboard desativado temporariamente")
    st.info("Horário de Atualizações: Segunda a Sexta, das 08:00 às 12:00 e das 13:20 às 18:00")
    st.info("As consultas à API estão pausadas. O sistema será reativado automaticamente dentro do próximo horário permitido.")
