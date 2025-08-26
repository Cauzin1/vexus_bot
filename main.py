# main.py - vIAjante - Versão Final com Cérebro de IA

import os
import re
import traceback
import sqlite3
import random
import json
from datetime import datetime
from dotenv import load_dotenv
import google.generativeai as genai
import telebot
from telebot import types

# --- Configuração ---
load_dotenv()
GEMINI_KEY = os.getenv("GEMINI_KEY")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
bot = telebot.TeleBot(TELEGRAM_TOKEN)
sessoes = {} # Memória de curto prazo para dados do roteiro
historico_conversa = {} # Memória de contexto da conversa atual

try:
    genai.configure(api_key=GEMINI_KEY)
    model = genai.GenerativeModel('gemini-1.5-flash')
    print("✅ Gemini configurado com sucesso!")
except Exception as e:
    print(f"❌ Erro na configuração do Gemini: {e}"); exit()

# --- BANCO DE DADOS (MEMÓRIA DE LONGO PRAZO) ---
def inicializar_banco():
    conexao = sqlite3.connect('usuarios.db', check_same_thread=False)
    cursor = conexao.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS usuarios (
            id INTEGER PRIMARY KEY, chat_id TEXT UNIQUE NOT NULL, nome TEXT,
            estilo_viagem TEXT, interesses TEXT
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
    if resultado: return dict(resultado)
    return {}

# --- "FERRAMENTAS" DO BOT ---
def gerar_roteiro_final(dados_viagem: dict, preferencias: dict) -> str:
    try:
        contexto = f"Perfil do Viajante: Estilo {preferencias.get('estilo_viagem', 'geral')}, Interesses {preferencias.get('interesses', 'variados')}."
        prompt = (f"Crie um roteiro de viagem detalhado para {dados_viagem['destino']} de {dados_viagem['datas']} com orçamento de {dados_viagem['orcamento']}. {contexto} "
                  f"Inclua uma tabela Markdown com colunas DATA, DIA, LOCAL.")
        response = model.generate_content(prompt)
        # (Futuramente, aqui entraria a lógica de salvar o roteiro completo na sessão para PDF/CSV)
        return response.text
    except Exception as e:
        return f"Ocorreu um erro ao gerar o roteiro: {e}"

# --- O "CÉREBRO" DO BOT ---
def decidir_proxima_acao(chat_id: str, texto_usuario: str, preferencias: dict, dados_roteiro_atual: dict) -> dict:
    if chat_id not in historico_conversa: historico_conversa[chat_id] = []
    
    contexto_perfil = "O usuário ainda não tem um perfil salvo."
    if preferencias:
        contexto_perfil = f"O usuário se chama {preferencias.get('nome', '')} e tem o perfil: Estilo {preferencias.get('estilo_viagem', '')}, Interesses {preferencias.get('interesses', '')}."

    prompt_cerebro = f"""
    Você é o cérebro de um assistente de viagens. Analise a Mensagem do Usuário, o Histórico e o Perfil para decidir qual ferramenta usar.

    PERFIL DO USUÁRIO: {contexto_perfil}
    DADOS DO ROTEIRO ATUAL: {json.dumps(dados_roteiro_atual)}

    FERRAMENTAS:
    - 'coletar_dados_viagem': Use quando o usuário fornecer QUALQUER informação para um roteiro (destino, data, orçamento). Extraia os dados que ele fornecer.
    - 'responder_pergunta_geral': Use para perguntas genéricas sobre viagens (vistos, clima, dicas, etc.) que NÃO são parte do planejamento de um roteiro específico.
    - 'saudacao': Para cumprimentos simples.
    
    HISTÓRICO (últimas 4 mensagens):
    {''.join(historico_conversa.get(chat_id, [])[-4:])}

    MENSAGEM ATUAL DO USUÁRIO: "{texto_usuario}"

    Sua resposta DEVE ser um objeto JSON com a "ferramenta" e os "parametros" extraídos. Se a mensagem do usuário tiver múltiplas intenções (ex: "em setembro. Precisa de visto?"), sua resposta PODE ser uma lista de JSONs.
    Ex: [{{"ferramenta": "coletar_dados_viagem", "parametros": {{"datas": "em setembro"}}}}, {{"ferramenta": "responder_pergunta_geral", "parametros": {{"pergunta": "Precisa de visto?"}}}}]
    """
    try:
        response = model.generate_content(prompt_cerebro)
        # Tenta encontrar uma lista de JSONs ou um único JSON
        json_text = response.text.strip()
        if json_text.startswith('[') and json_text.endswith(']'):
            return json.loads(json_text) # Retorna a lista de decisões
        elif json_text.startswith('{') and json_text.endswith('}'):
            return [json.loads(json_text)] # Retorna um único JSON dentro de uma lista
        else: # Fallback para extração com regex se a formatação falhar
            match = re.search(r'\[.*\]|\{.*\}', json_text, re.DOTALL)
            if match:
                return json.loads(match.group(0))
            return [{"ferramenta": "erro"}]
    except Exception as e:
        print(f"Erro ao decidir ação: {e}"); return [{"ferramenta": "erro"}]

# --- Gerenciadores de Mensagem do Telegram (Handlers) ---

@bot.message_handler(commands=['start', 'help', 'iniciar', 'reiniciar'])
def handle_start(message: telebot.types.Message):
    session_id = str(message.chat.id)
    nome_usuario = message.from_user.first_name
    preferencias = carregar_preferencias(session_id)
    
    sessoes[session_id] = {} # Limpa os dados do roteiro atual
    historico_conversa[session_id] = [] # Limpa o histórico da conversa

    if preferencias:
        estilo = preferencias.get('estilo_viagem', 'desconhecido')
        bot.reply_to(message, f"👋 Bem-vindo de volta, {nome_usuario}! Vi aqui que você curte viagens no estilo *{estilo}*. Para onde vamos dessa vez?", parse_mode='Markdown')
    else:
        bot.reply_to(message, f"🌟 Olá, {nome_usuario}! Eu sou o VexusBot. Para começarmos, me diga para qual cidade ou país você quer um roteiro. Você também pode digitar `/perfil` para me contar seus gostos.")

# (Handlers para /perfil e callback_query_handler aqui)

@bot.message_handler(func=lambda message: True)
def handle_messages(message: telebot.types.Message):
    session_id = str(message.chat.id)
    texto_usuario = message.text
    
    try:
        preferencias = carregar_preferencias(session_id)
        if session_id not in sessoes: sessoes[session_id] = {}
        
        # O cérebro da IA analisa a mensagem
        decisoes = decidir_proxima_acao(session_id, texto_usuario, preferencias, sessoes[session_id])
        
        respostas_a_enviar = []
        proxima_pergunta = ""

        # Executa cada decisão da IA
        for decisao in decisoes:
            ferramenta = decisao.get("ferramenta")
            parametros = decisao.get("parametros", {})

            if ferramenta == 'coletar_dados_viagem':
                sessoes[session_id].update(parametros)
                # Não envia resposta ainda, apenas coleta os dados
            
            elif ferramenta == 'responder_pergunta_geral':
                bot.send_chat_action(session_id, 'typing')
                pergunta = parametros.get('pergunta', texto_usuario)
                prompt_geral = f"Responda a seguinte pergunta de um viajante: {pergunta}"
                response = model.generate_content(prompt_geral)
                respostas_a_enviar.append(response.text)
                
            elif ferramenta == 'saudacao':
                respostas_a_enviar.append(f"Olá, {message.from_user.first_name}! Como posso te ajudar?")
        
        # Após executar todas as ações, verifica o estado do roteiro
        dados_atuais = sessoes.get(session_id, {})
        if dados_atuais.get('destino') and dados_atuais.get('datas') and dados_atuais.get('orcamento'):
            bot.send_chat_action(session_id, 'typing')
            resposta_roteiro = gerar_roteiro_final(dados_atuais, preferencias)
            respostas_a_enviar.append(resposta_roteiro)
            sessoes[session_id] = {} # Limpa após gerar
        else:
            # Pede a próxima informação que falta
            if not dados_atuais.get('destino'):
                proxima_pergunta = "Para onde vamos?"
            elif not dados_atuais.get('datas'):
                proxima_pergunta = f"Destino anotado: *{dados_atuais.get('destino')}*. Quando seria a viagem?"
            elif not dados_atuais.get('orcamento'):
                proxima_pergunta = f"Perfeito! Viagem para *{dados_atuais.get('destino')}* em *{dados_atuais.get('datas')}*. Qual o seu orçamento?"
        
        # Envia todas as respostas acumuladas
        if respostas_a_enviar:
            bot.reply_to(message, "\n\n".join(respostas_a_enviar), parse_mode='Markdown')
        
        # Envia a próxima pergunta, se houver
        if proxima_pergunta:
            # Se já enviou uma resposta, envia como nova mensagem. Se não, usa reply_to.
            if respostas_a_enviar:
                bot.send_message(message.chat.id, proxima_pergunta, parse_mode='Markdown')
            else:
                bot.reply_to(message, proxima_pergunta, parse_mode='Markdown')

        # Atualiza o histórico
        historico_conversa.setdefault(session_id, []).append(f"Usuário: {texto_usuario}\nBot: {' '.join(respostas_a_enviar)} {proxima_pergunta}\n")

    except Exception as e:
        print(f"!!!!!!!!!! ERRO GERAL NO HANDLE: {e} !!!!!!!!!!"); traceback.print_exc()
        bot.reply_to(message, "Desculpe, ocorreu um erro inesperado. Tente novamente.")

# --- Inicia o Bot ---
print("Bot VexusBot (com Cérebro de IA) em execução...")
bot.infinity_polling()