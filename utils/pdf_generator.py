from weasyprint import HTML
from datetime import datetime
import os
import re

def gerar_pdf(destino: str, datas: str, tabela: str, descricao: str, session_id: str) -> str:
    tabela_html = ""
    
    # Validação robusta para a tabela
    if tabela and tabela.count('|') > 2:
        linhas = tabela.strip().splitlines()
        linhas_validas = [l for l in linhas if '|' in l and not re.match(r'^[|: -]+$', l.replace(" ", ""))]

        if len(linhas_validas) > 0:
            tabela_html = "<table class='itinerario-table'>"
            # Cabeçalho
            cabecalho_cells = [cell.strip() for cell in linhas_validas[0].split('|')][1:-1]
            tabela_html += "<thead><tr>"
            for cell in cabecalho_cells:
                tabela_html += f"<th>{cell}</th>"
            tabela_html += "</tr></thead>"
            
            # Corpo da tabela
            tabela_html += "<tbody>"
            for linha in linhas_validas[1:]:
                tabela_html += "<tr>"
                corpo_cells = [cell.strip() for cell in linha.split('|')][1:-1]
                for cell in corpo_cells:
                    tabela_html += f"<td>{cell}</td>"
                tabela_html += "</tr>"
            tabela_html += "</tbody></table>"
    
    html_content = f"""
    <html>
    <head>
        <meta charset="UTF-8">
        <style>
            body {{ font-family: 'Helvetica', 'Arial', sans-serif; margin: 2em; color: #333; }}
            h1 {{ color: #0056b3; }}
            .header-info {{ background-color: #f0f8ff; padding: 15px; border-radius: 8px; margin-bottom: 20px; }}
            .section-title {{ color: #d9534f; border-bottom: 1px solid #eee; padding-bottom: 5px; margin-top: 30px;}}
            .itinerario-table {{ width: 100%; border-collapse: collapse; margin-top: 15px; }}
            .itinerario-table th {{ background-color: #0056b3; color: white; padding: 10px; }}
            .itinerario-table td {{ padding: 8px; border-bottom: 1px solid #ddd; }}
            .footer {{ margin-top: 40px; text-align: center; font-size: 0.8em; color: #777; }}
        </style>
    </head>
    <body>
        <h1>Roteiro de Viagem: {destino}</h1>
        <div class="header-info">
            <p><strong>Período:</strong> {datas}</p>
        </div>
        <h2 class="section-title">Itinerário</h2>
        {tabela_html}
        <h2 class="section-title">Detalhes e Dicas</h2>
        <div>{descricao.replace('*', '').replace('**', '').replace('\n', '<br>')}</div>
        <div class="footer"><p>Gerado por vIAjante</p></div>
    </body>
    </html>
    """
    
    os.makedirs('arquivos', exist_ok=True)
    nome_arquivo = f"roteiro_{destino.lower()}_{session_id[:6]}.pdf"
    caminho = os.path.join('arquivos', nome_arquivo)
    HTML(string=html_content).write_pdf(caminho)
    return caminho