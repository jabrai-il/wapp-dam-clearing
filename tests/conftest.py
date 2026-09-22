import pytest

from wapp_dam import BUY, SELL, HourlyOrder, Link, Market, MarketParams


def H(id, zone, hour, side, q, p, participant=None, **kw):
    return HourlyOrder(id, participant or ("D" if side == BUY else "G"), zone, hour, side, q, p, **kw)


@pytest.fixture
def one_hour():
    return MarketParams(hours=1, price_max=500.0)


@pytest.fixture
def two_zone_market(one_hour):
    """SN : demande 100 MW à 100 ; offre 60 MW à 30 et 60 MW à 80.
    ML : demande 50 MW à 100 ; offre 200 MW à 20.  Liaison ML -> SN."""
    def make(atc, loss=0.0):
        m = Market(zones=["ML", "SN"], params=one_hour)
        m.hourly = [
            H("sn_d", "SN", 1, BUY, 100, 100), H("sn_g1", "SN", 1, SELL, 60, 30), H("sn_g2", "SN", 1, SELL, 60, 80),
            H("ml_d", "ML", 1, BUY, 50, 100), H("ml_g", "ML", 1, SELL, 200, 20),
        ]
        m.links = [Link("ML-SN", "ML", "SN", {1: atc}, loss)]
        return m
    return make
