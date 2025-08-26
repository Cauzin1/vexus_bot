# main.py - vIAjante - Versão Final com Botões, Tabela Formatada e IA Completa

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
from telebot import types # Importação para os botões

# --- UTILS ---
from utils.pdf_generator import gerar_pdf
from utils.csv_generator import csv_generator
from utils.validators import remover_acentos # Apenas o que for necessário

# --- Configuração ---
load_dotenv()
GEMINI_KEY = os.getenv("GEMINI_KEY")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")

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

# --- BANCO DE DADOS (MEMÓRIA DE LONGO PRAZO) ---
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
sessoes = {} # Memória de curto prazo

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
    """Converte uma tabela Markdown para texto monoespaçado e alinhado."""
    if not tabela_markdown: return ""
    linhas = [l for l in tabela_markdown.strip().split('\n') if not re.match(r'^[|: -]+$', l.replace(" ", ""))]
    dados_tabela = [[cel.strip() for cel in linha.split('|') if cel.strip()] for linha in linhas if '|' in linha]
    if not dados_tabela: return ""
    
    try:
        num_colunas = len(dados_tabela[0])
        larguras = [max(len(dados_tabela[i][j]) for i in range(len(dados_tabela))) for j in range(num_colunas)]
        tabela_formatada = ""
        for i, linha in enumerate(dados_tabela):
            linha_formatada = [celula.ljust(larguras[j]) for j, celula in enumerate(linha)]
            tabela_formatada += "  ".join(linha_formatada) + "\n"
            if i == 0:
                separador = ["-" * larguras[j] for j in range(num_colunas)]
                tabela_formatada += "  ".join(separador) + "\n"
        return f"```\n{tabela_formatada}```"
    except IndexError:
        return "Tabela com formato inesperado."

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

# --- CÉREBRO DO BOT ---
def processar_mensagem(session_id: str, texto: str, nome_usuario: str) -> str:
    global sessoes
    if session_id not in sessoes: sessoes[session_id] = {'estado': 'AGUARDANDO_DESTINO', 'dados': {}}
    
    estado = sessoes[session_id]['estado']
    dados_usuario = sessoes[session_id]['dados']
    
    if estado == "BRIEFING_TIPO_COMIDA":
        salvar_preferencia(session_id, 'tipo_comida', texto.strip())
        sessoes[session_id]['estado'] = "BRIEFING_INTERESSES"
        return "Perfeito! E para finalizar, quais são seus principais interesses? (Ex: `Museus e história`, `Natureza e trilhas`, `Vida noturna`)"

    elif estado == "BRIEFING_INTERESSES":
        salvar_preferencia(session_id, 'interesses', texto.strip())
        sessoes[session_id]['estado'] = "AGUARDANDO_DESTINO"
        return f"Prontinho, {nome_usuario}! Seu perfil de viajante está salvo. Agora, para qual cidade ou país vamos planejar?"
    
    elif estado == "AGUARDANDO_DESTINO":
        destinos = validar_e_extrair_destinos_com_ia(texto)
        if not destinos.get("cidades") and not destinos.get("paises"):
            return "Hmm, não consegui identificar um destino. Pode tentar de novo?"
        destino_str = ", ".join(destinos.get("cidades", []) + destinos.get("paises", []))
        dados_usuario["destino"] = destino_str
        sessoes[session_id]['estado'] = "AGUARDANDO_DATAS"
        return (f"✈️ *{destino_str}* é uma ótima escolha!\nAgora me conta: *quando* você vai viajar?")

    elif estado == "AGUARDANDO_DATAS":
        datas = extrair_datas_com_ia(texto)
        if not datas.get("data_inicio"):
            return "❌ Não consegui entender esse período. Tente algo como '10 a 25 de dezembro'."
        dados_usuario["datas"] = f"{datas['data_inicio']} a {datas['data_fim']}" if datas.get("data_fim") else datas['data_inicio']
        sessoes[session_id]['estado'] = "AGUARDANDO_ORCAMENTO"
        return "Anotado! Agora, qual o seu orçamento total para a viagem em Reais (R$)? "

    elif estado == "AGUARDANDO_ORCAMENTO":
        valor = extrair_orcamento_com_ia(texto)
        if valor == 0:
            return "❌ Não entendi o valor. Por favor, informe um número (ex: 15000, 20 mil)."
        dados_usuario["orcamento"] = f"R$ {valor:,.2f}"
        sessoes[session_id]['estado'] = "GERANDO_ROTEIRO"
        return f"Perfeito! Orçamento salvo. Estou preparando seu roteiro... Me envie um `ok` para continuar."

    elif estado == "GERANDO_ROTEIRO":
        try:
            bot.send_chat_action(session_id, 'typing')
            preferencias = carregar_preferencias(session_id)
            contexto_personalizado = f"Perfil do Viajante: Estilo de Viagem: {preferencias.get('estilo_viagem', 'geral')}, Interesses: {preferencias.get('interesses', 'variados')}"
            
            prompt = (f"Crie um roteiro de viagem detalhado para {dados_usuario['destino']} de {dados_usuario['datas']} com orçamento de {dados_usuario['orcamento']}. {contexto_personalizado}. Inclua uma tabela Markdown com colunas DATA, DIA, LOCAL.")
            
            response = model.generate_content(prompt)
            resposta_completa = response.text
            tabela_bruta = extrair_tabela(resposta_completa)
            
            dados_usuario.update({'tabela_itinerario': tabela_bruta, 'descricao_detalhada': resposta_completa.replace(tabela_bruta, "").strip()})
            sessoes[session_id]['estado'] = "ROTEIRO_GERADO"
            
            resumo_formatado = formatar_tabela_para_telegram(tabela_bruta) if tabela_bruta else "**Não foi possível extrair um resumo em tabela.**"
            
            return (f"🎉 *Prontinho!* Seu roteiro personalizado está pronto:\n\n{resumo_formatado}\n\n"
                    "O que fazer agora?\n- Digite `pdf` para o roteiro completo\n- Digite `csv` para a planilha\n- Digite `reiniciar`.")
        except Exception as e:
            traceback.print_exc()
            sessoes[session_id]['estado'] = "AGUARDANDO_DESTINO"; return "❌ Opa! Tive um problema ao gerar o roteiro. Vamos recomeçar?"

    elif estado == "ROTEIRO_GERADO":
        return "Seu roteiro foi gerado. Peça seu `pdf`, `csv` ou digite `reiniciar`."

    return "Desculpe, não entendi."

# --- Gerenciadores de Mensagem do Telegram (Handlers) ---
@bot.message_handler(commands=['start', 'help', 'iniciar'])
def handle_start(message: telebot.types.Message):
    global sessoes
    session_id = str(message.chat.id)
    nome_usuario = message.from_user.first_name
    preferencias = carregar_preferencias(session_id)
    
    if preferencias and preferencias.get('estilo_viagem'):
        sessoes[session_id] = {'estado': 'AGUARDANDO_DESTINO', 'dados': {}}
        estilo = preferencias['estilo_viagem']
        bot.reply_to(message, f"👋 Bem-vindo de volta, {nome_usuario}! Vi aqui que você curte viagens no estilo *{estilo}*. Para onde vamos dessa vez?", parse_mode='Markdown')
    else:
        salvar_preferencia(session_id, 'nome', nome_usuario)
        handle_perfil(message) # Chama diretamente o handler de perfil

@bot.message_handler(commands=['perfil'])
def handle_perfil(message: telebot.types.Message):
    global sessoes
    session_id = str(message.chat.id)
    sessoes[session_id] = {'estado': 'BRIEFING_ESTILO_VIAGEM', 'dados': {}}
    markup = types.InlineKeyboardMarkup(row_width=2)
    b1 = types.InlineKeyboardButton("🎒 Mochileiro", callback_data="estilo_Mochileiro")
    b2 = types.InlineKeyboardButton("🏛️ Cultural", callback_data="estilo_Cultural")
    b3 = types.InlineKeyboardButton("💎 Luxo", callback_data="estilo_Luxo")
    b4 = types.InlineKeyboardButton("🌲 Aventura", callback_data="estilo_Aventura")
    markup.add(b1, b2, b3, b4)
    bot.send_message(message.chat.id, "Vamos personalizar sua experiência! Qual seu estilo de viagem preferido?", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith("estilo_"))
def handle_estilo_callback(call: types.CallbackQuery):
    global sessoes
    session_id = str(call.message.chat.id)
    nome_usuario = call.from_user.first_name
    estilo_selecionado = call.data.split('_')[1]
    
    bot.answer_callback_query(call.id, text=f"{estilo_selecionado} selecionado!")
    salvar_preferencia(session_id, 'estilo_viagem', estilo_selecionado)
    sessoes[session_id]['estado'] = "BRIEFING_TIPO_COMIDA"
    
    bot.edit_message_text(f"Legal, {nome_usuario}! Anotei seu estilo: *{estilo_selecionado}*.", 
                          call.message.chat.id, call.message.message_id, parse_mode='Markdown')
    bot.send_message(session_id, "Agora, que tipo de comida você mais gosta em suas viagens? (Ex: `Local`, `Italiana`, `Asiática`)", parse_mode='Markdown')

@bot.message_handler(func=lambda message: True)
def handle_messages(message: telebot.types.Message):
    global sessoes
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
            else:
                caminho_arquivo = csv_generator(tabela=dados_usuario['tabela_itinerario'], session_id=session_id)
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
print("Bot vIAjante (Versão Final com Botões) em execução...")
bot.infinity_polling()