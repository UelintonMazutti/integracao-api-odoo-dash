url = "https://suporte.sag.com.br"
db = "helpdesk-erp"
username = "uelinton.silva@sag.com.br"
password = "Dia@28_04#"

import pandas as pd
import xmlrpc.client

common = xmlrpc.client.ServerProxy('{}/xmlrpc/2/common'.format(url))
versao = common.version()
uid = common.authenticate(db, username, password, {})
models = xmlrpc.client.ServerProxy('{}/xmlrpc/2/object'.format(url))

# Campos de Cada Tabela
contatos_fields = ['name', 'country_id', 'comment', 'x_studio_mdulos_contratados','x_studio_classificao','phone',
                   'x_studio_categoria_empresaprodutor','mobile','x_studio_selection_field_86q_1hu3p48la']

modulos_fields = ['id', 'x_name', 'display_name']

tickets_fields = ['id','x_studio_projeto_cc','x_studio_resumo','x_studio_sprints','x_studio_ltima_rotina','description']

# IDs dos Registros
id_contatos = models.execute_kw(db, uid, password, 'res.partner', 'search', [[['is_company', '=', True]]])
id_modulos = models.execute_kw(db, uid, password, 'x_modulo', 'search', [[]])
id_tickets = models.execute_kw(db, uid, password, 'helpdesk.ticket', 'search', [[]])

# Lista de Campos para Consulta
lista_campos_contatos = models.execute_kw(db, uid, password, 'res.partner', 'fields_get', [], {'attributes': ['string']})
lista_campos_modulos = models.execute_kw(db, uid, password, 'x_modulo', 'fields_get', [], {'attributes': ['string', 'help', 'type']})
lista_campos_tickets = models.execute_kw(db, uid, password, 'helpdesk.ticket', 'fields_get', [], {'attributes': ['string', 'help', 'type']})

# Dados dos Registros com base nos IDs
contatos_dados = models.execute_kw(db, uid, password, 'res.partner', 'read', [id_contatos], {'fields': contatos_fields})
modulos_dados = models.execute_kw(db, uid, password, 'x_modulo', 'read', [id_modulos], {'fields': modulos_fields})
# tickets_fields = list(lista_campos_tickets.keys())
tickets_dados = models.execute_kw(db, uid, password, 'helpdesk.ticket', 'read', [74258], {'fields': tickets_fields})

# Convertendo para DataFrame
df_modulos = pd.DataFrame(modulos_dados)
df_contatos = pd.DataFrame(contatos_dados)
df_tickets = pd.DataFrame(tickets_dados)

# Alterando o módulo de Código para o Nome
map_modulos = df_modulos.set_index('id')['display_name'].to_dict()
df_contatos['x_studio_mdulos_contratados'] = df_contatos['x_studio_mdulos_contratados'].apply(lambda lista: [map_modulos.get(x, f'ID {x} desconhecido') for x in lista])

# Converter de Json em Colunas para Excel em Linhas
rows = [{'key': key, 'label': value.get('string', ''), 'type': value.get('type', '')} for key, value in lista_campos_tickets.items()]
df_listacampostickets = pd.DataFrame(rows)
df_listacampostickets.to_excel("Lista Campos Tickets.xlsx", index=False)

# Exportando para Excel
df_modulos.to_excel("Modulos.xlsx", index=False)
df_contatos.to_excel("Contatos.xlsx", index=False)
df_tickets.to_excel("Tickets.xlsx", index=False)

