import pytest

from agent import calculate_damage_value


def test_calculate_damage_applies_bonus_and_multiplier() -> None:
    assert calculate_damage_value(100, 25, 2) == pytest.approx(250)


def test_calculate_damage_rejects_negative_values() -> None:
    with pytest.raises(ValueError):
        calculate_damage_value(-1, 0)

    with pytest.raises(ValueError):
        calculate_damage_value(100, 0, -1)
