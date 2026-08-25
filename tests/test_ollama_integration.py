import json

from document_intelligence.extraction import FinancialExtraction, check_ollama_available, extract_financial_record


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


def test_extract_financial_record_accepts_ollama_json(monkeypatch):
    def fake_urlopen(request, timeout=None):
        if request.get_method() == "GET":
            return FakeResponse({"models": [{"name": "llama3.2:3b"}]})
        payload = json.loads(request.data.decode("utf-8"))
        assert payload["model"] == "llama3.2:3b"
        assert payload["stream"] is False
        assert payload["format"] == "json"
        return FakeResponse({
            "message": {
                "content": json.dumps({
                    "fund_name": "Example Fund",
                    "reporting_period": "2024-12-31",
                    "return_percentage": 12.5,
                    "benchmark_return": 10.0,
                    "assets_under_management": 5000000.0,
                    "currency": "USD",
                    "source_filename": "example.pdf",
                })
            }
        })

    monkeypatch.setattr("document_intelligence.extraction.urlopen", fake_urlopen)

    record = extract_financial_record("sample pdf text", "example.pdf")

    assert isinstance(record, FinancialExtraction)
    assert record.fund_name == "Example Fund"
    assert record.return_percentage == 12.5
    assert record.source_filename == "example.pdf"


def test_check_ollama_available_handles_missing_server(monkeypatch):
    def fake_urlopen(request, timeout=None):
        raise OSError("connection refused")

    monkeypatch.setattr("document_intelligence.extraction.urlopen", fake_urlopen)

    assert check_ollama_available() is False


def test_extract_financial_record_normalizes_common_financial_formats(monkeypatch):
    def fake_urlopen(request, timeout=None):
        if request.get_method() == "GET":
            return FakeResponse({"models": [{"name": "llama3.2:3b"}]})
        payload = json.loads(request.data.decode("utf-8"))
        assert payload["model"] == "llama3.2:3b"
        assert payload["stream"] is False
        return FakeResponse({
            "message": {
                "content": json.dumps({
                    "fund_name": "Example Fund",
                    "reporting_period": "2024-12-31",
                    "return_percentage": "4.2%",
                    "benchmark_return": "N/A",
                    "assets_under_management": "$1.25 billion",
                    "currency": "usd",
                    "source_filename": "example.pdf",
                })
            }
        })

    monkeypatch.setattr("document_intelligence.extraction.urlopen", fake_urlopen)

    record = extract_financial_record("sample pdf text", "example.pdf")

    assert record.return_percentage == 4.2
    assert record.benchmark_return is None
    assert record.assets_under_management == 1250000000
    assert record.currency == "USD"
