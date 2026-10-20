from calc import add


def test_add():
    """A soma de 2 e 3 deve dar 5; no fixture ela falha porque add subtrai."""
    assert add(2, 3) == 5
