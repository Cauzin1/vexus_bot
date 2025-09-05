# main.py - VexusBot - Versão 100% Completa, Final e sem Omissões

import os
import re
import traceback
import sqlite3
import random
import json
import time
from datetime import datetime
from dotenv import load_dotenv
import google.generativeai as genai
import telebot
from telebot import types
from langchain_google_genai import GoogleGenerativeAIEmbeddings, ChatGoogleGenerativeAI
from langchain_community.vectorstores import FAISS
from langchain.prompts import PromptTemplate
from langchain.schema.runnable import RunnablePassthrough
from langchain.schema.output_parser import StrOutputParser
# --- UTILS ---
# Certifique-se de que a pasta 'utils' com estes arquivos está no seu projeto
from utils.pdf_generator import gerar_pdf
from utils.csv_generator import csv_generator
from utils.validators import remover_acentos

# --- Configuração ---
load_dotenv()
GEMINI_KEY = os.getenv("GEMINI_KEY")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")

if not GEMINI_KEY or not TELEGRAM_TOKEN:
    print("ERRO CRÍTICO: Verifique suas chaves GEMINI_KEY e TELEGRAM_TOKEN no arquivo .env!")
    exit()

try:
    genai.configure(api_key=GEMINI_KEY)
    model = genai.GenerativeModel('gemini-1.5-flash')
    print("✅ Gemini configurado com sucesso!")
except Exception as e:
    print(f"❌ Erro na configuração do Gemini: {e}"); exit()

bot = telebot.TeleBot(TELEGRAM_TOKEN)
print("✅ Bot do Telegram iniciado com sucesso!")


# --- SISTEMA RAG COM LANGCHAIN ---


# --- INICIALIZAÇÃO DO RAG ---
rag_chain = None
try:
    llm = ChatGoogleGenerativeAI(model="gemini-1.5-flash", temperature=0.7, google_api_key=GEMINI_KEY)
    embeddings = GoogleGenerativeAIEmbeddings(model="models/embedding-001", google_api_key=GEMINI_KEY)
    vector_store = FAISS.load_local("faiss_index", embeddings, allow_dangerous_deserialization=True)
    retriever = vector_store.as_retriever(search_kwargs={"k": 3})

    template = """
    Você é o VexusBot. Use APENAS o CONTEÚDO FORNECIDO para responder à PERGUNTA.
    Se o conteúdo não for suficiente, diga que não encontrou essa dica específica no seu guia.

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
            id INTEGER PRIMARY KEY, chat_id TEXT UNIQUE NOT NULL, nome TEXT,
            idade INTEGER, acompanhantes TEXT, estilo_viagem TEXT,
            tipo_comida TEXT, interesses TEXT
        )
    ''')
    conexao.commit(); conexao.close()
    print("🗄️ Banco de dados inicializado com sucesso!")
inicializar_banco()

def salvar_preferencia(chat_id, coluna, valor):
    conexao = sqlite3.connect('usuarios.db', check_same_thread=False)
    cursor = conexao.cursor()
    cursor.execute("INSERT OR IGNORE INTO usuarios (chat_id) VALUES (?)", (str(chat_id),))
    cursor.execute(f"UPDATE usuarios SET {coluna} = ? WHERE chat_id = ?", (valor, str(chat_id)))
    conexao.commit(); conexao.close()

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

# --- FUNÇÕES DE AJUDA E IA ---
def extrair_tabela(texto: str) -> str:
    linhas_tabela = []
    for linha in texto.split('\n'):
        linha = linha.strip()
        if linha.startswith('|') and linha.count('|') > 2:
            if re.match(r'^[|: -]+$', linha.replace(" ", "")): continue
            linhas_tabela.append(linha)
    if not linhas_tabela: return ""
    return '\n'.join(linhas_tabela)

def formatar_tabela_para_telegram(tabela_markdown: str) -> str:
    if not tabela_markdown: return ""
    linhas = [l for l in tabela_markdown.strip().split('\n') if not re.match(r'^[|: -]+$', l.replace(" ", ""))]
    dados_tabela = [[cel.strip() for cel in linha.split('|') if cel.strip()] for linha in linhas if '|' in linha]
    if not dados_tabela: return ""
    try:
        num_colunas_header = len(dados_tabela[0])
        larguras = [0] * num_colunas_header
        for linha in dados_tabela:
            for i, celula in enumerate(linha):
                if i < num_colunas_header and len(celula) > larguras[i]:
                    larguras[i] = len(celula)
        tabela_formatada = ""
        for i, linha in enumerate(dados_tabela):
            while len(linha) < num_colunas_header: linha.append("")
            linha_formatada = [celula.ljust(larguras[j]) for j, celula in enumerate(linha[:num_colunas_header])]
            tabela_formatada += "  ".join(linha_formatada) + "\n"
            if i == 0:
                separador = ["-" * larguras[j] for j in range(num_colunas_header)]
                tabela_formatada += "  ".join(separador) + "\n"
        return f"```\n{tabela_formatada}```"
    except IndexError:
        return tabela_markdown

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
        json_text = re.search(r'\{.*\}', response.text, re.DOTALL).group(0)
        return json.loads(json_text)
    except Exception as e:
        print(f"ERRO AO ANALISAR RESPOSTA DE DATA: {e}")
        return {"classificacao": "indefinido"}

# --- CÉREBRO DO BOT (MÁQUINA DE ESTADOS) ---
def processar_mensagem(session_id: str, texto: str, nome_usuario: str) -> str:
    global sessoes
    if not sessoes.get(session_id) or not sessoes[session_id].get('estado'):
        return None

    estado = sessoes[session_id]['estado']

    if estado == "AGUARDANDO_CONFIRMACAO_FINAL":
        texto_normalizado = texto.strip().lower()
        if 'nao' in texto_normalizado or 'não' in texto_normalizado:
            sessoes.pop(session_id, None) # Limpa o estado
            handle_start(None, chat_id=session_id, nome_usuario=nome_usuario, is_returning=True)
            return None # Nenhuma mensagem de texto, pois o menu será enviado
        else:
            sessoes.pop(session_id, None) # Limpa o estado
            handle_start(None, chat_id=session_id, nome_usuario=nome_usuario)
            return None
    
    if estado == "AGUARDANDO_PERGUNTA_RAG":
        sessoes.pop(session_id, None) # Limpa o estado
        if rag_chain:
            bot.send_chat_action(session_id, 'typing')
            resposta = rag_chain.invoke(texto)
            #handle_start(None, chat_id=session_id, nome_usuario=nome_usuario, is_returning=True)
            return resposta
        else:
            return "Desculpe, meu sistema de consulta especialista está offline no momento."
            
    
    if estado == "AGUARDANDO_DESTINO":
        sessoes[session_id]['dados']['destino'] = texto.strip().title()
        sessoes[session_id]['estado'] = "AGUARDANDO_DATAS"
        return f"✈️ *{dados_usuario['destino']}* é uma ótima escolha!\nAgora me conta: *quando* você vai viajar?"

    elif estado == "AGUARDANDO_DATAS":
        analise = analisar_resposta_data(texto, dados_usuario.get('destino', 'esse destino'))
        classificacao = analise.get('classificacao')
        
        if classificacao == 'data_fornecida':
            dados_usuario["datas"] = analise.get('valor', texto)
            sessoes[session_id]['estado'] = "AGUARDANDO_ORCAMENTO"
            return f"Anotado! Agora, qual o seu orçamento total?"
        elif classificacao == 'pergunta_sobre_data':
            bot.send_chat_action(session_id, 'typing')
            prompt_resposta = f"Responda à pergunta de um viajante sobre o melhor período para ir para {dados_usuario.get('destino', 'esse lugar')}: '{texto}'"
            response = model.generate_content(prompt_resposta)
            return f"{response.text}\n\nSabendo disso, para quando gostaria de marcar sua viagem?"
        else:
            return "Desculpe, não entendi sua resposta sobre as datas. Por favor, me diga um período."
            
    elif estado == "AGUARDANDO_ORCAMENTO":
        dados_usuario["orcamento"] = texto.strip()
        sessoes[session_id]['estado'] = "GERANDO_ROTEIRO"
        return f"Perfeito! Orçamento salvo. Estou preparando seu roteiro... Me envie um `ok` para continuar."

    elif estado == "GERANDO_ROTEIRO":
        try:
            bot.send_chat_action(session_id, 'typing')
            preferencias = carregar_preferencias(session_id)
            contexto = f"Perfil: Estilo: {preferencias.get('estilo_viagem', 'geral')}, Interesses: {preferencias.get('interesses', 'variados')}"
            prompt = (f"Crie um roteiro de viagem detalhado para {dados_usuario['destino']} de {dados_usuario['datas']} com orçamento de {dados_usuario['orcamento']}. {contexto}. Inclua uma tabela Markdown com colunas DATA, DIA, LOCAL.")
            
            response = model.generate_content(prompt)
            resposta_completa = response.text
            tabela_bruta = extrair_tabela(resposta_completa)
            
            dados_usuario.update({'tabela_itinerario': tabela_bruta, 'descricao_detalhada': resposta_completa.replace(tabela_bruta, "").strip()})
            sessoes[session_id]['estado'] = 'ROTEIRO_GERADO'
            
            resumo_formatado = formatar_tabela_para_telegram(tabela_bruta) if tabela_bruta else "**Não foi possível extrair um resumo em tabela.**"
            return f"🎉 *Prontinho!* Seu roteiro personalizado está pronto:\n\n{resumo_formatado}"
        except Exception as e:
            traceback.print_exc(); return "❌ Opa! Tive um problema ao gerar o roteiro. Vamos recomeçar?"
    
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

# --- FUNÇÕES DE MENU E HANDLERS ---
def enviar_menu_principal(chat_id, nome_usuario, texto_saudacao, message_to_edit=None):
    markup = types.InlineKeyboardMarkup(row_width=1)
    b1 = types.InlineKeyboardButton("✈️ Planejar Roteiro", callback_data="menu_planejar")
    b2 = types.InlineKeyboardButton("👤 Ver Meu Perfil", callback_data="menu_ver_perfil")
    b3 = types.InlineKeyboardButton("✍️ Criar/Atualizar Perfil", callback_data="menu_perfil")
    b4 = types.InlineKeyboardButton("❓ Pergunta Rápida", callback_data="menu_pergunta")
    b5 = types.InlineKeyboardButton("❓ Como Funciona?", callback_data="menu_ajuda")
    markup.add(b1, b2, b3, b4, b5)
    
    texto_final = f"{texto_saudacao}\n\nComo posso te ajudar?"
    if message_to_edit:
        bot.edit_message_text(texto_final, chat_id, message_to_edit.message_id, reply_markup=markup, parse_mode="Markdown")
    else:
        bot.send_message(chat_id, texto_final, reply_markup=markup, parse_mode="Markdown")

def enviar_menu_pos_roteiro(chat_id, message_to_edit=None):
    markup = types.InlineKeyboardMarkup(row_width=2)
    b1 = types.InlineKeyboardButton("📄 Gerar PDF", callback_data="gerar_pdf")
    b2 = types.InlineKeyboardButton("📊 Gerar CSV", callback_data="gerar_csv")
    b3 = types.InlineKeyboardButton("✈️ Voltar ao Menu", callback_data="voltar_menu")
    markup.add(b1, b2, b3)

    texto = "O que mais você gostaria de fazer?"
    if message_to_edit:
        bot.edit_message_text(texto, chat_id, message_to_edit.message_id, reply_markup=markup)
    else:
        bot.send_message(chat_id, texto, reply_markup=markup)

@bot.message_handler(commands=['start', 'help', 'iniciar'])
def handle_start(message=None, chat_id=None, nome_usuario=None, is_returning=False):
    global sessoes
    session_id = str(message.chat.id if message else chat_id)
    nome = message.from_user.first_name if message else nome_usuario
    sessoes[session_id] = {}
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
    session_id = str(call.message.chat.id)
    nome_usuario = call.from_user.first_name
    
    bot.answer_callback_query(call.id)
    
    if call.data == "menu_pergunta":
        sessoes[session_id] = {'estado': 'AGUARDANDO_PERGUNTA_RAG'}
        bot.edit_message_text("Entendido. Pode fazer sua pergunta que vou consultar meu guia de viagens!",
                              session_id, call.message.message_id)
        
    elif call.data == "menu_ver_perfil":
        preferencias = carregar_preferencias(session_id)
        if not preferencias or not (preferencias.get('estilo_viagem') or preferencias.get('interesses')):
            texto = "Você ainda não criou seu perfil de viajante."
            markup = types.InlineKeyboardMarkup()
            markup.add(types.InlineKeyboardButton("✍️ Criar Meu Perfil Agora", callback_data="menu_perfil"))
            bot.edit_message_text(texto, session_id, call.message.message_id, reply_markup=markup)
            return

        texto_perfil = f"*Seu Perfil de Viajante* 👤\n\n- *Nome:* {preferencias.get('nome', 'Não informado')}\n- *Estilo de Viagem:* {preferencias.get('estilo_viagem', 'Não informado')}\n- *Interesses:* {preferencias.get('interesses', 'Não informado')}"
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("⬅️ Voltar ao Menu", callback_data="voltar_menu"))
        bot.edit_message_text(texto_perfil, session_id, call.message.message_id, reply_markup=markup, parse_mode="Markdown")

    elif call.data == "voltar_menu":
        nome_usuario = call.from_user.first_name
        texto_saudacao = f"Ok, {nome_usuario}!"
        enviar_menu_principal(session_id, nome_usuario, texto_saudacao, message_to_edit=call.message)

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
        sessoes[session_id] = {'estado': 'AGUARDANDO_DESTINO', 'dados': {}}
        bot.edit_message_text("Ótima escolha! Para qual cidade ou país você quer um roteiro?", session_id, call.message.message_id)

    elif call.data == "menu_sugerir":
        sessoes[session_id] = {'estado': 'AGUARDANDO_SUGESTAO', 'dados': {}}
        bot.edit_message_text("Claro! Me diga o que você procura em uma viagem (ex: 'praia e sol').", session_id, call.message.message_id)

    elif call.data == "menu_perfil":
        interesses_salvos = carregar_preferencias(session_id).get('interesses', '')
        selecoes_atuais = [i.strip() for i in interesses_salvos.split(',') if i.strip()]
        sessoes[session_id] = {'estado': 'BRIEFING_INTERESSES', 'selecoes_interesses': selecoes_atuais}
        
        markup = types.InlineKeyboardMarkup(row_width=2)
        opcoes = ["Museus", "Natureza", "Vida Noturna", "Gastronomia"]
        botoes = [types.InlineKeyboardButton(f"✅ {opt}" if opt in selecoes_atuais else opt, callback_data=f"briefing_selecionar_{opt}") for opt in opcoes]
        markup.add(*botoes)
        markup.add(types.InlineKeyboardButton("➡️ Concluir", callback_data="briefing_selecionar_concluir"))
        bot.edit_message_text("Vamos criar/atualizar seu perfil. Selecione seus interesses e clique em 'Concluir'.", session_id, call.message.message_id, reply_markup=markup)

    elif call.data.startswith("briefing_selecionar_"):
        valor = call.data.split('_', 2)[2]
        if 'selecoes_interesses' not in sessoes.get(session_id, {}):
            sessoes[session_id] = {'estado': 'BRIEFING_INTERESSES', 'selecoes_interesses': []}
        
        selecoes_atuais = sessoes[session_id]['selecoes_interesses']
        
        if valor == 'concluir':
            interesses_finais = ", ".join(selecoes_atuais)
            salvar_preferencia(session_id, 'interesses', interesses_finais)
            texto_final = f"Perfil salvo com os interesses: *{interesses_finais}*." if interesses_finais else "Perfil salvo!"
            enviar_menu_principal(session_id, nome_usuario, texto_final, message_to_edit=call.message)
            return

        if valor in selecoes_atuais: selecoes_atuais.remove(valor)
        else: selecoes_atuais.append(valor)
        
        markup = types.InlineKeyboardMarkup(row_width=2)
        opcoes = ["Museus", "Natureza", "Vida Noturna", "Gastronomia"]
        botoes = [types.InlineKeyboardButton(f"✅ {opt}" if opt in selecoes_atuais else opt, callback_data=f"briefing_selecionar_{opt}") for opt in opcoes]
        markup.add(*botoes)
        markup.add(types.InlineKeyboardButton("➡️ Concluir Seleção", callback_data="briefing_selecionar_concluir"))
        bot.edit_message_reply_markup(chat_id=session_id, message_id=call.message.message_id, reply_markup=markup)
    
    elif call.data in ["gerar_pdf", "gerar_csv"]:
        bot.send_chat_action(session_id, 'upload_document')
        tipo_arquivo = call.data.split('_')[1]
        if tipo_arquivo == 'pdf':
            caminho_arquivo = gerar_pdf(destino=dados_usuario.get('destino'), datas=dados_usuario.get('datas'), tabela=dados_usuario.get('tabela_itinerario'), descricao=dados_usuario.get('descricao_detalhada'), session_id=session_id)
        else:
            caminho_arquivo = csv_generator(tabela=dados_usuario.get('tabela_itinerario'), session_id=session_id)
        with open(caminho_arquivo, 'rb') as arquivo: bot.send_document(session_id, arquivo)
        os.remove(caminho_arquivo)
        enviar_menu_pos_roteiro(session_id, message_to_edit=call.message)

@bot.message_handler(func=lambda message: True)
def handle_messages(message: telebot.types.Message):
    global sessoes
    session_id = str(message.chat.id)
    nome_usuario = message.from_user.first_name
    texto_normalizado = message.text.strip().lower()
    
    try:
        
        palavras_agradecimento = ["obrigado", "obrigada", "valeu", "grato", "agradeço", "thanks", "obg"]
        if any(palavra in texto_normalizado for palavra in palavras_agradecimento):
            sessoes[session_id] = {'estado': 'AGUARDANDO_CONFIRMACAO_FINAL', 'dados': {}}
            bot.reply_to(message, f"De nada, {nome_usuario}! 😊 Fico feliz em ajudar. Posso te ajudar com mais alguma coisa?")
            return

        estado_atual = sessoes.get(session_id, {}).get('estado')

        # Se o usuário está em um fluxo de perguntas, continua nele
        if estado_atual:
            resposta = processar_mensagem(session_id, message.text, nome_usuario)
            if resposta: bot.reply_to(message, resposta, parse_mode='Markdown')
        else:
            # Se não há estado, o bot dá uma resposta padrão sem entrar em loop
            bot.reply_to(message, "Desculpe, não entendi. Por favor, use os botões do menu ou digite /start para ver as opções.")
            return

        # Após processar, verifica se o fluxo terminou para mostrar o menu de opções
        if sessoes.get(session_id, {}).get('estado') == 'ROTEIRO_GERADO':
            enviar_menu_pos_roteiro(session_id)

    except Exception as e:
        print(f"!!!!!!!!!! ERRO GERAL NO HANDLE: {e} !!!!!!!!!!"); traceback.print_exc()
        bot.reply_to(message, "Desculpe, ocorreu um erro inesperado.")
        
# --- INICIA O BOT ---
print("VexusBot (Versão Avançada) em execução...")
while True:
    try:
        bot.infinity_polling(timeout=10, long_polling_timeout=5)
    except Exception as e:
        print(f"Erro de conexão/polling: {e}. Reiniciando em 15 segundos...")
        time.sleep(15)