import streamlit as st

st.set_page_config(page_title="Dashboard Helpdesk ERP SAG", layout="wide")

import pandas as pd
import xmlrpc.client
import time
import os
import base64
from datetime import datetime, time as dtime
import platform
from streamlit_autorefresh import st_autorefresh

# 🔁 Mantém refresh ativo sempre (1 minuto)
st_autorefresh(interval=30 * 1000, key="refresh_dashboard", limit=None)

# 🕒 Função de controle de horário
def dentro_do_horario():
    agora = datetime.now()
    dia_semana = agora.weekday()  # 0 = segunda, 6 = domingo
    hora = agora.time()
    return dia_semana < 5 and (
        dtime(8, 0) <= hora <= dtime(12, 0)
        or dtime(13, 20) <= hora <= dtime(18, 0)
    )

# 🧠 Lógica principal
if dentro_do_horario():
    print("✅ Dentro do horário permitido — dashboard ativo")

    st.markdown("""
        <style>
            .block-container {padding-top: 0.7rem !important;}
            h1 {font-size: 2.3rem !important;}
            /* Adiciona transição suave para evitar piscar */
            .element-container {
                transition: opacity 0.3s ease;
            }
        </style>
    """, unsafe_allow_html=True)

    def carregar_dados():
        hoje = datetime.now()
        hoje_str = hoje.strftime('%Y-%m-%d')

        url = "https://suporte.sag.com.br"
        db = "helpdesk-erp"
        username = "uelinton.silva@sag.com.br"
        password = "Dia@28_04#"

        # Reaproveita conexão existente se estiver em cache
        if 'models' in st.session_state and 'uid' in st.session_state:
            models = st.session_state.models
            uid = st.session_state.uid
        else:
            common = xmlrpc.client.ServerProxy(f'{url}/xmlrpc/2/common')
            uid = common.authenticate(db, username, password, {})
            models = xmlrpc.client.ServerProxy(f'{url}/xmlrpc/2/object')
            st.session_state.models = models
            st.session_state.uid = uid

        estagios_excluidos = ['Cancelado/Recusado', 'Encerrado', 'Faturado', 'Notificado']
        id_estagios_validos = models.execute_kw(
            db, uid, password, 'helpdesk.stage', 'search',
            [[['name', 'not in', estagios_excluidos]]]
        )

        tickets_fields = ['id', 'ticket_ref', 'stage_id', 'user_id', 'team_id', 'x_studio_prioridade']

        if 'dados_cache' not in st.session_state or st.session_state.get('ultima_execucao_dados') != hoje_str:
            # Primeira execução do dia — busca completa
            dominio = [
                ['stage_id', 'in', id_estagios_validos],
                ['team_id', '=', 1]
            ]
            st.session_state.ultima_execucao_dados = hoje_str
            id_tickets = models.execute_kw(
                db, uid, password, 'helpdesk.ticket', 'search',
                [dominio],
                {'limit': 1000, 'order': 'create_date desc'}
            )
            tickets_dados = models.execute_kw(
                db, uid, password, 'helpdesk.ticket', 'read',
                [id_tickets], {'fields': tickets_fields}
            )
            df = pd.DataFrame(tickets_dados)
        else:
            # Execução incremental — busca somente alterados hoje
            dominio = [
                ['stage_id', 'in', id_estagios_validos],
                ['team_id', '=', 1],
                ['write_date', '>=', hoje_str]
            ]
            id_tickets = models.execute_kw(
                db, uid, password, 'helpdesk.ticket', 'search',
                [dominio],
                {'limit': 1000, 'order': 'write_date desc'}
            )
            if id_tickets:
                tickets_dados = models.execute_kw(
                    db, uid, password, 'helpdesk.ticket', 'read',
                    [id_tickets], {'fields': tickets_fields}
                )
                df_alterados = pd.DataFrame(tickets_dados)
                # Atualiza registros alterados no cache
                df_antigo = st.session_state.dados_cache['df']
                df = pd.concat([
                    df_antigo[~df_antigo['id'].isin(df_alterados['id'])],
                    df_alterados
                ], ignore_index=True)
            else:
                df = st.session_state.dados_cache['df']

        # Atualiza cache
        st.session_state.dados_cache = {
            'df': df,
            'models': models,
            'db': db,
            'uid': uid,
            'password': password,
            'timestamp': time.time()
        }

        df.to_excel("Tickets_Abertos.xlsx", index=False)
        ticket = df[df['ticket_ref'] == '106786']

        if not ticket.empty:
            descricao = ticket['stage_id'].iloc[0][1]  # Pega apenas a descrição do estágio
            print(f"Status do Ticket 106786 em Abertos: {descricao}")
        else:
            print("Ticket 106786 não encontrado em Abertos.")

        return df, models, db, uid, password

    def carregar_tickets_fechados_mes(models, db, uid, password):
        hoje = datetime.now()
        hoje_str = hoje.strftime('%Y-%m-%d')

        estagios_fechados = ['Encerrado', 'Notificado']

        id_stage_encerrado = models.execute_kw(db, uid, password, 'helpdesk.stage', 'search', [[['name', 'in', estagios_fechados]]])

        if not id_stage_encerrado:
            return pd.DataFrame()

        tickets_fields = ['id', 'user_id', 'ticket_ref', 'stage_id', 'team_id']

        if 'fechados_cache' not in st.session_state or st.session_state.get('ultima_execucao_fechados') != hoje_str:
            # Primeira execução do dia — busca completa do mês
            primeiro_dia = hoje.replace(day=1).strftime('%Y-%m-%d')
            proximo_mes = (hoje.replace(day=28) + pd.Timedelta(days=4)).replace(day=1)
            proximo_dia_1 = proximo_mes.strftime('%Y-%m-%d')

            dominio = [
                ['stage_id', 'in', id_stage_encerrado],
                ['write_date', '>=', primeiro_dia],
                ['write_date', '<', proximo_dia_1],
                ['team_id', '=', 1]
            ]

            st.session_state.ultima_execucao_fechados = hoje_str

            ticket_ids = models.execute_kw(
                db, uid, password, 'helpdesk.ticket', 'search',
                [dominio],
                {'limit': 1000}
            )

            if ticket_ids:
                tickets_data = models.execute_kw(
                    db, uid, password, 'helpdesk.ticket', 'read',
                    [ticket_ids], {'fields': tickets_fields}
                )
                df = pd.DataFrame(tickets_data)
            else:
                df = pd.DataFrame()
        else:
            # Execução incremental — apenas os alterados hoje
            dominio = [
                ['write_date', '>=', hoje_str],
                ['team_id', '=', 1]
            ]

            ticket_ids = models.execute_kw(
                db, uid, password, 'helpdesk.ticket', 'search',
                [dominio],
                {'limit': 1000}
            )

            if ticket_ids:
                tickets_data = models.execute_kw(
                    db, uid, password, 'helpdesk.ticket', 'read',
                    [ticket_ids], {'fields': tickets_fields}
                )
                df_alterados = pd.DataFrame(tickets_data)

                df_antigo = st.session_state.fechados_cache['df'] if 'fechados_cache' in st.session_state else pd.DataFrame()
                df = pd.concat([
                    df_antigo[~df_antigo['id'].isin(df_alterados['id'])],
                    df_alterados
                ], ignore_index=True)
            else:
                df = st.session_state.fechados_cache['df']

        # Adiciona coluna auxiliar
        if not df.empty:
            df['user_id_num'] = df['user_id'].apply(lambda x: int(x[0]) if isinstance(x, list) else None)

        # Atualiza o cache
        st.session_state.fechados_cache = {
            'df': df,
            'timestamp': time.time()
        }

        df.to_excel("Tickets_Fechados_Mes.xlsx", index=False)
        ticket = df[df['ticket_ref'] == '106786']

        if not ticket.empty:
            descricao = ticket['stage_id'].iloc[0][1]  # Pega apenas a descrição do estágio
            print(f"Status do Ticket 106786 em Fechados: {descricao}")
        else:
            print("Ticket 106786 não encontrado em Abertos.")

        return df


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

    def mostrar_fotos_agentes(df, df_fechados_mes, *_):
        placeholder = st.empty()

        with placeholder.container():
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
            card_style = """
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
            img_style = """
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
                    img_html = f'<img src="https://cdn-icons-png.flaticon.com/512/1828/1828843.png" style="{img_style}">'
                    prioridades = df_sem['prioridade'].value_counts().to_dict()
                    prioridade_html = ' '.join(f"{prioridade_emojis[p]} {prioridades[p]}" for p in ordem if p in prioridades)
                    st.markdown(f"""
                        <div style="{card_style}">
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

                
                # Cor da borda com base na tendência
                if tendencia_icone == " 🔼 ":
                    cor_borda = "#3ecf8e"  # verde
                elif tendencia_icone == " 🔽 ":
                    cor_borda = "#f45e5e"  # vermelho
                else:
                    cor_borda = "#bbb"     # cinza padrão

                card_style = """
                    background-color: rgba(0,0,0,0.04);
                    border-radius: 30px;
                    padding: 10px 6px 6px 6px;
                    box-shadow: 0 1px 6px 0 rgba(0,0,0,0.06);
                    border: 3px solid """ + cor_borda + """;
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
                    border: 3px solid """ + cor_borda + """;
                    background: #f3f3f3;
                    margin-bottom: 3px;
                """

                with col:
                    img_base64 = imagens_cache.get(id_user)
                    img_html = f'<img src="data:image/png;base64,{img_base64}" style="{img_style}">' if img_base64 else f'<img src="https://i.ibb.co/wrskMjQK/FotoGalo.png" style="{img_style}">'
                    prioridades = df_agente['prioridade'].value_counts().to_dict()
                    prioridade_html = ' '.join(f"{prioridade_emojis[p]} {prioridades[p]}" for p in ordem if p in prioridades)
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
        total_abertos = len(df)
        total_fechados = len(df_fechados_mes)

        audio_file_feliz = os.path.join(os.path.dirname(os.path.abspath(__file__)), "feliz.wav")
        audio_file_triste = os.path.join(os.path.dirname(os.path.abspath(__file__)), "triste.wav")

        total_fechados_anterior = st.session_state.get("total_fechados_anterior")

        st.title(f"📺 Dashboard - Equipe Suporte | 🎟️ Abertos: {total_abertos} | ✅ Fechados no mês: {total_fechados}")
        st.badge("🎟️ Tickets Abertos: Todos exceto os ***Cancelados***, ***Encerrados***, ***Notificados*** ou ***Faturados***. ✅ Tickets Fechados: ***Encerrados***, ***Notificados*** ou ***Faturados***, com data de atualização no mês atual.")

        mostrar_fotos_agentes(df, df_fechados_mes, models, db, uid, password)
        
        # Só entra nas animações se já houver valor anterior
        if total_fechados_anterior is not None:
            if total_fechados > total_fechados_anterior:
                st.balloons()
                tocar_audio(audio_file_feliz)

            elif total_fechados < total_fechados_anterior:
                st.snow()
                tocar_audio(audio_file_triste)

        # Atualiza sempre no final (inclusive na primeira vez)
        st.session_state["total_fechados_anterior"] = total_fechados

    try:
        # Usar um placeholder para o conteúdo principal
        main_placeholder = st.empty()
        
        with main_placeholder.container():
            df_raw, models, db, uid, password = carregar_dados()
            df_tratado = tratar_dados(df_raw)
            df_fechados_mes = carregar_tickets_fechados_mes(models, db, uid, password)
            exibir_dashboard(df_tratado, df_fechados_mes, models, db, uid, password)
            # df_tratado.to_excel("Tickets_Abertos.xlsx", index=False)
            # df_fechados_mes.to_excel("Tickets_Fechados_Mes.xlsx", index=False)
            # print("Dados carregados com sucesso!")
    except Exception as e:
        st.error(f"Erro ao carregar dados: {e}")
else:
    st.warning("⏸️ Dashboard desativado temporariamente")
    st.info("Horário de Atualizações: Segunda a Sexta, das 08:00 às 12:00 e das 13:20 às 18:00")
    st.info("As consultas à API estão pausadas. O sistema será reativado automaticamente dentro do próximo horário permitido.")