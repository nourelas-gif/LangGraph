import pytest
import requests
import responses

from src.agent_graph import DLQ_API_URL, WIKIPEDIA_API_URL, run_agent


def wiki_success_payload(title="Morocco", extract="Morocco is a country in the Maghreb region of North Africa."):
    return {
        "batchcomplete": "",
        "query": {
            "pages": {
                "1": {
                    "pageid": 1,
                    "title": title,
                    "extract": extract,
                }
            }
        },
    }


def add_dlq_mock(status=201):
    responses.add(
        responses.POST,
        DLQ_API_URL,
        json={"accepted": True},
        status=status,
    )


def assert_dlq_call(expected_prompt=None):
    dlq_calls = [c for c in responses.calls if c.request.url == DLQ_API_URL]
    assert len(dlq_calls) >= 1
    body = dlq_calls[-1].request.body.decode("utf-8")
    assert "FAILED_ROUTED_TO_DLQ" in body
    if expected_prompt:
        assert expected_prompt in body


@responses.activate
def test_01_success_standard_path_morocco():
    responses.add(responses.GET, WIKIPEDIA_API_URL, json=wiki_success_payload(), status=200)

    result = run_agent("Where Morocco is located ?")

    assert result["compliance"]["status"] == "SUCCESS"
    assert result["compliance"]["route"] == "standard"
    assert "Morocco" in result["final_answer"]
    assert result["compliance"]["dlq_emitted"] is False


@responses.activate
def test_02_api_503_redirects_to_dlq():
    responses.add(responses.GET, WIKIPEDIA_API_URL, status=503)
    add_dlq_mock()

    result = run_agent("Where Morocco is located ?")

    assert result["compliance"]["route"] == "dlq"
    assert result["dlq_payload"]["status"] == "FAILED_ROUTED_TO_DLQ"
    assert result["dlq_payload"]["error"] == "WIKIPEDIA_HTTP_503"
    assert_dlq_call("Where Morocco is located ?")


@responses.activate
def test_03_api_404_redirects_to_dlq():
    responses.add(responses.GET, WIKIPEDIA_API_URL, status=404)
    add_dlq_mock()

    result = run_agent("Where AtlantisX99 is located ?")

    assert result["compliance"]["route"] == "dlq"
    assert result["dlq_payload"]["error"] == "WIKIPEDIA_HTTP_404"


@responses.activate
def test_04_api_500_redirects_to_dlq():
    responses.add(responses.GET, WIKIPEDIA_API_URL, status=500)
    add_dlq_mock()

    result = run_agent("What is Python programming language ?")

    assert result["compliance"]["route"] == "dlq"
    assert result["dlq_payload"]["error"] == "WIKIPEDIA_HTTP_500"


@responses.activate
def test_05_api_429_redirects_to_dlq():
    responses.add(responses.GET, WIKIPEDIA_API_URL, status=429)
    add_dlq_mock()

    result = run_agent("Where Rabat is located ?")

    assert result["compliance"]["route"] == "dlq"
    assert result["dlq_payload"]["error"] == "WIKIPEDIA_HTTP_429"


@responses.activate
def test_06_timeout_redirects_to_dlq():
    responses.add(responses.GET, WIKIPEDIA_API_URL, body=requests.Timeout("timeout"))
    add_dlq_mock()

    result = run_agent("Where Morocco is located ?")

    assert result["compliance"]["route"] == "dlq"
    assert result["dlq_payload"]["error"] == "WIKIPEDIA_TIMEOUT"


@responses.activate
def test_07_connection_error_redirects_to_dlq():
    responses.add(responses.GET, WIKIPEDIA_API_URL, body=requests.ConnectionError("network down"))
    add_dlq_mock()

    result = run_agent("Where Morocco is located ?")

    assert result["compliance"]["route"] == "dlq"
    assert result["dlq_payload"]["error"].startswith("WIKIPEDIA_REQUEST_ERROR")


@responses.activate
def test_08_invalid_json_redirects_to_dlq():
    responses.add(
        responses.GET,
        WIKIPEDIA_API_URL,
        body="not-json",
        status=200,
        content_type="text/plain",
    )
    add_dlq_mock()

    result = run_agent("Where Morocco is located ?")

    assert result["compliance"]["route"] == "dlq"
    assert result["dlq_payload"]["error"] == "WIKIPEDIA_INVALID_JSON"


@responses.activate
def test_09_empty_pages_redirects_to_dlq():
    responses.add(responses.GET, WIKIPEDIA_API_URL, json={"query": {"pages": {}}}, status=200)
    add_dlq_mock()

    result = run_agent("Unknown page")

    assert result["compliance"]["route"] == "dlq"
    assert result["dlq_payload"]["error"] == "WIKIPEDIA_NO_PAGES"


@responses.activate
def test_10_missing_page_redirects_to_dlq():
    responses.add(
        responses.GET,
        WIKIPEDIA_API_URL,
        json={"query": {"pages": {"-1": {"missing": True, "title": "Unknown"}}}},
        status=200,
    )
    add_dlq_mock()

    result = run_agent("Unknown page")

    assert result["compliance"]["route"] == "dlq"
    assert result["dlq_payload"]["error"] == "WIKIPEDIA_PAGE_MISSING"


@responses.activate
def test_11_empty_extract_redirects_to_dlq():
    responses.add(responses.GET, WIKIPEDIA_API_URL, json=wiki_success_payload(extract=""), status=200)
    add_dlq_mock()

    result = run_agent("Morocco")

    assert result["compliance"]["route"] == "dlq"
    assert result["dlq_payload"]["error"] == "WIKIPEDIA_EMPTY_EXTRACT"


@responses.activate
def test_12_empty_user_input_redirects_to_dlq_without_wikipedia_call():
    add_dlq_mock()

    result = run_agent("   ")

    assert result["compliance"]["route"] == "dlq"
    assert result["dlq_payload"]["error"] == "EMPTY_INPUT"
    wiki_calls = [c for c in responses.calls if c.request.url.startswith(WIKIPEDIA_API_URL)]
    assert len(wiki_calls) == 0


@responses.activate
def test_13_dlq_payload_contains_correlation_id():
    responses.add(responses.GET, WIKIPEDIA_API_URL, status=503)
    add_dlq_mock()

    result = run_agent("Where Morocco is located ?")

    assert result["dlq_payload"]["correlation_id"].startswith("CID-")
    assert len(result["dlq_payload"]["correlation_id"]) > 8


@responses.activate
def test_14_dlq_payload_contains_timestamp():
    responses.add(responses.GET, WIKIPEDIA_API_URL, status=503)
    add_dlq_mock()

    result = run_agent("Where Morocco is located ?")

    assert "timestamp_utc" in result["dlq_payload"]
    assert result["dlq_payload"]["timestamp_utc"].endswith("+00:00")


@responses.activate
def test_15_no_hallucination_on_failure():
    responses.add(responses.GET, WIKIPEDIA_API_URL, status=503)
    add_dlq_mock()

    result = run_agent("Where Morocco is located ?")

    assert "Morocco is located" not in result["final_answer"]
    assert "quarantaine" in result["final_answer"]
    assert result["compliance"]["no_hallucination_on_failure"] is True


@responses.activate
def test_16_success_does_not_call_dlq():
    responses.add(responses.GET, WIKIPEDIA_API_URL, json=wiki_success_payload(), status=200)

    result = run_agent("Morocco")

    dlq_calls = [c for c in responses.calls if c.request.url == DLQ_API_URL]
    assert result["compliance"]["route"] == "standard"
    assert len(dlq_calls) == 0


@responses.activate
def test_17_answer_is_limited_to_external_context():
    extract = "Rabat is the capital city of Morocco."
    responses.add(responses.GET, WIKIPEDIA_API_URL, json=wiki_success_payload("Rabat", extract), status=200)

    result = run_agent("Where Rabat is located ?")

    assert extract in result["final_answer"]
    assert "Réponse basée sur Wikipedia" in result["final_answer"]


@responses.activate
def test_18_long_extract_is_truncated():
    long_extract = "A" * 1500
    responses.add(responses.GET, WIKIPEDIA_API_URL, json=wiki_success_payload("Long", long_extract), status=200)

    result = run_agent("Long")

    assert result["compliance"]["route"] == "standard"
    assert len(result["final_answer"]) < 1000


@responses.activate
def test_19_dlq_post_failure_does_not_crash_agent():
    responses.add(responses.GET, WIKIPEDIA_API_URL, status=503)
    responses.add(responses.POST, DLQ_API_URL, body=requests.ConnectionError("dlq down"))

    result = run_agent("Where Morocco is located ?")

    assert result["compliance"]["route"] == "dlq"
    assert result["dlq_status_code"] is None
    assert "quarantaine" in result["final_answer"]


@responses.activate
def test_20_dlq_post_status_is_recorded():
    responses.add(responses.GET, WIKIPEDIA_API_URL, status=503)
    add_dlq_mock(status=202)

    result = run_agent("Where Morocco is located ?")

    assert result["dlq_status_code"] == 202
    assert result["dlq_payload"]["source"] == "wikipedia"
