from app.parsers.parser_urls import extract_urls


def test_extract_urls_deduplicates_and_normalizes():
    text = "Visit http://example.com/path and https://example.com/path?query=1 and www.test.org/index."
    results = extract_urls(text)
    domains = {item.domain for item in results}
    assert {"example.com", "test.org"} == domains
    normalized = {item.normalized for item in results}
    assert "https://www.test.org/index" in normalized
    assert all(item.normalized.startswith("http") for item in results)


def test_extract_urls_handles_fanged_urls():
    """Test that fanged URLs are properly detected and defanged."""
    text = "Visit hxxps://example[.]com/path and hxxp://test(.)org/page and example[dot]com"
    results = extract_urls(text)
    
    domains = {item.domain for item in results}
    assert "example.com" in domains
    assert "test.org" in domains
    
    # Check that fanged URLs are normalized
    normalized_urls = {item.normalized for item in results}
    assert any("https://example.com" in url for url in normalized_urls)
    assert any("http://test.org" in url for url in normalized_urls)
    
    # Check that original fanged URLs are preserved
    original_urls = {item.original for item in results}
    assert any("hxxps://" in url or "hxxp://" in url or "[.]" in url or "(.)" in url or "[dot]" in url for url in original_urls)
    
    # All normalized URLs should use standard protocols
    assert all(item.normalized.startswith(("http://", "https://")) for item in results)
