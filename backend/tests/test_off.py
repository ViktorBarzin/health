"""Pure Open Food Facts product → Food mapping (no network, no DB).

The OFF API returns macros **per 100 g** (``energy-kcal_100g`` etc.). This module
maps one OFF v2 product payload into the fields of a shared ``source='off'`` Food
whose serving is **100 g** (so the stored per-serving macros ARE the per-100g
values, no unit guesswork), or rejects it when the macros are missing/garbage so
we never write a useless Food. These tests pin that mapping and its rejections;
the network fetch + cache behaviour is tested separately (mocked HTTP) in
``test_off_lookup.py``.
"""

import pytest

from app.services.off import (
    OffMappingError,
    map_off_product,
)


def _product(**overrides):
    """A minimal well-formed OFF v2 product payload (Nutella-shaped)."""
    product = {
        "product_name": "Nutella",
        "brands": "Ferrero",
        "nutriments": {
            "energy-kcal_100g": 539,
            "proteins_100g": 6.7,
            "carbohydrates_100g": 57.5,
            "fat_100g": 30.9,
        },
    }
    product.update(overrides)
    return product


def test_maps_per_100g_nutriments_to_a_100g_serving_food() -> None:
    mapped = map_off_product("3017624010701", _product())
    assert mapped.off_id == "3017624010701"
    assert mapped.name == "Nutella"
    assert mapped.brand == "Ferrero"
    # OFF macros are per 100 g, so the Food's serving is 100 g and its
    # per-serving macros are exactly the per-100g values.
    assert mapped.serving_size == 100.0
    assert mapped.serving_unit == "g"
    assert mapped.calories == 539
    assert mapped.protein_g == 6.7
    assert mapped.carbs_g == 57.5
    assert mapped.fat_g == 30.9
    assert mapped.source == "off"


def test_slug_is_namespaced_by_barcode_and_stable() -> None:
    # The slug must be deterministic from the barcode (the natural key for an OFF
    # cache row) so two maps of the same product collide on the unique index.
    a = map_off_product("3017624010701", _product())
    b = map_off_product("3017624010701", _product(product_name="Nutella (relabel)"))
    assert a.slug == b.slug
    assert "3017624010701" in a.slug


def test_blank_product_name_falls_back_to_barcode_label() -> None:
    mapped = map_off_product("123456", _product(product_name=""))
    # Never an empty name; a barcode-derived label keeps the row identifiable.
    assert mapped.name
    assert "123456" in mapped.name


def test_missing_brand_is_none() -> None:
    p = _product()
    del p["brands"]
    mapped = map_off_product("3017624010701", p)
    assert mapped.brand is None


def test_blank_brand_is_none() -> None:
    mapped = map_off_product("3017624010701", _product(brands="  "))
    assert mapped.brand is None


def test_missing_energy_rejected() -> None:
    p = _product()
    del p["nutriments"]["energy-kcal_100g"]
    with pytest.raises(OffMappingError):
        map_off_product("3017624010701", p)


def test_missing_a_macro_rejected() -> None:
    # Protein missing → we can't store honest macros → reject (don't default to 0).
    p = _product()
    del p["nutriments"]["proteins_100g"]
    with pytest.raises(OffMappingError):
        map_off_product("3017624010701", p)


def test_empty_nutriments_rejected() -> None:
    with pytest.raises(OffMappingError):
        map_off_product("3017624010701", _product(nutriments={}))


def test_non_numeric_macro_rejected() -> None:
    p = _product()
    p["nutriments"]["fat_100g"] = "lots"
    with pytest.raises(OffMappingError):
        map_off_product("3017624010701", p)


def test_negative_energy_rejected() -> None:
    p = _product()
    p["nutriments"]["energy-kcal_100g"] = -5
    with pytest.raises(OffMappingError):
        map_off_product("3017624010701", p)


def test_string_numeric_macros_coerced() -> None:
    # OFF sometimes returns numbers as strings; accept when they parse cleanly.
    p = _product()
    p["nutriments"]["proteins_100g"] = "6.7"
    p["nutriments"]["energy-kcal_100g"] = "539"
    mapped = map_off_product("3017624010701", p)
    assert mapped.protein_g == 6.7
    assert mapped.calories == 539.0
