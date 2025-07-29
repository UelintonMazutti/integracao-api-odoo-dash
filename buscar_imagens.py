# salvar_fotos.py

import xmlrpc.client
import base64
import os

# Configurações de acesso ao Odoo
url = "https://suporte.sag.com.br"
db = "helpdesk-erp"
username = "uelinton.silva@sag.com.br"
password = "Dia@28_04#"

# Conexão
common = xmlrpc.client.ServerProxy(f'{url}/xmlrpc/2/common')
uid = common.authenticate(db, username, password, {})
models = xmlrpc.client.ServerProxy(f'{url}/xmlrpc/2/object')

# Buscar todos os usuários
user_ids = models.execute_kw(db, uid, password, 'res.users', 'search', [[]])
users_data = models.execute_kw(
    db, uid, password, 'res.users', 'read',
    [user_ids], {'fields': ['name', 'image_1920']}
)

# Criar pasta de destino
output_folder = os.path.join("assets", "fotos_agentes")
os.makedirs(output_folder, exist_ok=True)

# Salvar imagens
for user in users_data:
    img_data = user.get("image_1920")
    user_id = user["id"]
    nome_arquivo = os.path.join(output_folder, f"{user_id}.png")

    if img_data:
        with open(nome_arquivo, "wb") as f:
            f.write(base64.b64decode(img_data))
        print(f"Imagem salva: {nome_arquivo}")
    else:
        print(f"Usuário {user['name']} sem imagem.")
