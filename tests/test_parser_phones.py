from app.parsers.parser_phones import extract_phone_numbers


def test_extract_phone_numbers_returns_e164():
    text = "Call us at (888) 111-1111 or +1 202-555-0199 today."
    results = extract_phone_numbers(text)
    assert {item.e164 for item in results} == {"+18881111111", "+12025550199"}

