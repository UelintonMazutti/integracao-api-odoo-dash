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

# =========================
# CONFIG DE LOGS
# =========================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_DIR = os.path.join(BASE_DIR, "logs_tickets")
os.makedirs(LOG_DIR, exist_ok=True)
LOG_FILE_TXT = os.path.join(LOG_DIR, "tickets_busca.log")

def _hoje_csv_path():
    return os.path.join(LOG_DIR, f"tickets_busca_{datetime.now().strftime('%Y%m%d')}.csv")

def registrar_log_texto(tipo_busca: str, df: pd.DataFrame):
    agora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if df is None or df.empty:
        linha = f"[{agora}] {tipo_busca}: Nenhum ticket retornado.\n"
    else:
        try:
            ids = ", ".join(str(i) for i in df["id"].tolist())
        except Exception:
            ids = "ids indisponíveis"
        linha = f"[{agora}] {tipo_busca}: {len(df)} tickets. IDs: {ids}\n"
    with open(LOG_FILE_TXT, "a", encoding="utf-8") as f:
        f.write(linha)

def _flatten_many2one(val, idx=1, default=None):
    """Extrai nome/ID de campos many2one (lista [id, nome])."""
    try:
        if isinstance(val, list) and len(val) > idx:
            return val[idx]
    except Exception:
        pass
    return default

def _flatten_many2one_id(val):
    try:
        if isinstance(val, list) and len(val) > 0 and isinstance(val[0], (int, float)):
            return int(val[0])
    except Exception:
        pass
    return None

def registrar_log_csv(tipo_busca: str, df: pd.DataFrame):
    """Salva CSV diário com colunas achatadas, anexando linhas novas."""
    if df is None or df.empty:
        # Mesmo sem registros, anotamos o "marco" da busca
        meta = pd.DataFrame([{
            "timestamp": datetime.now(),
            "tipo_busca": tipo_busca,
            "id": None,
            "ticket_ref": None,
            "stage_id": None,
            "stage_name": None,
            "user_id_num": None,
            "user_name": None,
            "team_id": None,
            "team_name": None,
            "prioridade": None,
            "create_date": None,
            "write_date": None,
        }])
        meta.to_csv(_hoje_csv_path(), index=False, mode="a", header=not os.path.exists(_hoje_csv_path()))
        return

    # Monta DataFrame achatado
    flat = pd.DataFrame({
        "timestamp": datetime.now(),
        "tipo_busca": tipo_busca,
        "id": df.get("id", pd.Series(dtype="Int64")),
        "ticket_ref": df.get("ticket_ref", pd.Series(dtype="object")),
        "stage_id": df.get("stage_id", pd.Series(dtype="object")).apply(_flatten_many2one_id) if "stage_id" in df else None,
        "stage_name": df.get("stage_id", pd.Series(dtype="object")).apply(lambda x: _flatten_many2one(x, 1)) if "stage_id" in df else None,
        "user_id_num": df.get("user_id", pd.Series(dtype="object")).apply(_flatten_many2one_id) if "user_id" in df else None,
        "user_name": df.get("user_id", pd.Series(dtype="object")).apply(lambda x: _flatten_many2one(x, 1)) if "user_id" in df else None,
        "team_id": df.get("team_id", pd.Series(dtype="object")).apply(_flatten_many2one_id) if "team_id" in df else None,
        "team_name": df.get("team_id", pd.Series(dtype="object")).apply(lambda x: _flatten_many2one(x, 1)) if "team_id" in df else None,
        "prioridade": df.get("x_studio_prioridade", pd.Series(dtype="object")),
        "create_date": df.get("create_date", pd.Series(dtype="object")),
        "write_date": df.get("write_date", pd.Series(dtype="object")),
    })

    # Converte datas para facilitar análise posterior
    for col in ["create_date", "write_date", "timestamp"]:
        if col in flat.columns:
            flat[col] = pd.to_datetime(flat[col], errors="coerce")

    flat.to_csv(_hoje_csv_path(), index=False, mode="a", header=not os.path.exists(_hoje_csv_path()))

# 🕒 Função de controle de horário
def dentro_do_horario():
    agora = datetime.now()
    dia_semana = agora.weekday()  # 0 = segunda, 6 = domingo
    hora = agora.time()
    return dia_semana < 5 and (
        dtime(8, 0) <= hora <= dtime(12, 0)
        or dtime(13, 20) <= hora <= dtime(18, 0)
    )

# =========================
# ODOO / AUTENTICAÇÃO (cache leve)
# =========================
def get_odoo_clients():
    # cache leve da sessão Odoo (reaproveita por 25s)
    if "odoo_cache" in st.session_state and time.time() - st.session_state.odoo_cache["ts"] < 25:
        c = st.session_state.odoo_cache
        return c["models"], c["db"], c["uid"], c["password"]

    url = "https://suporte.sag.com.br"
    db = "helpdesk-erp"
    username = "uelinton.silva@sag.com.br"
    password = "Dia@28_04#"

    common = xmlrpc.client.ServerProxy(f"{url}/xmlrpc/2/common")
    uid = common.authenticate(db, username, password, {})
    if not uid:
        raise RuntimeError("Falha na autenticação do Odoo (uid vazio).")

    models = xmlrpc.client.ServerProxy(f"{url}/xmlrpc/2/object")

    st.session_state.odoo_cache = {
        "models": models, "db": db, "uid": uid, "password": password, "ts": time.time()
    }
    return models, db, uid, password

# =========================
# BUSCAS: FULL e INCREMENTAL (com LOG)
# =========================
FIELDS = [
    "id", "ticket_ref", "stage_id", "user_id", "team_id",
    "x_studio_prioridade", "create_date", "write_date"
]
DOMINIO_BASE = [
    ["team_id", "=", 1],
    ["ticket_ref", "!=", 106786],  # exclui ticket de teste
]

def buscar_full(models, db, uid, password, limit=5000):
    ids = models.execute_kw(
        db, uid, password, "helpdesk.ticket", "search",
        [DOMINIO_BASE], {"limit": limit, "order": "write_date desc"}
    )
    if not ids:
        df = pd.DataFrame(columns=FIELDS)
    else:
        data = models.execute_kw(
            db, uid, password, "helpdesk.ticket", "read", [ids], {"fields": FIELDS}
        )
        df = pd.DataFrame(data)

    # LOGS
    registrar_log_texto("FULL", df)
    registrar_log_csv("FULL", df)
    return df

def buscar_incremental_hoje(models, db, uid, password, limit=5000):
    # hoje a partir de 00:00
    hoje0 = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    hoje_str = hoje0.strftime("%Y-%m-%d %H:%M:%S")
    dominio = DOMINIO_BASE + [["write_date", ">=", hoje_str]]
    ids = models.execute_kw(
        db, uid, password, "helpdesk.ticket", "search",
        [dominio], {"limit": limit, "order": "write_date desc"}
    )
    if not ids:
        df = pd.DataFrame(columns=FIELDS)
    else:
        data = models.execute_kw(
            db, uid, password, "helpdesk.ticket", "read", [ids], {"fields": FIELDS}
        )
        df = pd.DataFrame(data)

    # LOGS
    registrar_log_texto("INCREMENTAL", df)
    registrar_log_csv("INCREMENTAL", df)
    return df

def upsert_por_id(df_base, df_novos):
    """Atualiza df_base com df_novos usando 'id' como chave (atualiza e inclui)."""
    if df_base is None or df_base.empty:
        return df_novos.copy()

    # garante colunas
    for c in FIELDS:
        if c not in df_base.columns:
            df_base[c] = None
        if c not in df_novos.columns:
            df_novos[c] = None

    base = df_base.set_index("id")
    novos = df_novos.set_index("id")
    base.update(novos)           # atualiza registros existentes
    faltantes = novos.index.difference(base.index)
    if len(faltantes) > 0:
        base = pd.concat([base, novos.loc[faltantes]], axis=0)

    return base.reset_index()

# =========================
# CONSULTA INTELIGENTE (FULL 1ª vez do dia, INCREMENTAL nas demais)
# =========================
def carregar_tickets_inteligente():
    """
    Na primeira execução do dia (ou quando não houver cache): FULL.
    Nas execuções seguintes do mesmo dia: INCREMENTAL (write_date >= hoje 00:00),
    fazendo upsert sobre o cache FULL do dia.
    Retorna df_all, models, db, uid, password (com cache de 25s geral).
    """
    # cache geral de 25s
    if "dados_cache" in st.session_state and time.time() - st.session_state.dados_cache["timestamp"] < 25:
        c = st.session_state.dados_cache
        return c["df_all"], c["models"], c["db"], c["uid"], c["password"]

    models, db, uid, password = get_odoo_clients()

    hoje_data = datetime.now().date()
    last_full_date = st.session_state.get("last_full_date")
    df_all = st.session_state.get("df_all")  # cache acumulado do dia

    if last_full_date != hoje_data or df_all is None or df_all.empty:
        # PRIMEIRA DO DIA → FULL
        df_full = buscar_full(models, db, uid, password)
        df_all = df_full
        st.session_state.last_full_date = hoje_data
    else:
        # DEMAIS → INCREMENTAL HOJE + UPSERT
        df_inc = buscar_incremental_hoje(models, db, uid, password)
        if not df_inc.empty:
            df_all = upsert_por_id(df_all, df_inc)

    # cache final de 25s
    st.session_state.dados_cache = {
        "df_all": df_all, "models": models, "db": db, "uid": uid, "password": password,
        "timestamp": time.time()
    }
    st.session_state.df_all = df_all  # mantém acumulado do dia

    return df_all, models, db, uid, password

# =========================
# RESTO DO APP
# =========================

# 🧠 Lógica principal
def dentro_do_horario():
    agora = datetime.now()
    dia_semana = agora.weekday()  # 0 = segunda, 6 = domingo
    hora = agora.time()
    return dia_semana < 5 and (
        dtime(8, 0) <= hora <= dtime(12, 0)
        or dtime(13, 20) <= hora <= dtime(18, 0)
    )

if dentro_do_horario():
    print("✅ Dentro do horário permitido — dashboard ativo")

    st.markdown("""
        <style>
            .block-container {padding-top: 0.7rem !important;}
            h1 {font-size: 2.3rem !important;}
            .element-container { transition: opacity 0.3s ease; }
        </style>
    """, unsafe_allow_html=True)

    def tratar_dados(df):
        # Normalizações necessárias
        if "write_date" in df.columns:
            df["write_date"] = pd.to_datetime(df["write_date"], errors="coerce")

        df["agente"] = df["user_id"].apply(lambda x: x[1] if isinstance(x, list) and len(x) > 1 else "Sem Atribuição")
        df["user_id_num"] = df["user_id"].apply(
            lambda x: int(x[0]) if isinstance(x, list) and len(x) > 0 and isinstance(x[0], (int, float)) else None
        )
        df["estagio"] = df["stage_id"].apply(lambda x: x[1] if isinstance(x, list) and len(x) > 1 else "Desconhecido")
        df["equipe"] = df["team_id"].apply(lambda x: x[1] if isinstance(x, list) and len(x) > 1 else "Desconhecida")
        df["prioridade"] = df["x_studio_prioridade"].astype(str)

        colunas = ["id", "ticket_ref", "estagio", "agente", "equipe", "prioridade", "user_id", "user_id_num", "write_date"]
        for c in colunas:
            if c not in df.columns:
                df[c] = None
        return df[colunas]

    def extrair_primeiro_e_segundo_nome(nome):
        partes = nome.split()
        return " ".join(partes[:2]) if len(partes) >= 2 else nome

    def mostrar_fotos_agentes(df_abertos, df_fechados_mes, *_):
        placeholder = st.empty()

        with placeholder.container():
            df_abertos["agente"] = df_abertos["agente"].apply(extrair_primeiro_e_segundo_nome)

            df_grouped = df_abertos.groupby(["agente", "user_id_num"])
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
            prioridade_emojis = {'Urgente': '🚨', 'Alta': '🔴', 'Média': '🟡', 'Baixa': '🔵', 'False': '⚪', 'Não definida': '⚪'}
            ordem = ['Urgente', 'Alta', 'Média', 'Baixa', 'False', 'Não definida']
            medalhas = ['🥇', '🥈', '🥉']

            # Card "Sem Atribuição" usa ABERTOS
            df_sem = df_abertos[df_abertos["user_id_num"].isnull()]
            if not df_sem.empty:
                cols = st.columns(n_colunas, gap="small")
                col = cols[0]
                with col:
                    img_html = f'<img src="https://cdn-icons-png.flaticon.com/512/1828/1828843.png" style="width:85px;height:85px;object-fit:cover;border-radius:50%;border:2px solid #bbb;background:#f3f3f3;margin-bottom:3px;">'
                    prioridades = df_sem["prioridade"].value_counts().to_dict()
                    prioridade_html = ' '.join(f"{prioridade_emojis[p]} {prioridades[p]}" for p in ordem if p in prioridades)
                    st.markdown(f"""
                        <div style="background-color:rgba(0,0,0,0.04);border-radius:30px;padding:10px 6px 6px 6px;box-shadow:0 1px 6px 0 rgba(0,0,0,0.06);border:2px solid #bbb;text-align:center;min-height:172px;margin-bottom:8px;display:flex;flex-direction:column;align-items:center;">
                            {img_html}
                            <div style="font-weight:600;font-size:1.01em;margin-bottom:1px;">Sem Atribuição</div>
                            <div style="font-size:0.93em;margin-bottom:3px;">🎟️ <b>{len(df_sem)}</b> abertos / ✅ <b>0</b> fechados</div>
                            <hr style="border:0;border-top:1.1px dashed #bbb;margin:7px 0 7px 0;width:90%;">
                            <div style="font-size:0.99em;">{prioridade_html}</div>
                        </div>
                    """, unsafe_allow_html=True)

            for i, ((agente, id_user), df_agente_abertos) in enumerate(grupos_ordenados):
                if id_user is None:
                    continue

                total_abertos = len(df_agente_abertos)
                total_fechados = 0 if df_fechados_mes.empty else len(df_fechados_mes[df_fechados_mes["user_id_num"] == id_user])

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

                # layout
                idx_offset = 1 if not df_sem.empty else 0
                col_idx = (i + idx_offset) % n_colunas
                if col_idx == 0:
                    cols = st.columns(n_colunas, gap="small")
                col = cols[col_idx]

                # Bordas/cores por tendência
                if tendencia_icone == " 🔼 ":
                    cor_borda = "#3ecf8e"  # verde
                elif tendencia_icone == " 🔽 ":
                    cor_borda = "#f45e5e"  # vermelho
                else:
                    cor_borda = "#bbb"     # cinza padrão

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
                    img_base64 = st.session_state.imagens_cache.get(id_user)
                    img_html = f'<img src="data:image/png;base64,{img_base64}" style="{img_style}">' if img_base64 else f'<img src="https://i.ibb.co/wrskMjQK/FotoGalo.png" style="{img_style}">'
                    prioridades = df_agente_abertos["prioridade"].value_counts().to_dict()
                    prioridade_html = ' '.join(f"{prioridade_emojis[p]} {prioridades[p]}" for p in ordem if p in prioridades)
                    medalha = medalhas[i] if i < 3 else ""

                    st.markdown(f"""
                        <div style="{card_style}">
                            {img_html}
                            <div style="font-weight:600;font-size:1.01em;margin-bottom:1px;">{medalha} {agente} {tendencia_icone}</div>
                            <div style="font-size:0.93em;margin-bottom:3px;">🎟️ <b>{total_abertos}</b> abertos / ✅ <b>{total_fechados}</b> fechados</div>
                            <hr style="border:0;border-top:1.1px dashed {cor_borda};margin:7px 0 7px 0;width:90%;">
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

    def exibir_dashboard(df_abertos, df_fechados_mes, models, db, uid, password):
        total_abertos = len(df_abertos)
        total_fechados = len(df_fechados_mes)

        audio_file_feliz = os.path.join(os.path.dirname(os.path.abspath(__file__)), "feliz.wav")
        audio_file_triste = os.path.join(os.path.dirname(os.path.abspath(__file__)), "triste.wav")

        total_fechados_anterior = st.session_state.get("total_fechados_anterior")

        st.title(f"📺 Dashboard - Equipe Suporte | 🎟️ Abertos: {total_abertos} | ✅ Fechados no mês: {total_fechados}")
        st.badge("🎟️ Abertos: qualquer período (exceto Cancelado/Recusado, Encerrado, Notificado, Faturado). ✅ Fechados: Encerrado/Notificado/Faturado com write_date no mês atual.")

        mostrar_fotos_agentes(df_abertos, df_fechados_mes, models, db, uid, password)
        
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
            # 1) Carga inteligente (FULL 1ª do dia; INCREMENTAL nas demais) + LOG
            df_raw, models, db, uid, password = carregar_tickets_inteligente()

            # 2) Normalização
            df_tratado = tratar_dados(df_raw)

            # 3) Conjuntos de estágios
            estagios_fechados = {'Encerrado', 'Notificado', 'Faturado'}
            estagios_cancelados = {'Cancelado/Recusado'}
            estagios_nao_abertos = estagios_fechados | estagios_cancelados

            # 4) Fechados do mês (estágio + write_date dentro do mês atual)
            hoje = datetime.now()
            primeiro_dia = hoje.replace(day=1).replace(hour=0, minute=0, second=0, microsecond=0)
            proximo_mes = (hoje.replace(day=28) + pd.Timedelta(days=4)).replace(day=1).replace(hour=0, minute=0, second=0, microsecond=0)

            df_fechados_mes = df_tratado[
                (df_tratado['estagio'].isin(estagios_fechados)) &
                (df_tratado['write_date'] >= primeiro_dia) &
                (df_tratado['write_date'] <  proximo_mes)
            ].copy()

            # 5) Abertos de QUALQUER período (só filtra estágio)
            df_abertos = df_tratado[~df_tratado['estagio'].isin(estagios_nao_abertos)].copy()

            # 6) Render
            exibir_dashboard(df_abertos, df_fechados_mes, models, db, uid, password)

    except Exception as e:
        st.error(f"Erro ao carregar dados: {e}")
else:
    st.warning("⏸️ Dashboard desativado temporariamente")
    st.info("Horário de Atualizações: Segunda a Sexta, das 08:00 às 12:00 e das 13:20 às 18:00")
    st.info("As consultas à API estão pausadas. O sistema será reativado automaticamente dentro do próximo horário permitido.")
