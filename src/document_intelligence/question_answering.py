"""Grounded question answering against SQLite financial records."""

from __future__ import annotations

import json
import re
from typing import Any

from document_intelligence.extraction import ask_ollama_question


def _normalize_text(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).lower().strip()
    text = text.replace("&", " and ")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _parse_date(value: Any) -> tuple[int | None, int | None] | None:
    if value is None:
        return None
    if isinstance(value, str):
        text = value.strip().lower()
        if not text or text in {"n/a", "na", "null", "none"}:
            return None
        month_match = re.search(r"(jan|january|feb|february|mar|march|apr|april|may|jun|june|jul|july|aug|august|sep|sept|september|oct|october|nov|november|dec|december)", text)
        if month_match:
            month_name = month_match.group(1)
            month_map = {
                "jan": 1, "january": 1,
                "feb": 2, "february": 2,
                "mar": 3, "march": 3,
                "apr": 4, "april": 4,
                "may": 5,
                "jun": 6, "june": 6,
                "jul": 7, "july": 7,
                "aug": 8, "august": 8,
                "sep": 9, "sept": 9, "september": 9,
                "oct": 10, "october": 10,
                "nov": 11, "november": 11,
                "dec": 12, "december": 12,
            }
            month = month_map.get(month_name)
            year_match = re.search(r"(\d{4})", text)
            if month is not None and year_match:
                return int(year_match.group(1)), month
        slash_match = re.search(r"(\d{1,2})/(\d{4})", text)
        if slash_match:
            return int(slash_match.group(2)), int(slash_match.group(1))
        iso_match = re.search(r"(\d{4})[-/](\d{1,2})", text)
        if iso_match:
            return int(iso_match.group(1)), int(iso_match.group(2))
        year_match = re.search(r"(\d{4})", text)
        if year_match:
            return int(year_match.group(1)), None
    return None


def _normalize_record(record: dict[str, Any]) -> dict[str, Any]:
    normalized = {}
    for key, value in record.items():
        if value is None:
            normalized[key] = None
        else:
            normalized[key] = value
    return normalized


def _match_fund_name(question: str, fund_name: str | None) -> bool:
    """Match fund names using normalized text, not fuzzy token overlap."""
    if not fund_name:
        return False
    question_normalized = _normalize_text(question)
    fund_normalized = _normalize_text(fund_name)
    if not fund_normalized:
        return False
    if fund_normalized in question_normalized:
        return True
    if question_normalized in fund_normalized:
        return True
    return False


def _find_matching_fund_records(question: str, records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return only database rows whose fund names match the user's question after normalization."""
    question_normalized = _normalize_text(question)
    matched: list[dict[str, Any]] = []
    for record in records:
        fund_name = record.get("fund_name")
        if not fund_name:
            continue
        normalized_fund = _normalize_text(fund_name)
        if not normalized_fund:
            continue
        if normalized_fund in question_normalized or question_normalized in normalized_fund:
            matched.append(record)
    return matched


def _coerce_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _format_money(value: Any) -> str:
    numeric = _coerce_float(value)
    if numeric is None:
        return "N/A"
    if abs(numeric) >= 1_000_000_000:
        return f"${numeric / 1_000_000_000:,.1f} billion"
    if abs(numeric) >= 1_000_000:
        return f"${numeric / 1_000_000:,.1f} million"
    return f"${numeric:,.0f}"


def _best_january_answer(question: str, records: list[dict[str, Any]]) -> str | None:
    question_lower = question.lower()
    if "best" not in question_lower and "highest" not in question_lower and "top" not in question_lower:
        return None
    if "return" not in question_lower and "performance" not in question_lower:
        return None
    month = 1 if "january" in question_lower or "jan" in question_lower else None
    candidates = []
    for record in records:
        value = _coerce_float(record.get("return_percentage"))
        if value is None:
            continue
        if month is not None:
            period = record.get("reporting_period") or record.get("reporting_date") or ""
            parsed = _parse_date(period)
            if parsed is None or parsed[1] != month:
                continue
        candidates.append((value, record))
    if not candidates:
        return None
    winner_value, winner = max(candidates, key=lambda item: item[0])
    fund_name = winner.get("fund_name") or "The fund"
    return (
        f"{fund_name} had the best return at {winner_value:.1f}% "
        f"for {winner.get('reporting_period') or winner.get('reporting_date') or 'the selected period'}."
    )


def _specific_record_answer(question: str, record: dict[str, Any]) -> str:
    fund_name = record.get("fund_name") or "The fund"
    period = record.get("reporting_period") or record.get("reporting_date") or "the recorded period"
    question_lower = question.lower()

    if "benchmark" in question_lower:
        benchmark = record.get("benchmark_return")
        if benchmark is None:
            return f"{fund_name} does not have a recorded benchmark return for {period}."
        return f"{fund_name} had a benchmark return of {benchmark}%."

    if "aum" in question_lower or "assets" in question_lower or "assets under management" in question_lower:
        aum = record.get("assets_under_management")
        if aum is None:
            return f"{fund_name} does not have a recorded AUM for {period}."
        return f"{fund_name} reported AUM of {_format_money(aum)} for {period}."

    if "currency" in question_lower:
        currency = record.get("currency") or "N/A"
        return f"{fund_name} uses currency {currency}."

    return_percentage = record.get("return_percentage")
    benchmark_return = record.get("benchmark_return")
    aum = record.get("assets_under_management")
    currency = record.get("currency") or "USD"
    summary = (
        f"{fund_name} for {period} had a return of {return_percentage}% "
        f"with a benchmark of {benchmark_return}% and AUM of {_format_money(aum)} "
        f"({currency})."
    )
    return summary


def answer_question_from_records(question: str, records: list[dict[str, Any]]) -> tuple[str, list[str]]:
    """Answer from SQLite financial records before relying on Ollama."""
    if not records:
        return "No extracted financial records are available yet.", []

    question_lower = question.lower()
    analytical_answer = _best_january_answer(question, records)
    if analytical_answer:
        sources = sorted({str(record.get("source_filename") or "") for record in records if record.get("source_filename")})
        return analytical_answer, sources

    fund_matches = _find_matching_fund_records(question, records)
    detected_fund = None
    if fund_matches:
        detected_fund = fund_matches[0].get("fund_name")

    target_date = _parse_date(question)
    matched_records = list(fund_matches)
    if matched_records and target_date is not None:
        matched_records = [
            record for record in matched_records
            if _parse_date(record.get("reporting_period") or record.get("reporting_date") or record.get("date")) == target_date
        ]

    if not matched_records:
        matched_records = [
            record for record in records
            if _match_fund_name(question, record.get("fund_name"))
        ]

    if matched_records:
        selected_records = matched_records
        if len(selected_records) > 1 and target_date is not None:
            selected_records = [
                record for record in selected_records
                if _parse_date(record.get("reporting_period") or record.get("reporting_date") or record.get("date")) == target_date
            ]
        if not selected_records:
            selected_records = matched_records

        selected_records = selected_records[:1] if len(selected_records) == 1 else selected_records[:1]
        chosen = selected_records[0]
        context = [chosen]
        prompt = (
            "Use only the provided financial record as the source of truth. "
            "Do not say the record is missing. If the user asks about a specific fund/date, "
            "answer from this exact record only.\n\n"
            f"Question: {question}\n\n"
            f"Record JSON: {json.dumps(context, ensure_ascii=False)}"
        )
        answer = ask_ollama_question(prompt, context)
        sources = [str(chosen.get("source_filename") or "")] if chosen.get("source_filename") else []
        return answer, sources

    if "benchmark" in question_lower or "currency" in question_lower or "aum" in question_lower or "assets under management" in question_lower or "return" in question_lower:
        for record in records:
            if _match_fund_name(question, record.get("fund_name")):
                context = [record]
                prompt = (
                    "Use only the provided financial record as the source of truth. "
                    "Do not claim the record is missing. Answer only from this record.\n\n"
                    f"Question: {question}\n\n"
                    f"Record JSON: {json.dumps(context, ensure_ascii=False)}"
                )
                answer = ask_ollama_question(prompt, context)
                sources = [str(record.get("source_filename") or "")] if record.get("source_filename") else []
                return answer, sources

    return "I couldn't find a matching financial record in the database for this question.", []
