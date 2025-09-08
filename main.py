# main.py - VexusBot - Versão 100% Completa, Final, sem Omissões (com painel RAG, guardas e datas DD/MM a DD/MM)

import os
import re
import traceback
import sqlite3
import json
import time
from dotenv import load_dotenv
import google.generativeai as genai
import telebot
from telebot import types
from langchain_google_genai import GoogleGenerativeAIEmbeddings, ChatGoogleGenerativeAI
from langchain_community.vectorstores import FAISS
from langchain.prompts import PromptTemplate
from langchain.schema.runnable import RunnablePassthrough
from langchain.schema.output_parser import StrOutputParser
from telebot.apihelper import ApiTelegramException

# --- UTILS ---
from utils.pdf_generator import gerar_pdf
from utils.csv_generator import csv_generator

# --- Configuração ---
load_dotenv()
GEMINI_KEY = os.getenv("GEMINI_KEY")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")  # não usado neste modo (polling)

if not GEMINI_KEY or not TELEGRAM_TOKEN:
    print("ERRO CRÍTICO: Verifique suas chaves GEMINI_KEY e TELEGRAM_TOKEN no arquivo .env!")
    exit()

try:
    genai.configure(api_key=GEMINI_KEY)
    model = genai.GenerativeModel('gemini-1.5-flash')
    print("✅ Gemini configurado com sucesso!")
except Exception as e:
    print(f"❌ Erro na configuração do Gemini: {e}")
    exit()

# Importante: desativar concorrência para evitar reordenação de mensagens/estados
bot = telebot.TeleBot(TELEGRAM_TOKEN, num_threads=1)
print("✅ Bot do Telegram iniciado com sucesso!")

# --- INICIALIZAÇÃO DO RAG ---
rag_chain = None
try:
    llm = ChatGoogleGenerativeAI(model="gemini-1.5-flash", temperature=0.7, google_api_key=GEMINI_KEY)
    embeddings = GoogleGenerativeAIEmbeddings(model="models/embedding-001", google_api_key=GEMINI_KEY)
    vector_store = FAISS.load_local("faiss_index", embeddings, allow_dangerous_deserialization=True)
    retriever = vector_store.as_retriever(search_kwargs={"k": 3})

    template = """
    Você é o VexusBot. Use APENAS o CONTEÚDO FORNECIDO para responder à PERGUNTA.
    Se o conteúdo não for suficiente, responda exatamente: "Não encontrei essa dica específica no meu guia."

    CONTEÚDO: {context}
    PERGUNTA: {question}
    RESPOSTA:
    """
    prompt_template = PromptTemplate.from_template(template)

    rag_chain = (
        {"context": retriever, "question": RunnablePassthrough()}
        | prompt_template
        | llm
        | StrOutputParser()
    )
    print("✅ Sistema RAG com LangChain carregado com sucesso!")
except Exception as e:
    print(f"❌ Erro ao carregar o sistema RAG: {e}. A função de pergunta rápida pode não funcionar.")

# --- BANCO DE DADOS E MEMÓRIA ---
sessoes = {}

def inicializar_banco():
    conexao = sqlite3.connect('usuarios.db', check_same_thread=False)
    cursor = conexao.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS usuarios (
            id INTEGER PRIMARY KEY,
            chat_id TEXT UNIQUE NOT NULL,
            nome TEXT,
            idade INTEGER,
            acompanhantes TEXT,
            estilo_viagem TEXT,
            tipo_comida TEXT,
            interesses TEXT
        )
    ''')
    conexao.commit()
    conexao.close()
    print("🗄️ Banco de dados inicializado com sucesso!")

inicializar_banco()

_COLS_OK = {"nome", "idade", "acompanhantes", "estilo_viagem", "tipo_comida", "interesses"}

def salvar_preferencia(chat_id, coluna, valor):
    if coluna not in _COLS_OK:
        raise ValueError("Coluna inválida para salvar preferências.")
    conexao = sqlite3.connect('usuarios.db', check_same_thread=False)
    cursor = conexao.cursor()
    cursor.execute("INSERT OR IGNORE INTO usuarios (chat_id) VALUES (?)", (str(chat_id),))
    cursor.execute(f"UPDATE usuarios SET {coluna} = ? WHERE chat_id = ?", (valor, str(chat_id)))
    conexao.commit()
    conexao.close()

def carregar_preferencias(chat_id):
    conexao = sqlite3.connect('usuarios.db', check_same_thread=False)
    conexao.row_factory = sqlite3.Row
    cursor = conexao.cursor()
    cursor.execute("SELECT * FROM usuarios WHERE chat_id = ?", (str(chat_id),))
    resultado = cursor.fetchone()
    conexao.close()
    if resultado:
        return dict(resultado)
    return {}

# --- HELPERS ---
def _extrair_json_seguro(texto):
    """Remove cercas de código e extrai o primeiro JSON com regex não-gulosa."""
    if not texto:
        return None
    texto_limpo = re.sub(r"^```(?:json)?\s*|\s*```$", "", texto.strip(), flags=re.IGNORECASE | re.MULTILINE)
    m = re.search(r'\{.*?\}', texto_limpo, re.DOTALL)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except Exception:
        return None

def extrair_tabela(texto: str) -> str:
    """Extrai linhas estilo tabela Markdown do texto."""
    linhas_tabela = []
    for linha in texto.split('\n'):
        linha = linha.strip()
        if linha.startswith('|') and linha.count('|') > 2:
            if re.fullmatch(r'[|:\-\s]+', linha):
                continue
            linhas_tabela.append(linha)
    if not linhas_tabela:
        return ""
    return '\n'.join(linhas_tabela)

def formatar_tabela_para_telegram(tabela_markdown: str) -> str:
    """Gera uma tabela monoespaçada dentro de <pre>...</pre> (HTML), para evitar conflitos com Markdown."""
    if not tabela_markdown:
        return ""
    linhas = [l for l in tabela_markdown.strip().split('\n') if not re.fullmatch(r'[|:\-\s]+', l)]
    dados_tabela = [[cel.strip() for cel in linha.split('|') if cel.strip()] for linha in linhas if '|' in linha]
    if not dados_tabela:
        return ""
    try:
        num_colunas_header = len(dados_tabela[0])
        larguras = [0] * num_colunas_header
        for linha in dados_tabela:
            for i, celula in enumerate(linha):
                if i < num_colunas_header and len(celula) > larguras[i]:
                    larguras[i] = len(celula)
        tabela_formatada = ""
        for i, linha in enumerate(dados_tabela):
            while len(linha) < num_colunas_header:
                linha.append("")
            linha_formatada = [celula.ljust(larguras[j]) for j, celula in enumerate(linha[:num_colunas_header])]
            tabela_formatada += "  ".join(linha_formatada) + "\n"
            if i == 0:
                separador = ["-" * larguras[j] for j in range(num_colunas_header)]
                tabela_formatada += "  ".join(separador) + "\n"
        return f"<pre>{tabela_formatada}</pre>"
    except IndexError:
        return f"<pre>{tabela_markdown}</pre>"

def _parse_mode_para_resposta(texto: str) -> str:
    """Usa HTML quando houver <pre> (tabelas), senão Markdown."""
    return 'HTML' if '<pre>' in (texto or '') else 'Markdown'

def _safe_edit_message_text(chat_id: int, message_id: int, text: str, reply_markup=None, parse_mode: str | None=None):
    """
    Edita o texto da mensagem ancorada. Se o Telegram responder 'message is not modified',
    reaplica com um caractere invisível para forçar alteração. Em último caso, envia nova msg.
    """
    try:
        bot.edit_message_text(text, chat_id, message_id, reply_markup=reply_markup, parse_mode=parse_mode)
        return message_id
    except ApiTelegramException as e:
        msg = str(e)
        if "message is not modified" in msg:
            # alterna entre dois invisíveis para garantir mudança real
            flip = sessoes.get(chat_id, {}).get('_zws_flip', False)
            zws = '\u2063' if not flip else '\u2062'  # INVISIBLE SEPARATOR / INVISIBLE TIMES
            sessoes.setdefault(chat_id, {})['_zws_flip'] = not flip
            try:
                bot.edit_message_text(text + zws, chat_id, message_id, reply_markup=reply_markup, parse_mode=parse_mode)
                return message_id
            except ApiTelegramException:
                # fallback final: manda uma nova mensagem e usa ela como nova âncora
                new = bot.send_message(chat_id, text, reply_markup=reply_markup, parse_mode=parse_mode)
                return new.message_id
        else:
            # outros erros: propaga
            raise

def _sig_markup(markup: types.InlineKeyboardMarkup | None) -> tuple:
    """
    Gera uma assinatura imutável do reply_markup para comparações.
    Considera textos e callback_data dos botões.
    """
    if not markup or not getattr(markup, 'keyboard', None):
        return ()
    sig = []
    for row in markup.keyboard:
        row_sig = []
        for btn in row:
            row_sig.append((getattr(btn, 'text', ''), getattr(btn, 'callback_data', None)))
        sig.append(tuple(row_sig))
    return tuple(sig)

TELEGRAM_SAFE_LIMIT = 3900  # margem de segurança < 4096

def _split_text_for_telegram(text: str, limit: int = TELEGRAM_SAFE_LIMIT, is_html: bool = False) -> list[str]:
    """
    Divide um texto longo em pedaços <= limit, tentando não quebrar no meio de blocos <pre>...</pre>
    e preferindo quebras em linhas/parágrafos.
    """
    if not text:
        return [""]

    parts: list[str] = []

    if is_html:
        # Se HTML, separamos blocos <pre>...</pre> do restante para não corromper tags.
        tokens = []
        idx = 0
        for m in re.finditer(r'(?is)<pre>.*?<\/pre>', text):
            if m.start() > idx:
                tokens.append(("text", text[idx:m.start()]))
            tokens.append(("pre", m.group(0)))
            idx = m.end()
        if idx < len(text):
            tokens.append(("text", text[idx:]))

        for kind, payload in tokens:
            if kind == "pre":
                # bloco <pre> vai sozinho; se maior que o limite, fazemos split bruto por linhas
                if len(payload) <= limit:
                    parts.append(payload)
                else:
                    # divide conteúdo do pre mantendo tags de abertura/fecho
                    inner = payload[5:-6]  # remove <pre> e </pre>
                    lines = inner.splitlines(keepends=True)
                    buff = ""
                    for ln in lines:
                        if len(buff) + len(ln) > (limit - len("<pre></pre>")):
                            parts.append(f"<pre>{buff}</pre>")
                            buff = ""
                        buff += ln
                    if buff:
                        parts.append(f"<pre>{buff}</pre>")
            else:
                # texto comum em HTML
                segments = _smart_split(payload, limit)
                parts.extend(segments)
    else:
        # Markdown/plain
        parts = _smart_split(text, limit)

    return [p for p in parts if p and p.strip()]

def _smart_split(payload: str, limit: int) -> list[str]:
    """
    Divide respeitando quebras por parágrafos/linhas, com fallback em regiões menores.
    """
    chunks: list[str] = []
    for block in re.split(r'(\n{2,})', payload):  # mantém separadores de parágrafo
        if not block:
            continue
        if len(block) <= limit:
            chunks.append(block)
            continue
        # Quebra por linhas
        acc = ""
        for line in block.splitlines(keepends=True):
            if len(acc) + len(line) > limit:
                if acc:
                    chunks.append(acc)
                    acc = ""
                # Linha sozinha maior que limite -> hard split
                while len(line) > limit:
                    chunks.append(line[:limit])
                    line = line[limit:]
            acc += line
        if acc:
            chunks.append(acc)
    return chunks

def send_long_message(chat_id: int, text: str, parse_mode: str | None = None, reply_to_message_id: int | None = None):
    """
    Envia 'text' dividido em partes que cabem no Telegram. A primeira pode ser reply,
    as demais seguem como mensagens normais.
    """
    is_html = (parse_mode or "").upper() == "HTML"
    pieces = _split_text_for_telegram(text, TELEGRAM_SAFE_LIMIT, is_html=is_html)
    sent = None
    for i, piece in enumerate(pieces):
        if i == 0:
            sent = bot.send_message(chat_id, piece, parse_mode=parse_mode, reply_to_message_id=reply_to_message_id)
        else:
            sent = bot.send_message(chat_id, piece, parse_mode=parse_mode)
    return sent


# === Formato de datas esperado ===
DATE_FORMAT_HELP = "Por favor, informe as datas no formato: *DD/MM a DD/MM* (ex.: *10/07 a 18/07*)."

def _zero2(n: str) -> str:
    try:
        return f"{int(n):02d}"
    except Exception:
        return n

def parse_intervalo_datas(texto: str) -> dict | None:
    """
    Extrai intervalo nos formatos:
      - DD/MM a DD/MM
      - DD a DD/MM  (assume mesmo mês do segundo)
    Retorna {'inicio':'DD/MM','fim':'DD/MM','texto_norm':'DD/MM a DD/MM'} ou None.
    """
    t = (texto or "").strip()

    # DD/MM a DD/MM
    m1 = re.search(r'(?i)\b(\d{1,2})[\/\-.](\d{1,2})\s*(?:a|até|ate|–|-|—)\s*(\d{1,2})[\/\-.](\d{1,2})\b', t)
    if m1:
        d1, m_1, d2, m_2 = _zero2(m1.group(1)), _zero2(m1.group(2)), _zero2(m1.group(3)), _zero2(m1.group(4))
        if 1 <= int(d1) <= 31 and 1 <= int(d2) <= 31 and 1 <= int(m_1) <= 12 and 1 <= int(m_2) <= 12:
            inicio = f"{d1}/{m_1}"
            fim    = f"{d2}/{m_2}"
            return {"inicio": inicio, "fim": fim, "texto_norm": f"{inicio} a {fim}"}

    # DD a DD/MM
    m2 = re.search(r'(?i)\b(\d{1,2})\s*(?:a|até|ate|–|-|—)\s*(\d{1,2})[\/\-.](\d{1,2})\b', t)
    if m2:
        d1, d2, m_ = _zero2(m2.group(1)), _zero2(m2.group(2)), _zero2(m2.group(3))
        if 1 <= int(d1) <= 31 and 1 <= int(d2) <= 31 and 1 <= int(m_) <= 12:
            inicio = f"{d1}/{m_}"
            fim    = f"{d2}/{m_}"
            return {"inicio": inicio, "fim": fim, "texto_norm": f"{inicio} a {fim}"}

    return None

# --- IA ---
def analisar_resposta_data(texto_usuario: str, destino: str) -> dict:
    prompt = f"""
    O assistente perguntou as datas para uma viagem a {destino}.
    O usuário respondeu: "{texto_usuario}".
    Analise a resposta e classifique-a em 'data_fornecida', 'pergunta_sobre_data' ou 'indefinido'.
    Extraia o valor da data se aplicável (ex: '10 a 20 de dezembro').
    Responda APENAS com um JSON. Ex: {{"classificacao": "pergunta_sobre_data", "valor": "melhor época"}}
    """
    try:
        response = model.generate_content(prompt)
        data = _extrair_json_seguro(response.text)
        return data if data else {"classificacao": "indefinido"}
    except Exception as e:
        print(f"ERRO AO ANALISAR RESPOSTA DE DATA: {e}")
        return {"classificacao": "indefinido"}

def analisar_mensagem_geral(texto_usuario: str) -> str:
    """Usa a IA para entender a intenção de uma mensagem fora de um fluxo."""
    prompt = f"""
    Analise a mensagem do usuário e classifique a intenção em uma das seguintes categorias:
    - 'saudacao': Se for um cumprimento como 'oi', 'olá', 'bom dia', 'eai', 'tudo bem'.
    - 'pedido_de_ajuda': Se o usuário pedir o menu, ajuda ou opções.
    - 'desconhecido': Para qualquer outra coisa.

    Mensagem: "{texto_usuario}"
    Responda APENAS com um JSON contendo a chave "intencao". Ex: {{"intencao": "saudacao"}}
    """
    try:
        response = model.generate_content(prompt)
        data = _extrair_json_seguro(response.text)
        return data.get("intencao", "desconhecido") if data else "desconhecido"
    except Exception:
        return "desconhecido"

# --- CÉREBRO DO BOT (MÁQUINA DE ESTADOS) ---
def processar_mensagem(session_id: int, texto: str, nome_usuario: str) -> str | None:
    global sessoes
    if not sessoes.get(session_id) or not sessoes[session_id].get('estado'):
        return None

    estado = sessoes[session_id]['estado']
    dados_usuario = sessoes[session_id]['dados']

    if estado == "AGUARDANDO_CONFIRMACAO_FINAL":
        texto_normalizado = texto.strip().lower()
        if 'nao' in texto_normalizado or 'não' in texto_normalizado:
            sessoes.pop(session_id, None)  # Limpa o estado
            handle_start(None, chat_id=session_id, nome_usuario=nome_usuario, is_returning=True)
            return None
        else:
            sessoes.pop(session_id, None)
            handle_start(None, chat_id=session_id, nome_usuario=nome_usuario)
            return None

    if estado == "AGUARDANDO_PERGUNTA_RAG":
        sessoes[session_id]['estado'] = 'PERGUNTA_RESPONDIDA'
        if rag_chain:
            bot.send_chat_action(session_id, 'typing')
            return rag_chain.invoke(texto)
        else:
            return "Desculpe, meu sistema de consulta especialista está offline."

    if estado == "AGUARDANDO_DESTINO":
        sessoes[session_id]['dados']['destino'] = texto.strip().title()
        sessoes[session_id]['estado'] = "AGUARDANDO_DATAS"
        return (f"✈️ *{dados_usuario['destino']}* é uma ótima escolha!\n"
                f"Agora me conta: *quando* você vai viajar?\n\n{DATE_FORMAT_HELP}")

    elif estado == "AGUARDANDO_DATAS":
        # 1) parsing local no formato fixo
        pars = parse_intervalo_datas(texto)
        if pars:
            dados_usuario["datas"] = pars["texto_norm"]  # normalizado: "DD/MM a DD/MM"
            sessoes[session_id]['estado'] = "AGUARDANDO_ORCAMENTO"
            return "Anotado! Agora, qual o seu orçamento total?"

        # 2) fallback: usuário perguntou sobre época
        analise = analisar_resposta_data(texto, dados_usuario.get('destino', 'esse destino'))
        classificacao = analise.get('classificacao')

        if classificacao == 'pergunta_sobre_data':
            bot.send_chat_action(session_id, 'typing')
            prompt_resposta = (f"Responda à pergunta de um viajante sobre o melhor período para ir para "
                               f"{dados_usuario.get('destino', 'esse lugar')}: '{texto}'")
            response = model.generate_content(prompt_resposta)
            return f"{response.text}\n\n{DATE_FORMAT_HELP}"

        # 3) não entendi: reforçar formato exigido
        return f"Desculpe, não entendi as datas.\n{DATE_FORMAT_HELP}"

    elif estado == "AGUARDANDO_ORCAMENTO":
        dados_usuario["orcamento"] = texto.strip()
        sessoes[session_id]['estado'] = "GERANDO_ROTEIRO"
        return "Perfeito! Orçamento salvo. Estou preparando seu roteiro... Me envie um `ok` para continuar."

    elif estado == "GERANDO_ROTEIRO":
        try:
            bot.send_chat_action(session_id, 'typing')
            preferencias = carregar_preferencias(session_id)
            contexto = f"Perfil: Estilo: {preferencias.get('estilo_viagem', 'geral')}, Interesses: {preferencias.get('interesses', 'variados')}"
            prompt = (f"Crie um roteiro de viagem detalhado para {dados_usuario['destino']} de {dados_usuario['datas']} "
                      f"com orçamento de {dados_usuario['orcamento']}. {contexto}. Inclua uma tabela Markdown com colunas DATA, DIA, LOCAL.")

            response = model.generate_content(prompt)
            resposta_completa = response.text
            tabela_bruta = extrair_tabela(resposta_completa)

            dados_usuario.update({
                'tabela_itinerario': tabela_bruta,
                'descricao_detalhada': resposta_completa.replace(tabela_bruta, "").strip()
            })
            sessoes[session_id]['estado'] = 'ROTEIRO_GERADO'

            resumo_formatado = formatar_tabela_para_telegram(tabela_bruta) if tabela_bruta else "**Não foi possível extrair um resumo em tabela.**"
            return f"🎉 *Prontinho!* Seu roteiro personalizado está pronto:\n\n{resumo_formatado}"
        except Exception as e:
            traceback.print_exc()
            return "❌ Opa! Tive um problema ao gerar o roteiro. Vamos recomeçar?"

    elif estado == "AGUARDANDO_SUGESTAO":
        sessoes.pop(session_id, None)
        prompt = f"Sugira um destino na Europa para alguém que gosta de '{texto}'."
        bot.send_chat_action(session_id, 'typing')
        response = model.generate_content(prompt)
        handle_start(None, chat_id=session_id, nome_usuario=nome_usuario, is_returning=True)
        return response.text

    elif estado == "AGUARDANDO_PERGUNTA":
        sessoes.pop(session_id, None)
        prompt = f"Responda a seguinte pergunta sobre viagens: '{texto}'"
        bot.send_chat_action(session_id, 'typing')
        response = model.generate_content(prompt)
        handle_start(None, chat_id=session_id, nome_usuario=nome_usuario, is_returning=True)
        return response.text

    return "Desculpe, não entendi. Por favor, escolha uma opção no menu ou use /start para recomeçar."

# --- MENUS (principal e RAG) ---
def enviar_menu_principal(chat_id: int, nome_usuario: str, texto_saudacao: str, message_to_edit=None):
    markup = types.InlineKeyboardMarkup(row_width=1)
    b1 = types.InlineKeyboardButton("✈️ Planejar Roteiro", callback_data="menu_planejar")
    b2 = types.InlineKeyboardButton("👤 Ver Meu Perfil", callback_data="menu_ver_perfil")
    b3 = types.InlineKeyboardButton("✍️ Criar/Atualizar Perfil", callback_data="menu_perfil")
    b4 = types.InlineKeyboardButton("🧑🏻‍💻 Pergunta Rápida", callback_data="menu_pergunta")
    b5 = types.InlineKeyboardButton("❓ Como Funciona?", callback_data="menu_ajuda")
    markup.add(b1, b2, b3, b4, b5)

    texto_final = f"{texto_saudacao}\n\nComo posso te ajudar?"
    if message_to_edit:
        _safe_edit_message_text(chat_id, message_to_edit.message_id, texto_final, reply_markup=markup, parse_mode="Markdown")
    else:
        bot.send_message(chat_id, texto_final, reply_markup=markup, parse_mode="Markdown")

# ====== NOVO: Painel RAG ======
def enviar_rag_prompt(chat_id: int, anchor_message_id: int | None = None):
    """Mostra o 'painel RAG' pedindo a pergunta, com botão para voltar ao menu."""
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(types.InlineKeyboardButton("⬅️ Voltar ao Menu", callback_data="voltar_menu"))

    base_texto = "🔎 *Pergunta Rápida ativa*\n\nDigite sua pergunta que vou consultar meu guia de viagens."
    parse_mode = "Markdown"

    # Assinatura alvo (texto sem zws + markup)
    alvo_sig = (base_texto, _sig_markup(markup))

    # Estado salvo da âncora anterior
    sess = sessoes.setdefault(chat_id, {})
    last_sig = sess.get('rag_anchor_sig')

    if anchor_message_id:
        # Se assinatura é igual, já enviamos com um ZWS para forçar alteração
        if last_sig == alvo_sig:
            flip = sess.get('_zws_flip', False)
            zws = '\u2063' if not flip else '\u2062'
            sess['_zws_flip'] = not flip
            texto_para_enviar = base_texto + zws
        else:
            texto_para_enviar = base_texto

        try:
            bot.edit_message_text(texto_para_enviar, chat_id, anchor_message_id,
                                  reply_markup=markup, parse_mode=parse_mode)
            new_id = anchor_message_id
        except ApiTelegramException as e:
            # Se mesmo assim o Telegram disser que "não modificou", cria nova mensagem
            if "message is not modified" in str(e):
                msg = bot.send_message(chat_id, base_texto, reply_markup=markup, parse_mode=parse_mode)
                new_id = msg.message_id
            else:
                raise
    else:
        msg = bot.send_message(chat_id, base_texto, reply_markup=markup, parse_mode=parse_mode)
        new_id = msg.message_id

    # Atualiza âncora e assinatura para próximas edições
    sess.update({
        "rag_anchor_id": new_id,
        "rag_anchor_sig": alvo_sig,  # guardamos a assinatura-alvo (sem zws)
    })

def enviar_rag_pos_resposta(chat_id: int):
    """Depois de responder, mostra ação de continuar no RAG ou voltar ao menu."""
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("➕ Fazer outra pergunta", callback_data="rag_nova_pergunta"),
        types.InlineKeyboardButton("⬅️ Voltar ao Menu", callback_data="voltar_menu"),
    )
    bot.send_message(chat_id, "Quer fazer mais alguma pergunta específica?", reply_markup=markup)

def enviar_menu_pos_roteiro(chat_id: int, message_to_edit=None):
    markup = types.InlineKeyboardMarkup(row_width=2)
    b1 = types.InlineKeyboardButton("📄 Gerar PDF", callback_data="gerar_pdf")
    b2 = types.InlineKeyboardButton("📊 Gerar CSV", callback_data="gerar_csv")
    b3 = types.InlineKeyboardButton("✈️ Voltar ao Menu", callback_data="voltar_menu")
    markup.add(b1, b2, b3)

    texto = "O que mais você gostaria de fazer?"

    if message_to_edit:
        # Usa o helper que evita "message is not modified" e faz fallback se necessário
        _safe_edit_message_text(chat_id, message_to_edit.message_id, texto, reply_markup=markup)
    else:
        bot.send_message(chat_id, texto, reply_markup=markup)

# --- HANDLERS ---
@bot.message_handler(commands=['start', 'help', 'iniciar'])
def handle_start(message=None, chat_id: int | None=None, nome_usuario: str | None=None, is_returning=False):
    global sessoes
    session_id = message.chat.id if message else int(chat_id)
    nome = message.from_user.first_name if message else nome_usuario
    sessoes[session_id] = {'estado': None, 'dados': {}, 'modo': None, 'rag_anchor_id': None, 'rag_anchor_sig': None}
    salvar_preferencia(session_id, 'nome', nome)
    texto_saudacao = f"Ok, de volta ao menu principal, {nome}!" if is_returning else f"🌟 Olá, {nome}! Eu sou o VexusBot."
    enviar_menu_principal(session_id, nome, texto_saudacao)

@bot.message_handler(commands=['ajuda'])
def handle_ajuda(message: telebot.types.Message):
    texto_ajuda = """
Olá! Eu sou o VexusBot, seu assistente de viagens com IA.

1️⃣ */perfil* ou *Criar/Atualizar Perfil*
Use esta opção para me contar sobre seus interesses. Você pode selecionar múltiplas opções para roteiros mais personalizados!

2️⃣ *Planejar um Roteiro*
Escolha esta opção no menu para começar. Eu te guiarei pelo processo, e você pode até me fazer perguntas no meio do caminho, como "qual a melhor época para ir?".

Para recomeçar a qualquer momento, use /start.
"""
    bot.reply_to(message, texto_ajuda, parse_mode='Markdown')

@bot.callback_query_handler(func=lambda call: True)
def handle_callback_query(call: types.CallbackQuery):
    global sessoes
    session_id = call.message.chat.id
    nome_usuario = call.from_user.first_name

    bot.answer_callback_query(call.id)

    if call.data == "menu_pergunta":
        # Entra no modo RAG
        sessoes[session_id] = {'estado': 'AGUARDANDO_PERGUNTA_RAG', 'dados': {}, 'modo': 'RAG', 'rag_anchor_id': None, 'rag_anchor_sig': None}
        enviar_rag_prompt(session_id, anchor_message_id=call.message.message_id)

    elif call.data == "rag_nova_pergunta":
        anchor = sessoes.get(session_id, {}).get('rag_anchor_id')
        sessoes[session_id].update({'estado': 'AGUARDANDO_PERGUNTA_RAG', 'modo': 'RAG'})
        if anchor:
            enviar_rag_prompt(session_id, anchor_message_id=anchor)
        else:
            enviar_rag_prompt(session_id)
        bot.send_message(session_id, "Claro! Pode perguntar — estou aqui para tirar suas dúvidas. 🙂")

    elif call.data == "voltar_menu":
        # Sai do modo RAG explicitamente
        sessoes[session_id].update({'estado': None, 'modo': None, 'rag_anchor_id': None, 'rag_anchor_sig': None})
        texto_saudacao = f"Ok, {nome_usuario}!"
        enviar_menu_principal(session_id, nome_usuario, texto_saudacao, message_to_edit=call.message)

    elif call.data == "menu_ver_perfil":
        preferencias = carregar_preferencias(session_id)
        if not preferencias or not (preferencias.get('estilo_viagem') or preferencias.get('interesses')):
            texto = "Você ainda não criou seu perfil de viajante."
            markup = types.InlineKeyboardMarkup()
            markup.add(types.InlineKeyboardButton("✍️ Criar Meu Perfil Agora", callback_data="menu_perfil"))
            bot.edit_message_text(texto, session_id, call.message.message_id, reply_markup=markup)
            return
        texto_perfil = (f"*Seu Perfil de Viajante* 👤\n\n"
                        f"- *Nome:* {preferencias.get('nome', 'Não informado')}\n"
                        f"- *Estilo de Viagem:* {preferencias.get('estilo_viagem', 'Não informado')}\n"
                        f"- *Interesses:* {preferencias.get('interesses', 'Não informado')}")
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("⬅️ Voltar ao Menu", callback_data="voltar_menu"))
        bot.edit_message_text(texto_perfil, session_id, call.message.message_id, reply_markup=markup, parse_mode="Markdown")

    elif call.data == "menu_ajuda":
        texto_ajuda = """Olá! Eu sou o VexusBot, seu co-piloto de viagens! ✈️

Aqui está um resumo do que podemos fazer juntos:

✈️ ***Planejar Roteiro***
Começamos do zero a planejar sua próxima aventura.

👤 ***Meu Perfil***
Me conte sobre seus gostos para roteiros personalizados.

💡 ***Sugerir um Destino***
Está em dúvida para onde ir? Me diga o que você procura!

Para voltar a este menu, basta usar o comando /start."""
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("⬅️ Voltar ao Menu", callback_data="voltar_menu"))
        bot.edit_message_text(texto_ajuda, session_id, call.message.message_id, reply_markup=markup, parse_mode="Markdown")

    elif call.data == "menu_planejar":
        sessoes[session_id] = {'estado': 'AGUARDANDO_DESTINO', 'dados': {}, 'modo': None, 'rag_anchor_id': None, 'rag_anchor_sig': None}
        bot.edit_message_text("Ótima escolha! Para qual cidade ou país você quer um roteiro?", session_id, call.message.message_id)

    elif call.data == "menu_sugerir":
        sessoes[session_id] = {'estado': 'AGUARDANDO_SUGESTAO', 'dados': {}, 'modo': None, 'rag_anchor_id': None, 'rag_anchor_sig': None}
        bot.edit_message_text("Claro! Me diga o que você procura em uma viagem (ex: 'praia e sol').", session_id, call.message.message_id)

    elif call.data == "menu_perfil":
        interesses_salvos = carregar_preferencias(session_id).get('interesses', '')
        selecoes_atuais = [i.strip() for i in interesses_salvos.split(',') if i.strip()]
        sessoes[session_id] = {'estado': 'BRIEFING_INTERESSES', 'selecoes_interesses': selecoes_atuais, 'dados': {}, 'modo': None, 'rag_anchor_id': None, 'rag_anchor_sig': None}
        markup = types.InlineKeyboardMarkup(row_width=2)
        opcoes = ["Museus", "Natureza", "Vida Noturna", "Gastronomia"]
        botoes = [types.InlineKeyboardButton(f"✅ {opt}" if opt in selecoes_atuais else opt, callback_data=f"briefing_selecionar_{opt}") for opt in opcoes]
        markup.add(*botoes)
        markup.add(types.InlineKeyboardButton("➡️ Concluir", callback_data="briefing_selecionar_concluir"))
        bot.edit_message_text("Vamos criar/atualizar seu perfil. Selecione seus interesses e clique em 'Concluir'.", session_id, call.message.message_id, reply_markup=markup)

    elif call.data.startswith("briefing_selecionar_"):
        valor = call.data.split('_', 2)[2]
        if 'selecoes_interesses' not in sessoes.get(session_id, {}):
            sessoes[session_id] = {'estado': 'BRIEFING_INTERESSES', 'selecoes_interesses': [], 'dados': {}, 'modo': None, 'rag_anchor_id': None, 'rag_anchor_sig': None}
        selecoes_atuais = sessoes[session_id]['selecoes_interesses']
        if valor == 'concluir':
            interesses_finais = ", ".join(selecoes_atuais)
            salvar_preferencia(session_id, 'interesses', interesses_finais)
            texto_final = f"Perfil salvo com os interesses: *{interesses_finais}*." if interesses_finais else "Perfil salvo!"
            enviar_menu_principal(session_id, nome_usuario, texto_final, message_to_edit=call.message)
            return
        if valor in selecoes_atuais:
            selecoes_atuais.remove(valor)
        else:
            selecoes_atuais.append(valor)
        markup = types.InlineKeyboardMarkup(row_width=2)
        opcoes = ["Museus", "Natureza", "Vida Noturna", "Gastronomia"]
        botoes = [types.InlineKeyboardButton(f"✅ {opt}" if opt in selecoes_atuais else opt, callback_data=f"briefing_selecionar_{opt}") for opt in opcoes]
        markup.add(*botoes)
        markup.add(types.InlineKeyboardButton("➡️ Concluir Seleção", callback_data="briefing_selecionar_concluir"))
        bot.edit_message_reply_markup(chat_id=session_id, message_id=call.message.message_id, reply_markup=markup)

    elif call.data in ["gerar_pdf", "gerar_csv"]:
        bot.send_chat_action(session_id, 'upload_document')
        tipo_arquivo = call.data.split('_')[1]
        dados = sessoes.get(session_id, {}).get('dados', {})

        # garantir tipos e defaults seguros
        destino_safe = (dados.get('destino') or 'roteiro')
        datas_safe   = (dados.get('datas') or '')
        tabela_safe  = (dados.get('tabela_itinerario') or '')
        desc_safe    = (dados.get('descricao_detalhada') or '')

        # utils usam slicing em session_id, assegurar string
        session_id_str = str(session_id)

        if tipo_arquivo == 'pdf':
            caminho_arquivo = gerar_pdf(
                destino=destino_safe,
                datas=datas_safe,
                tabela=tabela_safe,
                descricao=desc_safe,
                session_id=session_id_str,
            )
        else:
            caminho_arquivo = csv_generator(
                tabela=tabela_safe,
                session_id=session_id_str,
            )

        with open(caminho_arquivo, 'rb') as arquivo:
            bot.send_document(session_id, arquivo)
        os.remove(caminho_arquivo)
        enviar_menu_pos_roteiro(session_id, message_to_edit=call.message)

@bot.message_handler(func=lambda message: True)
def handle_messages(message: telebot.types.Message):
    global sessoes
    session_id = message.chat.id
    nome_usuario = message.from_user.first_name
    texto_normalizado = message.text.strip().lower()

    try:
        # 1) Guardas de obrigado
        palavras_agradecimento = ["obrigado", "obrigada", "valeu", "grato", "agradeço", "thanks", "obg"]
        if any(palavra in texto_normalizado for palavra in palavras_agradecimento):
            sessoes[session_id] = {
                'estado': 'AGUARDANDO_CONFIRMACAO_FINAL',
                'dados': {},
                'modo': None,
                'rag_anchor_id': sessoes.get(session_id, {}).get('rag_anchor_id'),
                'rag_anchor_sig': sessoes.get(session_id, {}).get('rag_anchor_sig')
            }
            bot.reply_to(message, f"De nada, {nome_usuario}! 😊 Fico feliz em ajudar. Posso te ajudar com mais alguma coisa?")
            return

        # 2) Estado/mode atuais
        estado_atual = sessoes.get(session_id, {}).get('estado')
        modo_atual = sessoes.get(session_id, {}).get('modo')

        # 3) Se estamos em modo RAG, garantimos o fluxo (mesmo que o estado tenha sido perdido)
        if modo_atual == 'RAG':
            if not estado_atual:
                sessoes.setdefault(session_id, {}).update({'estado': 'AGUARDANDO_PERGUNTA_RAG'})
            resposta = processar_mensagem(session_id, message.text, nome_usuario)
            if resposta:
                bot.reply_to(message, resposta, parse_mode=_parse_mode_para_resposta(resposta))
            # pós-resposta do RAG
            if sessoes.get(session_id, {}).get('estado') == 'PERGUNTA_RESPONDIDA':
                enviar_rag_pos_resposta(session_id)
            return

        # 4) Demais fluxos
        if estado_atual:
            resposta = processar_mensagem(session_id, message.text, nome_usuario)
            if resposta:
                bot.reply_to(message, resposta, parse_mode=_parse_mode_para_resposta(resposta))
            if sessoes.get(session_id, {}).get('estado') == 'ROTEIRO_GERADO':
                enviar_menu_pos_roteiro(session_id)
            elif sessoes.get(session_id, {}).get('estado') == 'PERGUNTA_RESPONDIDA':
                enviar_rag_pos_resposta(session_id)
            return

        # 5) Fora de fluxo e fora do modo RAG: decide entre saudação/menu
        intencao = analisar_mensagem_geral(message.text)
        if intencao == 'saudacao':
            texto_apresentacao = f"""
Olá, {nome_usuario}! Eu sou o VexusBot. ✈️

Sou seu assistente de viagens pessoal e uso inteligência artificial para te ajudar a planejar a viagem dos sonhos!

Posso *criar roteiros completos*, te dar *sugestões de destinos* ou até mesmo *criar um perfil de viajante* para que minhas sugestões sejam sempre perfeitas para você.

Para ver todas as opções, é só me pedir o menu ou usar o comando /start.
"""
            bot.reply_to(message, texto_apresentacao, parse_mode='Markdown')
        else:
            # Mostra o menu principal só quando não estamos em modo RAG
            handle_start(message)
        return

    except Exception as e:
        print(f"!!!!!!!!!! ERRO GERAL NO HANDLE: {e} !!!!!!!!!!")
        traceback.print_exc()
        bot.reply_to(message, "Desculpe, ocorreu um erro inesperado.")

# --- INICIA O BOT ---
print("VexusBot (Versão Avançada) em execução...")
while True:
    try:
        bot.infinity_polling(timeout=10, long_polling_timeout=5, skip_pending=True)
    except Exception as e:
        print(f"Erro de conexão/polling: {e}. Reiniciando em 15 segundos...")
        time.sleep(15)
