# criar_base_rag.py

import os
from dotenv import load_dotenv
from langchain_community.document_loaders import TextLoader
from langchain_google_genai import GoogleGenerativeAIEmbeddings
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_community.vectorstores import FAISS

print("Iniciando a criação da base de conhecimento RAG...")
load_dotenv()

GEMINI_KEY = os.getenv("GEMINI_KEY")
if not GEMINI_KEY:
    raise ValueError("Chave GEMINI_KEY não encontrada no arquivo .env")

# 1. Carregar o documento
loader = TextLoader('conhecimento.txt', encoding='utf-8')
documentos = loader.load()

# 2. Dividir o documento em pedaços (chunks)
text_splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=150)
chunks = text_splitter.split_documents(documentos)
print(f"Documento dividido em {len(chunks)} pedaços.")

# 3. Criar os embeddings e o Vector Store
embeddings = GoogleGenerativeAIEmbeddings(model="models/embedding-001", google_api_key=GEMINI_KEY)
vector_store = FAISS.from_documents(chunks, embeddings)

# 4. Salvar o índice localmente
vector_store.save_local("faiss_index")
print("\n✅ Base de conhecimento RAG criada e salva com sucesso na pasta 'faiss_index'!")