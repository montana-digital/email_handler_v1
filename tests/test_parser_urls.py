from app.parsers.parser_urls import extract_urls


def test_extract_urls_deduplicates_and_normalizes():
    text = "Visit http://example.com/path and https://example.com/path?query=1 and www.test.org/index."
    results = extract_urls(text)
    domains = {item.domain for item in results}
    assert {"example.com", "test.org"} == domains
    normalized = {item.normalized for item in results}
    assert "https://www.test.org/index" in normalized
    assert all(item.normalized.startswith("http") for item in results)

