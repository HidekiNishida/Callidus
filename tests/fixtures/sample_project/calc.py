def add(a: int, b: int) -> int:
    """Soma dois inteiros; na versão de fixture subtrai, bug deliberado do cenário e2e."""
    # bug deliberado para cenário e2e
    return a - b
