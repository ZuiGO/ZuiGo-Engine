import logging

from backend.logging_setup import RedactSecretsFilter


def _render(msg, *args):
    record = logging.LogRecord("t", logging.INFO, __file__, 1, msg, args, None)
    assert RedactSecretsFilter().filter(record)
    return record.getMessage()


def test_redacts_api_key_in_url():
    out = _render("HTTP Request: GET https://serpapi.com/search?api_key=SECRET123&q=a")
    assert "SECRET123" not in out
    assert "api_key=[REDACTED]&q=a" in out


def test_redacts_google_key_and_args_style_logging():
    out = _render("GET %s", "https://x.googleapis.com/v5?url=a&key=AIzaFAKE&strategy=mobile")
    assert "AIzaFAKE" not in out
    assert "strategy=mobile" in out


def test_leaves_normal_messages_alone():
    assert _render("crawled %d pages in %s", 5, "2s") == "crawled 5 pages in 2s"
