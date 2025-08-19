# app.py - vIAjante - Versão Final Completa

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

# (Assuma que sua pasta utils com pdf_generator, csv_generator, etc., ainda existe)
from utils.pdf_generator import gerar_pdf
from utils.csv_generator import csv_generator

# --- Configuração ---
load_dotenv()
GEMINI_KEY = os.getenv("GEMINI_KEY")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
bot = telebot.TeleBot(TELEGRAM_TOKEN)
sessoes = {}

try:
    genai.configure(api_key=GEMINI_KEY)
    model = genai.GenerativeModel('gemini-1.5-flash')
    print("✅ Gemini configurado com sucesso!")
except Exception as e:
    print(f"❌ Erro na configuração do Gemini: {e}"); exit()

# --- BANCO DE DADOS ---
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
    cursor = conexao.cursor()
    cursor.execute("SELECT * FROM usuarios WHERE chat_id = ?", (str(chat_id),))
    resultado = cursor.fetchone()
    conexao.close()
    if resultado:
        colunas = [description[0] for description in cursor.description]
        return dict(zip(colunas, resultado))
    return {}

# --- FUNÇÕES DE IA ---
def validar_e_extrair_destinos_com_ia(texto_usuario: str) -> dict:
    prompt = f'Analise o texto e identifique cidades e países. Retorne APENAS um JSON com chaves "cidades" e "paises". Texto: "{texto_usuario}"'
    try:
        response = model.generate_content(prompt)
        json_text = re.search(r'\{.*\}', response.text, re.DOTALL).group(0)
        return json.loads(json_text)
    except Exception: return {"cidades": [], "paises": []}

def extrair_datas_com_ia(texto_usuario: str) -> dict:
    data_atual = datetime.now().strftime('%d/%m/%Y')
    prompt = f'Considere a data atual como {data_atual}. Extraia um intervalo de datas do texto. Responda APENAS com um JSON com chaves "data_inicio" e "data_fim" (formato "DD/MM/YYYY"). Texto: "{texto_usuario}"'
    try:
        response = model.generate_content(prompt)
        json_text = re.search(r'\{.*\}', response.text, re.DOTALL).group(0)
        return json.loads(json_text)
    except Exception: return {"data_inicio": "", "data_fim": ""}

def extrair_orcamento_com_ia(texto_usuario: str) -> int:
    prompt = f'Extraia o valor monetário do texto como um número inteiro. "20 mil" é 20000. Responda APENAS com um JSON com a chave "valor". Texto: "{texto_usuario}"'
    try:
        response = model.generate_content(prompt)
        json_text = re.search(r'\{.*\}', response.text, re.DOTALL).group(0)
        return int(json.loads(json_text).get("valor", 0))
    except Exception: return 0
    
def extrair_tabela(texto: str) -> str:
    linhas_tabela = []
    for linha in texto.split('\n'):
        linha = linha.strip()
        if linha.startswith('|') and linha.count('|') > 2:
            if re.match(r'^[|: -]+$', linha.replace(" ", "")): continue
            linhas_tabela.append(linha)
    if not linhas_tabela: return ""
    return '\n'.join(linhas_tabela)

# --- CÉREBRO DO BOT ---
def processar_mensagem(session_id: str, texto: str, nome_usuario: str) -> str:
    if session_id not in sessoes:
        sessoes[session_id] = {'estado': 'INICIO', 'dados': {}}
    
    estado = sessoes[session_id]['estado']
    dados_usuario = sessoes[session_id]['dados']
    texto_normalizado = texto.strip().lower()

    if texto_normalizado in ["reiniciar", "/reiniciar"]:
        sessoes[session_id] = {'estado': 'AGUARDANDO_DESTINO', 'dados': {}}
        return f"🔄 Certo, {nome_usuario}! Vamos recomeçar. Para qual cidade ou país você quer um roteiro?"
    
    # (Seu fluxo de Briefing deve ser inserido aqui se desejar)

    if estado == "AGUARDANDO_DESTINO":
        destinos = validar_e_extrair_destinos_com_ia(texto)
        if not destinos.get("cidades") and not destinos.get("paises"):
            return "Hmm, não consegui identificar um destino. Pode tentar de novo?"
        
        destino_str = ", ".join(destinos.get("cidades", [])) + ", ".join(destinos.get("paises", []))
        dados_usuario['destino'] = destino_str
        sessoes[session_id]['estado'] = "AGUARDANDO_DATAS"
        return f"Entendido! Roteiro para: *{destino_str}*.\n\nPara quando seria a viagem?"

    elif estado == "AGUARDANDO_DATAS":
        datas = extrair_datas_com_ia(texto)
        if not datas.get("data_inicio"):
            return "❌ Não consegui entender esse período. Tente algo como '10 a 25 de dezembro' ou 'próximo mês'."
            
        dados_usuario["datas"] = f"{datas['data_inicio']} a {datas['data_fim']}"
        sessoes[session_id]['estado'] = "AGUARDANDO_ORCAMENTO"
        return "Anotado! Agora, qual o seu orçamento total para a viagem em Reais (R$)?"

    elif estado == "AGUARDANDO_ORCAMENTO":
        valor = extrair_orcamento_com_ia(texto)
        if valor == 0:
            return "❌ Não entendi o valor. Por favor, informe um número (ex: 15000, 20 mil)."
        
        dados_usuario["orcamento"] = f"R$ {valor:,.2f}"
        sessoes[session_id]['estado'] = "GERANDO_ROTEIRO"
        return "Perfeito! Orçamento salvo. Estou preparando seu roteiro... Me envie um `ok` para continuar."

    # >>> LÓGICA FINAL RESTAURADA <<<
    elif estado == "GERANDO_ROTEIRO":
        try:
            bot.send_chat_action(session_id, 'typing')
            preferencias = carregar_preferencias(session_id)
            contexto_personalizado = f"Perfil do Viajante: Estilo de Viagem: {preferencias.get('estilo_viagem', 'geral')}, Interesses: {preferencias.get('interesses', 'variados')}"
            
            prompt = (f"Crie um roteiro de viagem detalhado para {dados_usuario['destino']} de {dados_usuario['datas']} com orçamento de {dados_usuario['orcamento']}. "
                      f"Inclua uma tabela Markdown com colunas DATA, DIA, LOCAL. {contexto_personalizado}")
            
            response = model.generate_content(prompt)
            resposta_completa = response.text
            tabela_itinerario = extrair_tabela(resposta_completa)
            descricao_detalhada = resposta_completa.replace(tabela_itinerario, "").strip() if tabela_itinerario else resposta_completa

            dados_usuario.update({
                'roteiro_completo': resposta_completa,
                'tabela_itinerario': tabela_itinerario,
                'descricao_detalhada': descricao_detalhada
            })
            sessoes[session_id]['estado'] = "ROTEIRO_GERADO"
            resumo_tabela = tabela_itinerario if tabela_itinerario else "**Não foi possível extrair um resumo.**"
            
            return (f"🎉 *Prontinho!* Seu roteiro personalizado está pronto:\n\n{resumo_tabela}\n\n"
                    "O que fazer agora?\n- Digite `pdf` para o roteiro completo\n- Digite `csv` para a planilha\n- Digite `reiniciar`.")
        except Exception as e:
            traceback.print_exc()
            sessoes[session_id]['estado'] = "AGUARDANDO_DESTINO"
            return "❌ Opa! Tive um problema ao gerar o roteiro. Pode ter sido um problema com a API. Vamos recomeçar?"

    elif estado == "ROTEIRO_GERADO":
        # A lógica para PDF/CSV é tratada no handler principal
        return "Seu roteiro foi gerado. Peça seu `pdf`, `csv` ou digite `reiniciar`."

    return "Desculpe, não entendi."


# --- Gerenciadores de Mensagem do Telegram ---
@bot.message_handler(commands=['start', 'help', 'iniciar'])
def handle_start(message: telebot.types.Message):
    session_id = str(message.chat.id)
    nome_usuario = message.from_user.first_name
    sessoes[session_id] = {'estado': 'AGUARDANDO_DESTINO', 'dados': {}}
    bot.reply_to(message, f"🌟 Olá, {nome_usuario}! Eu sou o VexusBot. Para começarmos, me diga para qual cidade ou país você quer um roteiro.")

@bot.message_handler(func=lambda message: True)
def handle_messages(message: telebot.types.Message):
    session_id = str(message.chat.id)
    nome_usuario = message.from_user.first_name
    texto_normalizado = message.text.strip().lower()
    estado_atual = sessoes.get(session_id, {}).get('estado')

    try:
        if estado_atual == "ROTEIRO_GERADO" and texto_normalizado in ['pdf', 'csv']:
            bot.reply_to(message, f"Gerando seu arquivo `{texto_normalizado}`, um momento...")
            dados_usuario = sessoes[session_id]['dados']
            
            if texto_normalizado == 'pdf':
                caminho_arquivo = gerar_pdf(
                    destino=dados_usuario['destino'], datas=dados_usuario['datas'],
                    tabela=dados_usuario['tabela_itinerario'], descricao=dados_usuario['descricao_detalhada'],
                    session_id=session_id)
            else: # csv
                caminho_arquivo = csv_generator(
                    tabela=dados_usuario['tabela_itinerario'],
                    session_id=session_id)

            with open(caminho_arquivo, 'rb') as arquivo:
                bot.send_document(message.chat.id, arquivo)
            os.remove(caminho_arquivo)
            return

        resposta = processar_mensagem(session_id, message.text, nome_usuario)
        bot.reply_to(message, resposta, parse_mode='Markdown')
        
    except Exception as e:
        print(f"!!!!!!!!!! ERRO GERAL NO HANDLE: {e} !!!!!!!!!!"); traceback.print_exc()
        bot.reply_to(message, "Desculpe, ocorreu um erro. Tente `reiniciar`.")

# --- Inicia o Bot ---
print("Bot VexusBot (Versão Completa) em execução...")
bot.infinity_polling()