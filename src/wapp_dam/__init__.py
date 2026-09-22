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
from .clearing import Clearing, ClearingResult, clear
from .prices import PriceDeterminer, determine_prices
from .solvers import HighsSolver, Solver

__version__ = "0.5.0"
__all__ = [
    "BUY", "SELL", "BlockOrder", "HourlyOrder", "Link", "Market", "MarketParams",
    "Participant", "ValidationReport", "validate", "ClearingResult", "clear", "Clearing",
    "PriceDeterminer", "determine_prices", "Solver", "HighsSolver",
]
