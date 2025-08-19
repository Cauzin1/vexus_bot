import re
import unicodedata

PAISES_EUROPA = [
    "alemanha", "franca", "espanha", "italia", "portugal", "holanda", "belgica", 
    "suica", "austria", "dinamarca", "suecia", "noruega", "finlandia", "irlanda", 
    "reino unido", "polonia", "tchequia", "hungria", "romenia", "bulgaria", 
    "grecia", "croacia", "malta", "chipre", "luxemburgo" 
    # Lista simplificada para os destinos mais comuns
]

def remover_acentos(texto: str) -> str:
    nfkd_form = unicodedata.normalize('NFKD', texto)
    return "".join([c for c in nfkd_form if not unicodedata.combining(c)])

def validar_data(texto: str) -> bool:
    return re.match(r"^\d{1,2}/\d{1,2}\s*a\s*\d{1,2}/\d{1,2}$", texto.strip()) is not None

def validar_orcamento(texto: str) -> bool:
    txt = texto.lower().replace("r$", "").replace(" ", "").replace(".", "").replace(",", ".")
    if "mil" in txt:
        txt = txt.replace("mil", "")
        try: return float(txt) * 1000 > 0
        except ValueError: return False
    try: return float(txt) > 0
    except ValueError: return False