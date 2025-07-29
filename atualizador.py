import pandas as pd
import xmlrpc.client
import pickle
from datetime import datetime
import os

def carregar_dados_completos():
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

    # Tickets fechados no mês
    hoje = datetime.now()
    primeiro_dia = hoje.replace(day=1).strftime('%Y-%m-%d')
    proximo_mes = (hoje.replace(day=28) + pd.Timedelta(days=4)).replace(day=1)
    proximo_dia_1 = proximo_mes.strftime('%Y-%m-%d')

    estagios_fechados = ['Encerrado', 'Notificado']
    id_stage_encerrado = models.execute_kw(
        db, uid, password, 'helpdesk.stage', 'search',
        [[['name', 'in', estagios_fechados]]]
    )

    tickets_fechados_ids = models.execute_kw(
        db, uid, password, 'helpdesk.ticket', 'search',
        [[
            ['stage_id', 'in', id_stage_encerrado],
            ['write_date', '>=', primeiro_dia],
            ['write_date', '<', proximo_dia_1],
        ]],
        {'limit': 1000}
    )

    tickets_fechados_dados = models.execute_kw(
        db, uid, password, 'helpdesk.ticket', 'read',
        [tickets_fechados_ids], {'fields': ['user_id']}
    )

    # Coletar user_ids únicos
    user_ids = list({
        int(x['user_id'][0]) for x in tickets_dados + tickets_fechados_dados
        if isinstance(x.get('user_id'), list) and len(x['user_id']) > 0
    })

    # Buscar imagens em blocos de 40
    imagens = {}
    for chunk in [user_ids[i:i+40] for i in range(0, len(user_ids), 40)]:
        dados_user = models.execute_kw(
            db, uid, password, 'res.users', 'read',
            [chunk], {'fields': ['image_1920']}
        )
        for user in dados_user:
            imagens[user['id']] = user.get('image_1920')

    dados = {
        "tickets_abertos": tickets_dados,
        "tickets_fechados_mes": tickets_fechados_dados,
        "imagens": imagens
    }

    # Salva o cache na mesma pasta deste script
    diretorio_atual = os.path.dirname(os.path.abspath(__file__))
    caminho_arquivo = os.path.join(diretorio_atual, "dados_cache.pkl")
    with open(caminho_arquivo, "wb") as f:
        pickle.dump(dados, f)

    print("✅ Cache salvo com sucesso.")

if __name__ == "__main__":
    carregar_dados_completos()