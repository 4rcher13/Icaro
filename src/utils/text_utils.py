import unicodedata

def normalize_text(text: str) -> str:
    """
    Normaliza una cadena quitando tildes y pasando a minúsculas.
    Útil para comparaciones robustas de comandos de voz.
    """
    if not text:
        return ""
    return "".join(
        c for c in unicodedata.normalize("NFD", text.lower().strip())
        if unicodedata.category(c) != "Mn"
    )
