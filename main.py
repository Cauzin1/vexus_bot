import os
import re
import traceback
from dotenv import load_dotenv
import google.generativeai as genai
import telebot

# Restaura as importações dos seus arquivos de utilidades
from utils.pdf_generator import gerar_pdf
from utils.csv_generator import csv_generator
from utils.validators import validar_destino, validar_data, validar_orcamento, remover_acentos

# --- Configuração ---
load_dotenv()
GEMINI_KEY = os.getenv("GEMINI_KEY")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")

# Validação das chaves
if not GEMINI_KEY or not TELEGRAM_TOKEN:
    print("ERRO CRÍTICO: Verifique suas chaves GEMINI_KEY e TELEGRAM_TOKEN no arquivo .env!")
    exit()

# Inicialização dos serviços
try:
    genai.configure(api_key=GEMINI_KEY)
    model = genai.GenerativeModel('gemini-1.5-flash')
    print("✅ Gemini configurado com sucesso!")
except Exception as e:
    print(f"❌ Erro na configuração do Gemini: {e}")
    exit()

bot = telebot.TeleBot(TELEGRAM_TOKEN)
print("✅ Bot do Telegram iniciado com sucesso!")

# --- Armazenamento e Lógica ---
sessoes = {}

def extrair_tabela(texto: str) -> str:
    # Sua função de extração de tabela
    linhas_tabela = []
    for linha in texto.split('\n'):
        linha = linha.strip()
        if linha.startswith('|') and linha.count('|') > 2:
            if re.match(r'^[|: -]+$', linha.replace(" ", "")): continue
            linhas_tabela.append(linha)
    if not linhas_tabela: return ""
    return '\n'.join(linhas_tabela)

# Cérebro do bot, agora completo
def processar_mensagem(session_id: str, texto: str) -> str:
    if session_id not in sessoes:
        sessoes[session_id] = {'estado': 'INICIO', 'dados': {}}
    
    estado = sessoes[session_id]['estado']
    dados_usuario = sessoes[session_id]['dados']
    texto_normalizado = texto.strip().lower()

    if texto_normalizado in ["reiniciar", "/reiniciar"]:
        sessoes[session_id] = {'estado': 'INICIO', 'dados': {}}
        return "🔄 Certo! Vamos começar uma nova viagem. Para onde na Europa você quer viajar?"

    if texto_normalizado in ["oi", "ola", "olá", "eai"]:
        if estado == 'INICIO':
            return "Olá! 👋 Para começarmos, me diga para qual país da Europa você quer viajar?"
        else:
            destino = dados_usuario.get('destino', 'sua viagem')
            return f"Olá! 😊 Podemos continuar planejando sua viagem para *{destino}*."

    # --- Fluxo de Estados ---
    if estado == "INICIO":
        if validar_destino(texto_normalizado):
            dados_usuario["destino"] = texto.strip().title()
            sessoes[session_id]['estado'] = "AGUARDANDO_DATAS"
            return (f"✈️ *{dados_usuario['destino']}* é uma ótima escolha!\n"
                    "Agora me conta: *quando* você vai viajar?\n\n"
                    "📅 Por favor, informe as datas no formato: `DD/MM a DD/MM`")
        else:
            return "❌ *País não reconhecido*. Por favor, informe um país europeu válido (ex: Itália, França...)."

    elif estado == "AGUARDANDO_DATAS":
        if not validar_data(texto_normalizado):
            return "❌ *Formato incorreto* ⚠️\nPor favor, use o formato: `DD/MM a DD/MM`."
        dados_usuario["datas"] = texto_normalizado
        sessoes[session_id]['estado'] = "AGUARDANDO_ORCAMENTO"
        return "💰 *Quase lá!* Agora me fale sobre o orçamento total da viagem em Reais (R$):"

    elif estado == "AGUARDANDO_ORCAMENTO":
        if not validar_orcamento(texto_normalizado):
            return "❌ *Valor inválido* ⚠️\nPor favor, informe um valor numérico válido (ex: 15000)."
        dados_usuario["orcamento"] = texto.strip()
        sessoes[session_id]['estado'] = "GERANDO_ROTEIRO"
        return (f"⏱️ *Perfeito!* Estou preparando seu roteiro para *{dados_usuario['destino']}*...\n"
                "Isso pode levar alguns segundos. Para continuar, pode me mandar um `ok`.")

    elif estado == "GERANDO_ROTEIRO":
        try:
            prompt = (f"Crie um roteiro de viagem detalhado para {dados_usuario['destino']} de {dados_usuario['datas']} com orçamento de {dados_usuario['orcamento']}. Inclua um itinerário dia a dia em uma tabela Markdown com colunas DATA, DIA, LOCAL.")
            print("Enviando prompt para o Gemini...")
            response = model.generate_content(prompt)
            print("Resposta recebida do Gemini.")
            resposta_completa = response.text
            tabela_itinerario = extrair_tabela(resposta_completa)
            descricao_detalhada = resposta_completa.replace(tabela_itinerario, "").strip() if tabela_itinerario else resposta_completa

            dados_usuario.update({
                'roteiro_completo': resposta_completa,
                'tabela_itinerario': tabela_itinerario,
                'descricao_detalhada': descricao_detalhada
            })
            sessoes[session_id]['estado'] = "ROTEIRO_GERADO"
            resumo_tabela = tabela_itinerario if tabela_itinerario else "**Não foi possível extrair o resumo do itinerário.**"
            return (f"🎉 *Prontinho!* Seu roteiro para *{dados_usuario['destino']}* está pronto:\n\n{resumo_tabela}\n\n"
                    "O que fazer agora?\n- Digite `pdf` para o roteiro completo\n- Digite `csv` para a planilha\n- Digite `reiniciar` para começar de novo")
        except Exception as e:
            traceback.print_exc()
            sessoes[session_id]['estado'] = "INICIO"
            return "❌ Opa! Tive um problema ao gerar o roteiro. Verifique sua chave da API Gemini. Para recomeçar, me diga um destino."

    elif estado == "ROTEIRO_GERADO":
        # A lógica de pedir PDF/CSV é tratada no handler principal
        return "Seu roteiro foi gerado. Peça seu `pdf`, `csv` ou digite `reiniciar`."

    return "Desculpe, não entendi. Para recomeçar, digite `reiniciar`."


# --- Gerenciadores de Mensagem do Telegram ---

@bot.message_handler(commands=['start', 'help', 'iniciar'])
def handle_start(message: telebot.types.Message):
    session_id = str(message.chat.id)
    sessoes[session_id] = {'estado': 'INICIO', 'dados': {}}
    bot.reply_to(message, "🌟 Olá! Eu sou o vIAjante. Para começarmos, me diga para qual país da Europa você quer viajar?")

@bot.message_handler(func=lambda message: True)
def handle_messages(message: telebot.types.Message):
    session_id = str(message.chat.id)
    texto_normalizado = message.text.strip().lower()
    estado_atual = sessoes.get(session_id, {}).get('estado')

    try:
        # --- LÓGICA DE ENVIO DE ARQUIVOS ---
        # Se o roteiro já foi gerado e o usuário pede um arquivo
        if estado_atual == "ROTEIRO_GERADO" and texto_normalizado in ['pdf', 'csv']:
            bot.reply_to(message, f"Gerando seu arquivo `{texto_normalizado}`, só um momento...")
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

            # Envia o arquivo diretamente no chat
            with open(caminho_arquivo, 'rb') as arquivo:
                bot.send_document(message.chat.id, arquivo)
            
            # Apaga o arquivo temporário do servidor
            os.remove(caminho_arquivo)
            bot.send_message(message.chat.id, "Aqui está! O que mais posso fazer?")

        else:
            # Se não for um pedido de arquivo, processa a mensagem normalmente
            resposta = processar_mensagem(session_id, message.text)
            bot.reply_to(message, resposta, parse_mode='Markdown')

    except Exception as e:
        print(f"!!!!!!!!!! ERRO GERAL NO HANDLE: {e} !!!!!!!!!!")
        traceback.print_exc()
        bot.reply_to(message, "Desculpe, ocorreu um erro inesperado. Tente `reiniciar`.")


# --- Inicia o Bot ---
print("Bot vIAjante Completo em execução... (Polling)")
bot.infinity_polling()