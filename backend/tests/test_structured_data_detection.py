import pytest

from backend.services.structured_data import detect_structured_data, validate_structured_data

LD = '<script type="application/ld+json">%s</script>'


def doc(head="", body=""):
    return f"<html><head>{head}</head><body>{body}</body></html>"


def test_json_ld_parsed_and_types_found():
    d = detect_structured_data(doc(LD % '{"@context":"https://schema.org","@type":"Organization","name":"X"}'))
    assert d["formats"] == ["json-ld"] and d["types"] == ["Organization"]


def test_invalid_json_ld_is_not_counted_as_structured_data():
    r = validate_structured_data("u", doc(LD % '{"@type": "Organization", name: }'))
    assert r["has_structured_data"] is False
    assert r["jsonld_parse_errors"] == 1


def test_graph_members_are_validated():
    r = validate_structured_data("u", doc(LD % '{"@context":"https://schema.org","@graph":[{"@type":"Product","name":"P"},{"@type":"WebSite","name":"W"}]}'))
    assert "Product" in r["types_present"] and "WebSite" in r["types_present"]
    assert r["invalid_types"] == ["Product"]  # Product without offers
    assert r["missing_required"] == {"Product": ["offers"]}


def test_microdata_counts_as_structured_data():
    r = validate_structured_data("u", doc(body='<div itemscope itemtype="https://schema.org/Product"><span itemprop="name">P</span></div>'))
    assert r["has_structured_data"] is True and r["formats"] == ["microdata"]
    assert "Product" in r["types_present"]


def test_rdfa_counts_as_structured_data():
    r = validate_structured_data("u", doc(body='<div vocab="https://schema.org/" typeof="Article"><h1 property="headline">x</h1></div>'))
    assert r["has_structured_data"] is True and r["formats"] == ["rdfa"]


def test_page_without_markup_has_none():
    assert validate_structured_data("u", doc(body="<p>hi</p>"))["has_structured_data"] is False
    assert detect_structured_data("")["formats"] == []


def test_valid_supported_type():
    r = validate_structured_data("u", doc(LD % '{"@type":"Organization","name":"X"}'))
    assert r["valid"] is True and r["invalid_types"] == []
