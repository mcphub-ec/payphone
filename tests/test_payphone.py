import pytest
from decimal import Decimal
from server import _calcular_centavos, TipoMonto
import os

def test_calcular_centavos_subtotal(monkeypatch):
    monkeypatch.setenv("IVA_EC_PERCENTAGE", "0.15")
    # Base $30
    total, subtotal, iva = _calcular_centavos(30.0, TipoMonto.SUBTOTAL)
    assert subtotal == 3000
    assert iva == 450
    assert total == 3450

def test_calcular_centavos_total_con_iva(monkeypatch):
    monkeypatch.setenv("IVA_EC_PERCENTAGE", "0.15")
    # Total $34.50
    total, subtotal, iva = _calcular_centavos(34.50, TipoMonto.TOTAL_CON_IVA)
    assert total == 3450
    assert subtotal == 3000
    assert iva == 450

def test_calcular_centavos_rounding(monkeypatch):
    monkeypatch.setenv("IVA_EC_PERCENTAGE", "0.15")
    # Base $10.12 -> IVA $1.518 -> rounds to 1.52 -> Total $11.64
    total, subtotal, iva = _calcular_centavos(10.12, TipoMonto.SUBTOTAL)
    assert subtotal == 1012
    assert iva == 152
    assert total == 1164
