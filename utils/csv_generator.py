import csv
import os
import re
import uuid

def csv_generator(tabela: str, session_id: str) -> str:
    """Gera CSV do itinerário no formato desejado (com índice) e de forma segura."""
    
    os.makedirs('arquivos', exist_ok=True)
    
    linhas = [l for l in tabela.strip().splitlines() if '|' in l and not re.match(r'^[|: -]+$', l.replace(" ", ""))]
    
    if len(linhas) < 2:
        print(f"❌ Erro no csv_generator: Tabela com apenas {len(linhas)} linha(s). CSV não gerado.")
        raise ValueError("Dados insuficientes para gerar um CSV útil (cabeçalho + dados).")

    nome_arquivo = f"itinerario_{session_id[:6]}_{uuid.uuid4().hex[:4]}.csv"
    caminho_completo = os.path.join('arquivos', nome_arquivo)

    with open(caminho_completo, 'w', newline='', encoding='utf-8') as csvfile:
        writer = csv.writer(csvfile, delimiter=';')
        
        # >>> ALTERAÇÃO PARA O NOVO FORMATO <<<
        # Escreve o cabeçalho manualmente como na imagem de exemplo
        cabecalho_original = [col.strip() for col in linhas[0].split('|')][1:-1]
        writer.writerow([''] + cabecalho_original) # Adiciona a primeira coluna vazia

        # Escreve as linhas de dados com um índice
        for indice, linha_dados in enumerate(linhas[1:], start=1):
            celulas = [col.strip() for col in linha_dados.split('|')][1:-1]
            if celulas:
                writer.writerow([indice] + celulas)

    return caminho_completo