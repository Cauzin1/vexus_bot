from weasyprint import HTML
from datetime import datetime
import os
import re
import csv
import io
import html as htmlmod
import unicodedata


def _slugify(text: str) -> str:
    """Gera um slug seguro para nomes de arquivo."""
    if not text:
        return "roteiro"
    # remove acentos
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    # só letras, números, hífens e underscores
    text = re.sub(r"[^a-zA-Z0-9_\-]+", "-", text)
    text = re.sub(r"-{2,}", "-", text).strip("-").lower()
    return text or "roteiro"


def _parse_markdown_table(tabela_md: str) -> list[list[str]]:
    """
    Converte uma tabela Markdown em linhas/colunas.
    Ignora linhas de separador (---|:---).
    """
    if not tabela_md:
        return []

    linhas = tabela_md.strip().splitlines()
    linhas_validas = [
        l for l in linhas
        if "|" in l and not re.fullmatch(r"[|:\-\s]+", l.replace(" ", ""))
    ]
    if not linhas_validas:
        return []

    rows: list[list[str]] = []
    for linha in linhas_validas:
        # split mantendo apenas células (ignora extremidades vazias de pipes)
        cells = [c.strip() for c in linha.split("|")]
        # remove vazios de início/fim comuns em markdown
        if cells and cells[0] == "":
            cells = cells[1:]
        if cells and cells[-1] == "":
            cells = cells[:-1]
        # ignora linhas vazias
        if any(cells):
            rows.append(cells)
    return rows


def _parse_csv_like(texto: str) -> list[list[str]]:
    """
    Tenta parsear como CSV/TSV usando csv.Sniffer para detectar delimitador (vírgula, ponto e vírgula, tab, etc.).
    """
    if not texto:
        return []

    data = texto.strip()
    if not data:
        return []

    try:
        # tenta detectar delimitador
        sniffer = csv.Sniffer()
        dialect = sniffer.sniff(data, delimiters=",;\t|")
        reader = csv.reader(io.StringIO(data), dialect)
    except Exception:
        # fallback comum: vírgula
        reader = csv.reader(io.StringIO(data), delimiter=",")

    rows = [[c.strip() for c in row] for row in reader]
    # limpa linhas totalmente vazias
    rows = [r for r in rows if any(cell for cell in r)]
    return rows


def _rows_from_any_table_string(tabela: str) -> list[list[str]]:
    """
    Detecta se a string parece Markdown com pipes ou CSV-like e retorna rows.
    Prioriza Markdown quando há muitos pipes por linha.
    """
    if not tabela:
        return []
    # Heurística rápida: se houver muitas linhas com '|' é markdown
    md_score = sum(1 for l in tabela.splitlines() if l.count("|") >= 2)
    if md_score >= 2:
        rows = _parse_markdown_table(tabela)
        if rows:
            return rows
    # caso contrário tenta CSV-like
    rows = _parse_csv_like(tabela)
    return rows


def _html_table_from_rows(rows: list[list[str]]) -> str:
    """
    Converte rows em HTML <table>. Usa a primeira linha como cabeçalho.
    Escapa conteúdo das células para segurança.
    """
    if not rows:
        return ""

    # normalizar número de colunas (pega o máximo e completa as demais)
    max_cols = max(len(r) for r in rows)
    norm_rows = [r + [""] * (max_cols - len(r)) for r in rows]

    thead = norm_rows[0]
    tbody = norm_rows[1:] if len(norm_rows) > 1 else []

    # escape HTML
    def esc(x: str) -> str:
        return htmlmod.escape(x or "", quote=True)

    html_parts = []
    html_parts.append("<table class='itinerario-table'>")

    # thead
    html_parts.append("<thead><tr>")
    for cell in thead:
        html_parts.append(f"<th>{esc(cell)}</th>")
    html_parts.append("</tr></thead>")

    # tbody
    html_parts.append("<tbody>")
    for r in tbody:
        html_parts.append("<tr>")
        for c in r:
            html_parts.append(f"<td>{esc(c)}</td>")
        html_parts.append("</tr>")
    html_parts.append("</tbody>")

    html_parts.append("</table>")
    return "".join(html_parts)


def gerar_pdf(destino: str, datas: str, tabela: str, descricao: str, session_id: str) -> str:
    """
    Gera um PDF organizado com título, período, descrição e uma tabela (Markdown ou CSV/TSV) formatada.
    - destino: texto do destino
    - datas: intervalo (ex.: "10/07 a 18/07")
    - tabela: string em Markdown de tabela OU CSV/TSV
    - descricao: markdown/plano (será convertido para HTML básico)
    - session_id: string (usada para nomear arquivo)
    """
    destino_safe = destino or "Roteiro"
    destino_slug = _slugify(destino_safe)
    session_fragment = (session_id or "sess")[:6]

    # Monta rows a partir de markdown ou csv/tsv
    rows = _rows_from_any_table_string(tabela or "")
    tabela_html = _html_table_from_rows(rows) if rows else "<p><em>Sem itens estruturados.</em></p>"

    # Descrição: remover * e ** e converter quebras de linha
    descricao_html = htmlmod.escape((descricao or "").replace("**", "").replace("*", ""))
    descricao_html = descricao_html.replace("\n", "<br>")

    # HTML completo
    html_content = f"""
    <html>
    <head>
        <meta charset="UTF-8">
        <style>
            @page {{
                size: A4;
                margin: 24mm 18mm 24mm 18mm;
            }}
            body {{ font-family: 'Helvetica', 'Arial', sans-serif; color: #333; }}
            h1 {{ color: #0056b3; margin-bottom: 8px; }}
            .header-info {{ background-color: #f0f8ff; padding: 12px 14px; border-radius: 8px; margin: 0 0 18px 0; }}
            .header-info p {{ margin: 4px 0; }}
            .section-title {{ color: #d9534f; border-bottom: 1px solid #eee; padding-bottom: 6px; margin: 26px 0 10px 0; }}
            .itinerario-table {{ width: 100%; border-collapse: collapse; margin-top: 10px; table-layout: fixed; }}
            .itinerario-table th, .itinerario-table td {{
                padding: 8px 10px;
                border: 1px solid #ddd;
                word-wrap: break-word;
                overflow-wrap: anywhere;
                font-size: 11px;
            }}
            .itinerario-table th {{
                background-color: #0056b3;
                color: #fff;
                text-align: center;
            }}
            .itinerario-table tbody tr:nth-child(even) {{ background: #f9fbff; }}
            .itinerario-table tbody tr:nth-child(odd)  {{ background: #ffffff; }}
            .footer {{ margin-top: 28px; text-align: center; font-size: 0.8em; color: #777; }}
        </style>
    </head>
    <body>
        <h1>Roteiro de Viagem: {htmlmod.escape(destino_safe)}</h1>
        <div class="header-info">
            <p><strong>Período:</strong> {htmlmod.escape(datas or '')}</p>
            <p><strong>Gerado em:</strong> {datetime.now().strftime('%d/%m/%Y %H:%M')}</p>
        </div>

        <h2 class="section-title">Itinerário</h2>
        {tabela_html}

        <h2 class="section-title">Detalhes e Dicas</h2>
        <div>{descricao_html}</div>

        <div class="footer"><p>Gerado por vIAjante</p></div>
    </body>
    </html>
    """

    os.makedirs('arquivos', exist_ok=True)
    nome_arquivo = f"roteiro_{destino_slug}_{session_fragment}.pdf"
    caminho = os.path.join('arquivos', nome_arquivo)
    HTML(string=html_content).write_pdf(caminho)
    return caminho

