"""Pacote gerador de extratos sintéticos ViaCard (PROMPT MESTRE v4.3 + fraudes materializadas v4.4)."""
from . import bases, motor, fraudes, validacao, export, gerador   # noqa: F401

__all__ = ["bases", "motor", "fraudes", "validacao", "export", "gerador"]
__version__ = "4.4.0"
