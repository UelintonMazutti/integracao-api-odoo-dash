# loop_atualizador.py
import os
import time
from datetime import datetime
import subprocess

while True:
    now = datetime.now()
    hora = now.hour
    dia_semana = now.weekday()  # 0=segunda, 6=domingo

    if dia_semana < 5 and 8 <= hora < 18:
        print(f"Atualizando cache... {now.strftime('%Y-%m-%d %H:%M:%S')}")
        caminho_arquivo = os.path.join(os.path.dirname(os.path.abspath(__file__)), "atualizador.py")
        subprocess.run(["python", caminho_arquivo])
    else:
        print(f"Fora do horário de atualização ({now.strftime('%Y-%m-%d %H:%M:%S')}). Dormindo até a próxima verificação.")
    time.sleep(10)
