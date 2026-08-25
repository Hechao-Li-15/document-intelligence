import json

from document_intelligence.question_answering import answer_question_from_records


def test_specific_fund_date_question_uses_database_record(monkeypatch):
    class FakeResponse:
        def __init__(self, payload):
            self.payload = payload

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return json.dumps(self.payload).encode("utf-8")

    def fake_urlopen(request, timeout=None):
        return FakeResponse({
            "message": {
                "content": "Pacific Opportunities Fund for January 2026 had a return of 3.3%, a benchmark return of 2.9%, AUM of $680 million, and currency USD."
            }
        })

    monkeypatch.setattr("document_intelligence.extraction.urlopen", fake_urlopen)
    monkeypatch.setattr("document_intelligence.extraction.check_ollama_available", lambda: True)

    records = [{
        "fund_name": "Pacific Opportunities Fund",
        "reporting_period": "January 2026",
        "return_percentage": 3.3,
        "benchmark_return": 2.9,
        "assets_under_management": 680000000,
        "currency": "USD",
        "source_filename": "Pacific_Opportunities_Fund_January_2026.pdf",
    }]

    answer, sources = answer_question_from_records("Tell me about Pacific Opportunities Fund 01/2026", records)

    assert "3.3" in answer
    assert "2.9" in answer
    assert "680" in answer or "$680" in answer
    assert "USD" in answer
    assert sources == ["Pacific_Opportunities_Fund_January_2026.pdf"]
    assert "I couldn't find" not in answer


def test_alpha_growth_fund_question_uses_exact_database_row(monkeypatch):
    class FakeResponse:
        def __init__(self, payload):
            self.payload = payload

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return json.dumps(self.payload).encode("utf-8")

    def fake_urlopen(request, timeout=None):
        return FakeResponse({
            "message": {
                "content": "Alpha Growth Fund for January 2026 had a return of 4.2%, a benchmark return of 3.5%, AUM of $1.25 billion, and currency USD."
            }
        })

    monkeypatch.setattr("document_intelligence.extraction.urlopen", fake_urlopen)
    monkeypatch.setattr("document_intelligence.extraction.check_ollama_available", lambda: True)

    records = [
        {
            "fund_name": "Global Equity Fund",
            "reporting_period": "January 2026",
            "return_percentage": 2.8,
            "benchmark_return": 2.4,
            "assets_under_management": 980000000,
            "currency": "USD",
            "source_filename": "Global_Equity_Fund_January_2026.pdf",
        },
        {
            "fund_name": "Alpha Growth Fund",
            "reporting_period": "January 2026",
            "return_percentage": 4.2,
            "benchmark_return": 3.5,
            "assets_under_management": 1250000000,
            "currency": "USD",
            "source_filename": "Alpha_Growth_Fund_January_2026.pdf",
        },
    ]

    answer, sources = answer_question_from_records("tell me about Alpha Growth fund", records)

    assert "Alpha Growth Fund" in answer
    assert "4.2" in answer
    assert "3.5" in answer
    assert "$1.25 billion" in answer or "1.25 billion" in answer
    assert "USD" in answer
    assert sources == ["Alpha_Growth_Fund_January_2026.pdf"]
    assert "Global_Equity_Fund_January_2026.pdf" not in ", ".join(sources)


def test_best_january_return_is_determined_from_database(monkeypatch):
    class FakeResponse:
        def __init__(self, payload):
            self.payload = payload

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return json.dumps(self.payload).encode("utf-8")

    def fake_urlopen(request, timeout=None):
        return FakeResponse({"message": {"content": "Pacific Opportunities Fund had the best return at 3.3%."}})

    monkeypatch.setattr("document_intelligence.extraction.urlopen", fake_urlopen)
    monkeypatch.setattr("document_intelligence.extraction.check_ollama_available", lambda: True)

    records = [
        {"fund_name": "Alpha Fund", "reporting_period": "January 2026", "return_percentage": 2.1, "source_filename": "alpha.pdf"},
        {"fund_name": "Pacific Opportunities Fund", "reporting_period": "January 2026", "return_percentage": 3.3, "source_filename": "pacific.pdf"},
        {"fund_name": "Beta Fund", "reporting_period": "January 2026", "return_percentage": 1.8, "source_filename": "beta.pdf"},
    ]

    answer, sources = answer_question_from_records("Which fund had the best January 2026 return?", records)

    assert "Pacific Opportunities Fund" in answer
    assert "3.3" in answer
    assert "pacific.pdf" in ", ".join(sources)


def test_specific_pacific_fund_question_uses_exact_database_row(monkeypatch):
    class FakeResponse:
        def __init__(self, payload):
            self.payload = payload

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return json.dumps(self.payload).encode("utf-8")

    def fake_urlopen(request, timeout=None):
        return FakeResponse({
            "message": {
                "content": "Pacific Opportunities Fund for January 2026 had a return of 3.3%, a benchmark return of 2.9%, AUM of $680 million, and currency USD."
            }
        })

    monkeypatch.setattr("document_intelligence.extraction.urlopen", fake_urlopen)
    monkeypatch.setattr("document_intelligence.extraction.check_ollama_available", lambda: True)

    records = [
        {
            "fund_name": "Global Equity Fund",
            "reporting_period": "January 2026",
            "return_percentage": 2.8,
            "benchmark_return": 2.4,
            "assets_under_management": 980000000,
            "currency": "USD",
            "source_filename": "Global_Equity_Fund_January_2026.pdf",
        },
        {
            "fund_name": "Pacific Opportunities Fund",
            "reporting_period": "January 2026",
            "return_percentage": 3.3,
            "benchmark_return": 2.9,
            "assets_under_management": 680000000,
            "currency": "USD",
            "source_filename": "Pacific_Opportunities_Fund_January_2026.pdf",
        },
    ]

    answer, sources = answer_question_from_records("tell me about Pacific Opportunities Fund", records)

    assert "Pacific Opportunities Fund" in answer
    assert "3.3" in answer
    assert "2.9" in answer
    assert "USD" in answer
    assert sources == ["Pacific_Opportunities_Fund_January_2026.pdf"]
    assert "Global_Equity_Fund_January_2026.pdf" not in ", ".join(sources)
