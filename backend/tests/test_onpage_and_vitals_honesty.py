import pytest

from backend.services import single_page_service as sp
from backend.services.single_page_service import evaluate_onpage_score, onpage_checks

GOOD_TITLE = "A clear descriptive page title here"          # 35 chars
GOOD_DESC = "A useful meta description that explains the page to searchers in a sensible number of characters."


def test_perfect_page_scores_100_and_empty_page_scores_0():
    assert evaluate_onpage_score(GOOD_TITLE, GOOD_DESC, "Heading", "a photo") == 100
    assert evaluate_onpage_score("", "", "", "") == 0


def test_score_is_share_of_checklist_passed():
    # title present + right length (2 of 6) only
    assert evaluate_onpage_score(GOOD_TITLE, "", "", "") == round(100 * 2 / 6)
    # present but out of range passes "present" and fails "length" - no partial-credit buckets
    checks = {c["check"]: c["passed"] for c in onpage_checks("x" * 80, GOOD_DESC, "H", "alt")}
    assert checks["title_present"] and not checks["title_length"]


def test_robots_and_llms_files_no_longer_add_free_points():
    base = evaluate_onpage_score("", "", "", "")
    assert evaluate_onpage_score("", "", "", "", robots_txt="User-agent: *", llms_txt="# site") == base == 0


def test_no_invented_vitals_constants_remain():
    import inspect

    from backend.services.snapshots import comparison_view

    for mod in (sp, comparison_view):
        src = inspect.getsource(mod)
        assert "old_vitals = 56" not in src
        assert "old_vitals + 12" not in src
