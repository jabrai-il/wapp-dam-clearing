"""Objets du modèle (spec §3.1, REMC-WA MC 13.1.2.1 et MC 13.1.3.1)."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping, Optional

BUY = +1
SELL = -1


@dataclass(frozen=True)
class HourlyOrder:
    """Ordre horaire : une heure, une quantité (MW), un prix limite (USD/MWh).

    Traité comme une marche (acceptation partielle au prorata, spec §3.1).
    """
    id: str
    participant: str
    zone: str
    hour: int            # 1..H (MTU horaire, MC 10.3.3.2)
    side: int            # BUY (+1) ou SELL (-1)
    quantity: float      # MW, >= 0
    price: float         # USD/MWh
    cross_border: bool = False  # intention d'import/export déclarée (contrôle MC 13.1.4.5)
    timestamp: Optional[str] = None  # horodatage de dernière modification (départage, EPD-2025 §5.4.4)
    hours: Optional[tuple[int, ...]] = None  # MTU couverts si l'ordre porte sur plusieurs MTU (ex. ordre 60 min sur
                                             # un marché au quart d'heure) : un seul ratio, dans la monnaie sur la
                                             # moyenne arithmétique des prix des MTU (EPD-2025 §5.1). None = (hour,).

    @property
    def mtus(self) -> tuple[int, ...]:
        return tuple(self.hours) if self.hours else (self.hour,)

    @property
    def n_mtu(self) -> int:
        return len(self.mtus)


@dataclass(frozen=True)
class BlockOrder:
    """Ordre en bloc : prix unique, ratio minimal d'acceptation, profil horaire (MC 13.1.2.1 b-d)."""
    id: str
    participant: str
    zone: str
    side: int
    price: float
    mar: float                       # ratio minimal d'acceptation, dans ]0, 1]
    profile: Mapping[int, float]     # heure -> MW (>= 0), heures consécutives
    parent: Optional[str] = None     # bloc parent (bloc lié, MC 13.1.2.1 c)
    exclusive_group: Optional[str] = None  # groupe exclusif (MC 13.1.2.1 d)
    timestamp: Optional[str] = None        # horodatage de dernière modification (départage)

    @property
    def hours(self) -> tuple[int, ...]:
        return tuple(sorted(self.profile))

    @property
    def volume(self) -> float:
        return float(sum(self.profile.values()))


@dataclass(frozen=True)
class Link:
    """Interconnexion orientée zone -> zone, ATC par heure (MC 16.1), facteur de pertes (MC 13.5.3)."""
    id: str
    from_zone: str
    to_zone: str
    atc: Mapping[int, float]         # heure -> MW disponible
    loss_factor: float = 0.0         # part perdue en transit, dans [0, 1[


@dataclass(frozen=True)
class Participant:
    id: str
    trading_limit: Optional[float] = None  # MW max par heure, tous ordres confondus (MC 13.1.4.3)


@dataclass
class MarketParams:
    """Paramètres de l'enchère (bornes ARREC MC 10.3.4, écrêtage MC 15.3.5, algorithme spec §4.6)."""
    hours: int = 24
    price_min: float = 0.0
    price_max: float = 500.0         # à fixer : 50 % du coût de l'énergie non servie (MC 10.3.4)
    block_fix_max_iter: int = 20     # bornes de l'itération de fixation des blocs
    tolerance: float = 1e-6          # tolérance numérique (MW, USD)
    price_decimals: int = 2          # MC 13.1.3.2
    time_limit_s: Optional[float] = None
    round_volumes: bool = True       # volumes publiés en MW entiers, arrondi half-up (MC 13.1.3.2, EPD-2025 §8.1)
    prorata_ties: bool = True        # départage au prorata des ordres horaires à la monnaie (partage du délestage)
    linked_family_rule: bool = True  # règles de famille des blocs liés (EPD-2025 §5.4.1) ; sinon cohérence bloc par bloc
    force_one_at_a_time: bool = True # itération de cohérence : un seul bloc forcé au rejet par itération (le plus incohérent)
    price_rule: str = "dual"         # levée de l'indétermination des prix : "dual" (au plus près du dual du solveur)
                                     # ou "midpoint" (au plus près du milieu de l'intervalle admissible de chaque
                                     # (zone, MTU), au sens des moindres carrés, EPD-2025 annexe C)
    tol_technical: float = 1e-3      # niveaux du rapport de cohérence (EPD-2025 §8.2)
    tol_decoupling: float = 1e-1


@dataclass
class Market:
    zones: list[str]
    hourly: list[HourlyOrder] = field(default_factory=list)
    blocks: list[BlockOrder] = field(default_factory=list)
    links: list[Link] = field(default_factory=list)
    participants: dict[str, Participant] = field(default_factory=dict)
    params: MarketParams = field(default_factory=MarketParams)

    @property
    def hour_range(self) -> range:
        return range(1, self.params.hours + 1)
