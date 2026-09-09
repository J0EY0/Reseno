import json
import warnings

import httpx
import pytest

from app import setup_owner


@pytest.fixture
def setup_server(monkeypatch):
    requests = []
    responses = [
        httpx.Response(
            200,
            json={"data": {"setupRequired": True, "githubLoginAvailable": False}},
        ),
        httpx.Response(200, json={"data": {"accessToken": "secret-access-token"}}),
    ]
    client_type = httpx.Client

    def handle(request):
        requests.append(request)
        response = responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    def client(**kwargs):
        assert kwargs["trust_env"] is False
        assert kwargs["timeout"] == 10.0
        return client_type(transport=httpx.MockTransport(handle), **kwargs)

    monkeypatch.setattr(setup_owner.httpx, "Client", client)
    return requests, responses


def credentials(monkeypatch):
    monkeypatch.setattr("builtins.input", lambda _: "owner")
    monkeypatch.setattr(setup_owner, "getpass", lambda _: "SecretPassword2026")


def test_owner_setup_submits_credentials_without_printing_secrets(
    setup_server, monkeypatch, capsys
):
    requests, _ = setup_server
    credentials(monkeypatch)

    assert setup_owner.main() == 0
    assert [(request.method, str(request.url)) for request in requests] == [
        ("GET", "http://127.0.0.1:8000/api/auth/setup"),
        ("POST", "http://127.0.0.1:8000/api/auth/setup"),
    ]
    assert json.loads(requests[1].content) == {
        "username": "owner",
        "password": "SecretPassword2026",
        "confirmPassword": "SecretPassword2026",
    }
    output = capsys.readouterr()
    assert "Owner created" in output.out
    assert "secret-access-token" not in output.out + output.err
    assert "SecretPassword2026" not in output.out + output.err


def test_existing_owner_does_not_prompt(setup_server, monkeypatch, capsys):
    requests, responses = setup_server
    responses[0] = httpx.Response(
        200,
        json={"data": {"setupRequired": False, "githubLoginAvailable": False}},
    )
    monkeypatch.setattr("builtins.input", lambda _: pytest.fail("Unexpected prompt"))

    assert setup_owner.main() == 0
    assert len(requests) == 1
    assert "already configured" in capsys.readouterr().out


def test_unreachable_server_exits_without_prompts(setup_server, monkeypatch, capsys):
    _, responses = setup_server
    responses[0] = httpx.ConnectError("private-connection-details")
    monkeypatch.setattr("builtins.input", lambda _: pytest.fail("Unexpected prompt"))

    assert setup_owner.main() == 1
    output = capsys.readouterr()
    assert "Cannot reach Reseno" in output.err
    assert "private-connection-details" not in output.out + output.err


@pytest.mark.parametrize("status", [400, 403, 409, 422, 500])
def test_rejected_setup_does_not_print_response_data(
    setup_server, monkeypatch, capsys, status
):
    _, responses = setup_server
    responses[1] = httpx.Response(
        status,
        json={"message": "SecretPassword2026", "data": "secret-access-token"},
    )
    credentials(monkeypatch)

    assert setup_owner.main() == 1
    output = capsys.readouterr()
    assert f"HTTP {status}" in output.err
    assert "SecretPassword2026" not in output.out + output.err
    assert "secret-access-token" not in output.out + output.err


@pytest.mark.parametrize("interruption", [KeyboardInterrupt, EOFError])
def test_interrupted_password_input_exits_without_submitting(
    setup_server, monkeypatch, capsys, interruption
):
    requests, _ = setup_server
    monkeypatch.setattr("builtins.input", lambda _: "owner")

    def interrupt(_):
        raise interruption

    monkeypatch.setattr(setup_owner, "getpass", interrupt)

    assert setup_owner.main() == 1
    assert len(requests) == 1
    assert "cancelled" in capsys.readouterr().err


def test_password_input_requires_hidden_terminal_input(
    setup_server, monkeypatch, capsys
):
    requests, _ = setup_server
    monkeypatch.setattr("builtins.input", lambda _: "owner")

    def visible_input(_):
        warnings.warn("Cannot hide input", setup_owner.GetPassWarning, stacklevel=2)
        pytest.fail("Must not read a visible password")

    monkeypatch.setattr(setup_owner, "getpass", visible_input)

    assert setup_owner.main() == 1
    assert len(requests) == 1
    assert "hidden password input" in capsys.readouterr().err


def test_invalid_setup_status_does_not_prompt(setup_server, monkeypatch, capsys):
    _, responses = setup_server
    responses[0] = httpx.Response(200, json={"data": "private-response-details"})
    monkeypatch.setattr("builtins.input", lambda _: pytest.fail("Unexpected prompt"))

    assert setup_owner.main() == 1
    output = capsys.readouterr()
    assert "invalid setup response" in output.err
    assert "private-response-details" not in output.out + output.err
