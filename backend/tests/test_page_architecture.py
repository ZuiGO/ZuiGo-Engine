import json

from backend.services.page_architecture import build_product_architecture


def _page(url, title, crumbs=None):
    html = ""
    if crumbs:
        items = [
            {"@type": "ListItem", "position": index, "name": name, "item": href}
            for index, (name, href) in enumerate(crumbs, start=1)
        ]
        html = '<script type="application/ld+json">' + json.dumps(
            {"@context": "https://schema.org", "@type": "BreadcrumbList", "itemListElement": items}
        ) + "</script>"
    return {"url": url, "title": title, "status_code": 200, "html": html}


def test_breadcrumbs_create_family_category_model_tree():
    base = "https://shop.example"
    pages = [
        _page(
            f"{base}/products/tube-fittings-and-connectors",
            "Tube fittings",
            [("Home", base), ("Products", f"{base}/products"), ("Tube Fittings & Connectors", f"{base}/products/tube-fittings-and-connectors")],
        ),
        _page(
            f"{base}/products/caps-plugs-and-closures",
            "Caps, plugs & closures",
            [("Home", base), ("Products", f"{base}/products"), ("Tube Fittings & Connectors", f"{base}/products/tube-fittings-and-connectors"), ("Caps, plugs & closures", f"{base}/products/caps-plugs-and-closures")],
        ),
        _page(
            f"{base}/products/caps-plugs-and-closures/coupling-cap",
            "Coupling cap",
            [("Home", base), ("Products", f"{base}/products"), ("Tube Fittings & Connectors", f"{base}/products/tube-fittings-and-connectors"), ("Caps, plugs & closures", f"{base}/products/caps-plugs-and-closures"), ("Coupling cap", f"{base}/products/caps-plugs-and-closures/coupling-cap")],
        ),
        _page(f"{base}/about", "About us"),
    ]

    architecture = build_product_architecture(pages)

    assert architecture["summary"] == {
        "product_pages": 3,
        "families": 1,
        "categories": 1,
        "model_pages": 1,
        "leaf_categories": 0,
        "from_breadcrumbs": 3,
        "from_url_fallback": 0,
        "unclassified": 0,
    }
    family = architecture["families"][0]
    assert family["name"] == "Tube Fittings & Connectors"
    assert family["source"] == "breadcrumb"
    assert family["categories"][0]["name"] == "Caps, plugs & closures"
    assert family["categories"][0]["models"] == [{
        "name": "Coupling cap",
        "url": f"{base}/products/caps-plugs-and-closures/coupling-cap",
        "source": "breadcrumb",
    }]


def test_category_product_page_is_not_reported_as_a_missing_model():
    base = "https://fluidcontrols.example"
    architecture = build_product_architecture([
        _page(
            f"{base}/products/hose-connectors",
            "Hose connectors",
            [("Home", base), ("Products", f"{base}/products"), ("Hoses", f"{base}/products/hoses"), ("Hose Connectors", f"{base}/products/hose-connectors")],
        )
    ])

    category = architecture["families"][0]["categories"][0]
    assert category["is_leaf_product"] is True
    assert category["models"] == []
    assert architecture["summary"]["leaf_categories"] == 1


def test_url_fallback_is_marked_and_query_duplicates_are_ignored():
    base = "https://fluidcontrols.example"
    architecture = build_product_architecture([
        _page(f"{base}/products/valves/ball/standard", "Standard ball valve"),
        _page(f"{base}/products/valves/ball/standard?ref=nav", "Standard ball valve"),
        _page(f"{base}/products/valves/ball", "Ball valves"),
    ])

    assert architecture["summary"]["product_pages"] == 2
    assert architecture["summary"]["from_url_fallback"] == 2
    family = architecture["families"][0]
    assert family["name"] == "Valves"
    assert family["source"] == "url_fallback"
    assert family["categories"][0]["models"][0]["name"] == "Standard ball valve"
