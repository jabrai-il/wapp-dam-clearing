"""wapp_dam : moteur de clearing day-ahead conforme au REMC-WA (marché régional CEDEAO).

Écrit à partir des seuls textes publics (REMC-WA, résolution 018/ERERA/25 ; description
publique de l'algorithme de couplage européen). Aucun code ni document propriétaire.
"""
from .orders import (
    BUY,
    SELL,
    BlockOrder,
    HourlyOrder,
    Link,
    Market,
    MarketParams,
    Participant,
)
from .validation import ValidationReport, validate
from .clearing import ClearingResult, clear

__version__ = "0.3.0"
__all__ = [
    "BUY", "SELL", "BlockOrder", "HourlyOrder", "Link", "Market", "MarketParams",
    "Participant", "ValidationReport", "validate", "ClearingResult", "clear",
]
