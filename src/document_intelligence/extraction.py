"""PDF text extraction and structured financial extraction with local Ollama."""

import json
import os
import re
from urllib.request import Request, urlopen

import fitz
from pydantic import BaseModel, Field, ValidationError


OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.2:3b")


class FinancialExtraction(BaseModel):
	"""Nullable normalized fields returned by the extraction model."""

	fund_name: str | None = None
	reporting_period: str | None = None
	return_percentage: float | None = None
	benchmark_return: float | None = None
	assets_under_management: float | None = None
	currency: str | None = None
	source_filename: str = Field(description="Original source filename")


def extract_pdf_text(content: bytes) -> str:
	"""Extract text from a PDF byte string."""
	with fitz.open(stream=content, filetype="pdf") as document:
		text = "\n".join(page.get_text() for page in document).strip()
	if not text:
		raise ValueError("The PDF contains no extractable text.")
	return text


def check_ollama_available() -> bool:
	"""Return True when the local Ollama API is responding."""
	try:
		request = Request(f"{OLLAMA_BASE_URL}/api/tags", method="GET")
		with urlopen(request, timeout=5) as response:
			payload = json.loads(response.read().decode("utf-8"))
		return isinstance(payload, dict) and "models" in payload
	except Exception:
		return False


def _extract_json_from_text(text: str) -> dict:
	"""Extract a JSON object from Ollama output even if it includes markdown fences."""
	cleaned = text.strip()
	match = re.search(r"```(?:json)?\s*(.*?)\s*```", cleaned, flags=re.IGNORECASE | re.DOTALL)
	if match:
		cleaned = match.group(1).strip()
	if not cleaned:
		raise ValueError("Ollama returned an empty response.")
	try:
		payload = json.loads(cleaned)
	except json.JSONDecodeError:
		start_index = cleaned.find("{")
		end_index = cleaned.rfind("}")
		if start_index == -1 or end_index <= start_index:
			raise ValueError("Ollama returned invalid JSON for financial extraction.")
		payload = json.loads(cleaned[start_index : end_index + 1])
	if not isinstance(payload, dict):
		raise ValueError("Ollama did not return a JSON object for the financial record.")
	return payload


def _normalize_missing(value):
	"""Convert empty or placeholder strings into None."""
	if value is None:
		return None
	if isinstance(value, str):
		cleaned = value.strip()
		if cleaned == "" or cleaned.lower() in {"null", "none", "n/a", "na", "n.a", "-", "--"}:
			return None
		return cleaned
	return value


def _normalize_currency(value):
	"""Normalize currency labels to uppercase ISO-like codes when present."""
	cleaned = _normalize_missing(value)
	if cleaned is None:
		return None
	text = str(cleaned).strip().upper().replace("USD", "USD").replace("US DOLLAR", "USD")
	if text in {"USD", "US DOLLAR", "$"}:
		return "USD"
	if text in {"EUR", "€"}:
		return "EUR"
	if text in {"GBP", "£"}:
		return "GBP"
	if text in {"AUD", "A$"}:
		return "AUD"
	if text in {"CAD", "C$"}:
		return "CAD"
	if text in {"JPY", "¥"}:
		return "JPY"
	if text in {"CHF"}:
		return "CHF"
	if text.startswith("$") or text.startswith("USD"):
		return "USD"
	if text.startswith("€"):
		return "EUR"
	if text.startswith("£"):
		return "GBP"
	if text.startswith("¥"):
		return "JPY"
	return text


def _normalize_numeric(value):
	"""Normalize numeric strings to float values; keep None for blank or missing fields."""
	cleaned = _normalize_missing(value)
	if cleaned is None:
		return None
	if isinstance(cleaned, (int, float)) and not isinstance(cleaned, bool):
		return float(cleaned)
	text = str(cleaned).strip()
	if not text:
		return None
	text = text.replace("%", "").replace("$", "").replace("€", "").replace("£", "").replace("¥", "")
	text = text.replace("USD", "").replace("EUR", "").replace("GBP", "").replace("AUD", "").replace("CAD", "").replace("JPY", "")
	text = text.replace("_", " ")
	text = text.replace(" ", "")
	if not text:
		return None
	multiplier = 1.0
	lower = text.lower()
	if lower.endswith("m"):
		multiplier = 1_000_000.0
		text = text[:-1]
	elif lower.endswith("b"):
		multiplier = 1_000_000_000.0
		text = text[:-1]
	elif "million" in lower:
		multiplier = 1_000_000.0
		text = text.lower().replace("million", "")
	elif "billion" in lower:
		multiplier = 1_000_000_000.0
		text = text.lower().replace("billion", "")
	text = text.replace(",", "")
	try:
		return float(text) * multiplier
	except ValueError:
		match = re.search(r"[-+]?\d*\.?\d+(?:e[-+]?\d+)?", text)
		if match is None:
			raise ValueError(f"Unable to parse numeric value: {value!r}")
		return float(match.group(0)) * multiplier


def _normalize_ollama_payload(payload: dict, filename: str) -> dict:
	"""Normalize common financial formatting before Pydantic validation."""
	if not isinstance(payload, dict):
		raise ValueError("Ollama did not return a JSON object for the financial record.")
	normalized = dict(payload)
	normalized["source_filename"] = filename
	for field in ("fund_name", "reporting_period", "currency"):
		if field in normalized:
			normalized[field] = _normalize_missing(normalized[field])
		if field == "currency" and normalized[field] is not None:
			normalized[field] = _normalize_currency(normalized[field])
	if "fund_name" in normalized and normalized["fund_name"] is not None:
		normalized["fund_name"] = str(normalized["fund_name"]).strip() or None
	if "reporting_period" in normalized and normalized["reporting_period"] is not None:
		normalized["reporting_period"] = str(normalized["reporting_period"]).strip() or None
	for field in ("return_percentage", "benchmark_return", "assets_under_management"):
		if field in normalized:
			normalized[field] = _normalize_missing(normalized[field])
		if field in normalized and normalized[field] is not None:
			normalized[field] = _normalize_numeric(normalized[field])
	return normalized


def _ollama_chat(prompt: str, system_prompt: str, *, use_json: bool = False) -> str:
	"""Call the local Ollama chat API and return the model text response."""
	if not check_ollama_available():
		raise RuntimeError("Ollama is not running. Start the local service and ensure http://localhost:11434 is reachable.")
	payload = {
		"model": OLLAMA_MODEL,
		"messages": [
			{"role": "system", "content": system_prompt},
			{"role": "user", "content": prompt},
		],
		"stream": False,
	}
	if use_json:
		payload["format"] = "json"
	request = Request(
		f"{OLLAMA_BASE_URL}/api/chat",
		data=json.dumps(payload).encode("utf-8"),
		headers={"Content-Type": "application/json"},
		method="POST",
	)
	with urlopen(request, timeout=60) as response:
		result = json.loads(response.read().decode("utf-8"))
	content = result.get("message", {}).get("content", "")
	if not content:
		raise ValueError("Ollama returned no chat content.")
	return content


def extract_financial_record(text: str, filename: str) -> FinancialExtraction:
	"""Extract a typed financial record from PDF text using the local Ollama model."""
	if not check_ollama_available():
		raise RuntimeError("Ollama is not running. Start the local service and ensure http://localhost:11434 is reachable.")
	prompt = (
		f"Filename: {filename}\n\n"
		"Extract only explicit financial values from the document text below. "
		"Use null for missing values. Never invent values. "
		"Return valid JSON only with numeric values for numeric fields. "
		"Percentages must be numbers like 4.2, not '4.2%'. "
		"Amounts must be raw numbers like 1250000000, not '$1.25 billion'. "
		"Convert million/billion suffixes to numeric values. "
		"Example field format: {\"return_percentage\": 4.2, \"assets_under_management\": 1250000000}. "
		"Return exactly these keys when present: "
		"fund_name, reporting_period, return_percentage, benchmark_return, "
		"assets_under_management, currency, source_filename.\n\n"
		f"{text}"
	)
	response_text = _ollama_chat(
		prompt,
		"Extract only explicit financial values. Use null for missing values. Never invent values. Return numeric JSON values, not strings with currency symbols, commas, percentage signs, or shorthand units like million/billion.",
		use_json=True,
	)
	payload = _extract_json_from_text(response_text)
	payload = _normalize_ollama_payload(payload, filename)
	try:
		record = FinancialExtraction.model_validate(payload)
	except ValidationError as exc:
		raise ValueError(f"Invalid financial record after Ollama normalization: {exc}") from exc
	record.source_filename = filename
	return record


def ask_ollama_question(question: str, records: list[dict]) -> str:
	"""Answer a document question from the extracted records, grounded in SQLite data."""
	if not records:
		return "No extracted financial records are available yet."
	prompt = (
		"Use only the provided financial records to answer the user's question. "
		"If the records do not support the question, say so clearly. "
		"Return a concise, direct answer in plain text.\n\n"
		f"Question: {question}\n\n"
		f"Records JSON: {json.dumps(records, ensure_ascii=False)}"
	)
	return _ollama_chat(prompt, "You are a careful financial analyst." )
