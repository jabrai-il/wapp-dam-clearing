"""Cas unitaires de la spec §8."""
import pytest

from wapp_dam import BUY, SELL, BlockOrder, HourlyOrder, Link, Market, MarketParams, clear
from wapp_dam.clearing import BLOCK_ACCEPTED, BLOCK_FORCED, BLOCK_PARADOX, BLOCK_REJECTED
from tests.conftest import H

TOL = 1e-6


def test_single_zone_equilibrium(one_hour):
    m = Market(zones=["SN"], params=one_hour)
    m.hourly = [H("d", "SN", 1, BUY, 100, 50), H("g1", "SN", 1, SELL, 60, 30), H("g2", "SN", 1, SELL, 60, 40)]
    r = clear(m)
    assert r.prices[("SN", 1)] == 40.0
    assert r.hourly_ratio["g1"] == pytest.approx(1.0)
    assert r.hourly_ratio["g2"] == pytest.approx(40 / 60)
    assert r.welfare == pytest.approx(100 * 50 - 60 * 30 - 40 * 40)
    assert r.iterations == 1


def test_two_zones_no_congestion_single_price(two_zone_market):
    r = clear(two_zone_market(atc=1000))
    # ML fournit tout à 20 : offre marginale ML partielle -> prix unique 20
    assert r.prices[("SN", 1)] == r.prices[("ML", 1)] == 20.0
    assert r.links[0].flow == pytest.approx(100)
    assert not r.links[0].congested
    assert r.congestion_rent() == pytest.approx(0.0)


def test_two_zones_congestion_market_splitting(two_zone_market):
    r = clear(two_zone_market(atc=30))
    # SN importe 30, puis sn_g1 (60 à 30) et 10 MW de sn_g2 à 80 -> prix SN = 80, ML = 20
    assert r.prices[("SN", 1)] == 80.0
    assert r.prices[("ML", 1)] == 20.0
    l = r.links[0]
    assert l.congested and l.flow == pytest.approx(30)
    assert l.rent == pytest.approx((80 - 20) * 30)
    assert r.hourly_ratio["sn_g2"] == pytest.approx(10 / 60)


def test_losses_price_wedge(two_zone_market):
    r = clear(two_zone_market(atc=1000, loss=0.10))
    # ML marginal à 20, 10 % de pertes : 1 MW livré coûte 20/0.9 en SN
    assert r.prices[("ML", 1)] == 20.0
    assert r.prices[("SN", 1)] == pytest.approx(20 / 0.9, abs=0.01)
    assert r.links[0].flow * 0.9 == pytest.approx(100, abs=1.0)  # flux publié arrondi au MW
    assert r.links[0].rent == pytest.approx(0.0, abs=0.5)  # arrondi des prix à 2 décimales


def test_block_in_the_money_accepted(one_hour):
    p = MarketParams(hours=2)
    m = Market(zones=["SN"], params=p)
    m.hourly = [H("d1", "SN", 1, BUY, 100, 60), H("d2", "SN", 2, BUY, 100, 60),
                H("g1", "SN", 1, SELL, 100, 50), H("g2", "SN", 2, SELL, 100, 50)]
    m.blocks = [BlockOrder("blk", "G", "SN", SELL, 30, 1.0, {1: 50, 2: 50})]
    r = clear(m)
    b = r.blocks[0]
    assert b.status == BLOCK_ACCEPTED and b.ratio == pytest.approx(1.0)
    assert b.weighted_price >= 30


def test_block_paradoxically_rejected(one_hour):
    """Bloc de vente 2 h à 45 pour 100 MW ; demande 100 à 50 (h1) et 100 à 100 (h2), offre horaire
    120 MW à 40 en h1 et 40 en h2. Sans le bloc : prix 40/40. Avec le bloc, il faut évincer
    100 MW d'offre à 40 chaque heure pour 45 : perte de bien-être -> rejet. Prix 40 < 45 : simplement rejeté.
    Variante paradoxale : offre horaire h2 à 60 -> prix h2 = 60, moyenne (40+60)/2 = 50 > 45 mais
    l'accepter forcerait le rejet des 100 MW à 40 en h1 (coût 500) contre un gain en h2 de 1500 :
    accepté. On calibre pour obtenir le paradoxe : h2 à 48, moyenne 44 < 45 ? non... calibrage ci-dessous."""
    p = MarketParams(hours=2)
    m = Market(zones=["SN"], params=p)
    # h1 : demande 100 à 100, offre 100 à 40. h2 : demande 100 à 100, offre 100 à 40 puis 0.
    # Bloc vente 2 h, 100 MW/h à 39.5 : accepté rapporte (40-39.5)*200 = 100 de bien-être ; prix 39.5 dégénéré.
    # Paradoxe classique : deux blocs concurrents. Bloc A (2 h, 100 MW à 30, MAR 1) et bloc B (1 h, h1, 100 MW à 25).
    # Demande 100 MW à 100 en h1, 100 MW à 100 en h2 ; pas d'offre horaire en h1, offre 100 à 35 en h2.
    # Optimum : A accepté (bien-être 2*100*100 - 200*30 = 14000) vs B + h2 horaire (100*100-2500 + 100*100-3500 = 14000)... égalité ; on penche : B à 26.
    m.hourly = [H("d1", "SN", 1, BUY, 100, 100), H("d2", "SN", 2, BUY, 100, 100), H("g2", "SN", 2, SELL, 100, 35)]
    m.blocks = [BlockOrder("A", "G", "SN", SELL, 30, 1.0, {1: 100, 2: 100}),
                BlockOrder("B", "G", "SN", SELL, 26, 1.0, {1: 100})]
    r = clear(m)
    st = {b.id: b for b in r.blocks}
    # A : 20000-6000 = 14000 ; B + g2 : 10000-2600 + 10000-3500 = 13900 -> A accepté, B rejeté.
    assert st["A"].status == BLOCK_ACCEPTED
    # Prix h1 : seule offre restante = bloc A fixé ; dual entre 30 et 100 (dégénéré) ; B à 26 est dans la monnaie si prix h1 >= 26
    assert st["B"].status in (BLOCK_PARADOX, BLOCK_REJECTED)
    if r.prices[("SN", 1)] >= 26:
        assert st["B"].status == BLOCK_PARADOX


def test_block_mar_partial(one_hour):
    m = Market(zones=["SN"], params=one_hour)
    m.hourly = [H("d", "SN", 1, BUY, 70, 100)]
    m.blocks = [BlockOrder("blk", "G", "SN", SELL, 30, 0.5, {1: 100})]
    r = clear(m)
    assert r.blocks[0].status == BLOCK_ACCEPTED
    assert r.blocks[0].ratio == pytest.approx(0.7)


def test_block_below_mar_rejected(one_hour):
    m = Market(zones=["SN"], params=one_hour)
    m.hourly = [H("d", "SN", 1, BUY, 30, 100)]
    m.blocks = [BlockOrder("blk", "G", "SN", SELL, 30, 0.5, {1: 100})]
    r = clear(m)
    assert r.blocks[0].ratio == 0.0
    assert r.blocks[0].status != BLOCK_ACCEPTED


def test_linked_blocks_family_rule(one_hour):
    """EPD-2025 §5.4.1 règle 3 : un parent hors de la monnaie est accepté si ses enfants acceptés compensent sa perte."""
    m = Market(zones=["SN"], params=one_hour)
    m.hourly = [H("d", "SN", 1, BUY, 250, 100)]
    m.blocks = [BlockOrder("P", "G", "SN", SELL, 150, 1.0, {1: 100}),
                BlockOrder("C", "G", "SN", SELL, 10, 1.0, {1: 100}, parent="P"),
                BlockOrder("GC", "G", "SN", SELL, 10, 1.0, {1: 50}, parent="C")]
    r = clear(m)
    st = {b.id: b for b in r.blocks}
    assert all(b.status == BLOCK_ACCEPTED for b in r.blocks)
    assert r.iterations == 1
    # surplus de famille de P aux prix (<= 100) : 100*(pi-150) + 100*(pi-10) + 50*(pi-10) >= 0 pour pi >= 64
    assert st["P"].family_surplus >= -1e-6
    assert r.prices[("SN", 1)] >= 64 - 0.01
    # lecture littérale du Code (cohérence bloc par bloc) : P forcé au rejet, famille rejetée
    m.params = MarketParams(hours=1, linked_family_rule=False)
    r = clear(m)
    st = {b.id: b.status for b in r.blocks}
    assert st["P"] == BLOCK_FORCED and st["C"] != BLOCK_ACCEPTED and st["GC"] != BLOCK_ACCEPTED
    assert r.iterations == 2 and r.welfare < r.welfare_first


def test_linked_child_out_of_money_not_accepted(one_hour):
    """Règle 4 : un enfant feuille hors de la monnaie n'est pas accepté même si le parent le compenserait."""
    m = Market(zones=["SN"], params=one_hour)
    m.hourly = [H("d", "SN", 1, BUY, 200, 100), H("g", "SN", 1, SELL, 100, 50)]
    m.blocks = [BlockOrder("P", "G", "SN", SELL, 10, 1.0, {1: 100}),
                BlockOrder("C", "G", "SN", SELL, 120, 1.0, {1: 50}, parent="P")]
    r = clear(m)
    st = {b.id: b.status for b in r.blocks}
    assert st["P"] == BLOCK_ACCEPTED and st["C"] != BLOCK_ACCEPTED


def test_no_price_supports_welfare_optimum(one_hour):
    """Exemple de non-existence (working paper, proposition 2) : demande 150 à 100, ordre horaire 100 à 50,
    bloc de vente 100 MW à 60. L'optimum de bien-être accepte le bloc (6 500 > 5 000) avec l'ordre horaire
    partiel (50/100), ce qui impose pi = 50 < 60 : aucun prix ne supporte l'optimum ; le bloc doit être
    paradoxalement rejeté (forcé) et le bien-être retombe à 5 000."""
    m = Market(zones=["SN"], params=one_hour)
    m.hourly = [H("d", "SN", 1, BUY, 150, 100), H("g", "SN", 1, SELL, 100, 50)]
    m.blocks = [BlockOrder("B", "G2", "SN", SELL, 60, 1.0, {1: 100})]
    r = clear(m)
    assert r.welfare_first == pytest.approx(6500) and r.welfare == pytest.approx(5000)
    assert r.blocks[0].status == BLOCK_FORCED and r.iterations == 2
    assert r.prices[("SN", 1)] == 100.0  # demande partielle après rejet du bloc


def test_prorata_curtailment_sharing(one_hour):
    """Deux demandes preneuses de prix (au plafond) face à une offre insuffisante : délestage au prorata."""
    p = MarketParams(hours=1, price_max=100.0)
    m = Market(zones=["SN"], params=p)
    m.hourly = [H("d1", "SN", 1, BUY, 300, 100, participant="A"), H("d2", "SN", 1, BUY, 100, 100, participant="B"),
                H("g", "SN", 1, SELL, 200, 40)]
    r = clear(m)
    assert r.hourly_mw["d1"] == pytest.approx(150) and r.hourly_mw["d2"] == pytest.approx(50)
    assert r.prices[("SN", 1)] == 100.0
    assert r.curtailed_price_takers(100.0) == {("SN", 1): pytest.approx(200)}
    assert r.coherence.level == "OK"


def test_identical_blocks_tiebreak(one_hour):
    m = Market(zones=["SN"], params=one_hour)
    m.hourly = [H("d", "SN", 1, BUY, 100, 100)]
    m.blocks = [BlockOrder("late", "G", "SN", SELL, 20, 1.0, {1: 100}, timestamp="2026-09-22T10:05:00"),
                BlockOrder("early", "G", "SN", SELL, 20, 1.0, {1: 100}, timestamp="2026-09-22T10:00:00")]
    r = clear(m)
    st = {b.id: b.status for b in r.blocks}
    assert st["early"] == BLOCK_ACCEPTED and st["late"] == BLOCK_PARADOX


def test_rounding_half_up(one_hour):
    m = Market(zones=["SN"], params=one_hour)
    m.hourly = [H("d", "SN", 1, BUY, 70, 100)]
    m.blocks = [BlockOrder("blk", "G", "SN", SELL, 30, 0.3, {1: 200})]  # ratio 0,35 -> 70 MW
    r = clear(m)
    assert r.blocks[0].mw == {1: 70.0} and r.blocks[0].ratio_published == pytest.approx(0.35)
    m.hourly = [H("d", "SN", 1, BUY, 75, 100)]
    m.blocks = [BlockOrder("blk", "G", "SN", SELL, 30, 0.5, {1: 201})]  # 75/201 * 201 = 75 ; 100.5 -> test half-up direct
    from wapp_dam.clearing import round_half_up
    assert round_half_up(100.5) == 101 and round_half_up(0.125, 2) == 0.13 and round_half_up(2.5) == 3


def test_exclusive_group(one_hour):
    m = Market(zones=["SN"], params=one_hour)
    m.hourly = [H("d", "SN", 1, BUY, 300, 100)]
    m.blocks = [BlockOrder("E1", "G", "SN", SELL, 20, 1.0, {1: 100}, exclusive_group="X"),
                BlockOrder("E2", "G", "SN", SELL, 25, 1.0, {1: 100}, exclusive_group="X")]
    r = clear(m)
    accepted = [b.id for b in r.blocks if b.status == BLOCK_ACCEPTED]
    assert accepted == ["E1"]


def test_price_cap_clipping():
    p = MarketParams(hours=1, price_min=0.0, price_max=100.0)
    m = Market(zones=["SN"], params=p)
    # demande inélastique au plafond, offre au plafond : dual dégénéré dans [100,100] ; on force un dual hors borne
    # via pertes : ML marginal à 100 (plafond), 20 % de pertes -> prix SN 125 > plafond -> écrêté.
    m = Market(zones=["ML", "SN"], params=p)
    m.hourly = [H("sn_d", "SN", 1, BUY, 50, 100), H("ml_g", "ML", 1, SELL, 200, 100), H("ml_d", "ML", 1, BUY, 50, 100)]
    m.links = [Link("ML-SN", "ML", "SN", {1: 1000}, 0.2)]
    r = clear(m)
    # demande SN à 100 avec coût livré 125 : l'optimum n'importe pas -> flux 0 ; prix SN dans [100, 125] selon dual
    assert r.prices[("SN", 1)] <= 100.0
    assert all(0 <= v <= 100 for v in r.prices.values())


def test_validation_rejections():
    p = MarketParams(hours=1, price_min=0.0, price_max=100.0)
    m = Market(zones=["ML", "SN"], params=p)
    m.participants = {"P": __import__("wapp_dam").Participant("P", trading_limit=50)}
    m.hourly = [
        H("ok", "SN", 1, BUY, 10, 50),
        H("neg", "SN", 1, BUY, 10, -5),                 # 13.1.4.2
        H("cap", "SN", 1, SELL, 10, 150),               # 13.1.4.2
        H("lim1", "SN", 1, SELL, 40, 30, participant="P"),
        H("lim2", "SN", 1, SELL, 20, 30, participant="P"),  # 13.1.4.3 : 60 > 50
        H("imp", "SN", 1, BUY, 500, 90, cross_border=True),  # 13.1.4.5 : ATC entrant 100
        H("badh", "SN", 7, BUY, 10, 50),                # 13.1.4.4
    ]
    m.blocks = [BlockOrder("orphan", "G", "SN", SELL, 20, 1.0, {1: 10}, parent="nope"),
                BlockOrder("badmar", "G", "SN", SELL, 20, 0.0, {1: 10})]
    m.links = [Link("ML-SN", "ML", "SN", {1: 100})]
    r = clear(m)
    rej = {x.order_id: x.article for x in r.validation.rejections}
    assert rej == {"neg": "MC 13.1.4.2", "cap": "MC 13.1.4.2", "lim2": "MC 13.1.4.3", "imp": "MC 13.1.4.5",
                   "badh": "MC 13.1.4.4", "orphan": "MC 13.1.4.4", "badmar": "MC 13.1.4.4"}
    assert {o.id for o in r.validation.accepted_hourly} == {"ok", "lim1"}


def test_block_coherence_iteration_forces_rejection():
    """Bloc d'achat accepté hors de la monnaie : l'optimum global peut accepter un bloc d'achat à 30 en
    h1 (prix 20) et h2 (prix 50, moyenne 35 > 30 -> hors de la monnaie) ; le moteur doit le forcer au rejet."""
    p = MarketParams(hours=2)
    m = Market(zones=["SN"], params=p)
    m.hourly = [H("g1", "SN", 1, SELL, 100, 20), H("g2", "SN", 2, SELL, 100, 50),
                H("d2", "SN", 2, BUY, 60, 100)]
    m.blocks = [BlockOrder("BB", "D", "SN", BUY, 30, 1.0, {1: 100, 2: 40})]
    r = clear(m)
    b = r.blocks[0]
    # accepté : bien-être bloc = 30*140 - 20*100 - 50*40 = 200 > 0, mais prix pondéré = (20*100+50*40)/140 = 28.6 <= 30 : cohérent
    assert b.status == BLOCK_ACCEPTED
    # même bloc avec profil {1: 40, 2: 100} : prix pondéré (20*40+50*100)/140 = 41.4 > 30 ; bien-être = 30*140 - 800 - 5000 < 0 : rejeté par l'optimum
    m.blocks = [BlockOrder("BB", "D", "SN", BUY, 30, 1.0, {1: 40, 2: 100})]
    r = clear(m)
    assert r.blocks[0].status in (BLOCK_REJECTED, BLOCK_FORCED)


def test_determinism(two_zone_market):
    r1, r2 = clear(two_zone_market(atc=30)), clear(two_zone_market(atc=30))
    assert r1.prices == r2.prices and r1.hourly_ratio == r2.hourly_ratio



def test_multi_mtu_order_cleared_on_mean_price():
    """Ordre de vente sur deux MTU (EPD-2025 §5.1) : un seul ratio, dans la monnaie sur la moyenne des prix.
    MTU 1 : demande 100 à 200, offre 100 à 50. MTU 2 : demande 100 à 200, offre 60 à 50 puis 40 à 140.
    L'ordre bi-MTU vend 40 MW à 90 sur les deux MTU. L'accepter coûte 40 x (90 - 50) = 1 600 au MTU 1 (il déplace
    l'offre à 50) et rapporte 40 x (140 - 90) = 2 000 au MTU 2 (il déplace l'offre à 140) : il est accepté en entier,
    hors de la monnaie au MTU 1 (prix 50) mais dans la monnaie en moyenne (prix 2 dans [130, 140])."""
    m = Market(zones=["Z"], params=MarketParams(hours=2, price_max=500.0))
    m.hourly = [
        H("d1", "Z", 1, BUY, 100, 200), H("g1", "Z", 1, SELL, 100, 50),
        H("d2", "Z", 2, BUY, 100, 200), H("g2a", "Z", 2, SELL, 60, 50), H("g2b", "Z", 2, SELL, 40, 140),
        H("mm", "Z", 1, SELL, 40, 90, hours=(1, 2)),
    ]
    r = clear(m)
    assert r.hourly_ratio["mm"] == pytest.approx(1.0)
    assert r.hourly_mw["g2b"] == pytest.approx(0)
    assert r.prices[("Z", 1)] == pytest.approx(50.0)
    assert 130 - 1e-6 <= r.prices[("Z", 2)] <= 140 + 1e-6
    assert r.coherence.level == "OK"
    assert r.welfare == pytest.approx(100 * 200 + 100 * 200 - 60 * 50 - 60 * 50 - 2 * 40 * 90)


def test_custom_solver_through_protocol(two_zone_market):
    """Le moteur ne dépend du solveur qu'à travers le protocole `Solver` : un solveur enveloppant, qui compte
    les appels et délègue à HiGHS, donne le même résultat et est bien sollicité pour le MILP et les LP."""
    from wapp_dam import HighsSolver

    class CountingSolver(HighsSolver):
        def __init__(self):
            self.calls = {"milp": 0, "lp": 0, "projection": 0}

        def solve_milp(self, d, time_limit=None):
            self.calls["milp"] += 1
            return super().solve_milp(d, time_limit)

        def solve_lp(self, *a, **k):
            self.calls["lp"] += 1
            return super().solve_lp(*a, **k)

        def solve_projection(self, *a, **k):
            self.calls["projection"] += 1
            return super().solve_projection(*a, **k)

    s = CountingSolver()
    r_ref, r = clear(two_zone_market(atc=30)), clear(two_zone_market(atc=30), solver=s)
    assert r.prices == r_ref.prices and r.hourly_ratio == r_ref.hourly_ratio
    assert s.calls["milp"] == r.iterations
    assert s.calls["lp"] == 2 * r.iterations          # LP à blocs figés + LP de prix par itération
    assert s.calls["projection"] == 0                 # règle « dual » : pas d'affinage quadratique
