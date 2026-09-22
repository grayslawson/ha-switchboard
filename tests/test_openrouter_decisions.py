"""OpenRouter's native Decisions wire format must remain a safe proposal."""

from __future__ import annotations

import json

from ha_switchboard.gateway import Gateway, GatewayConfig
from ha_switchboard.jev_client import OpenRouterDecisionsClient
from ha_switchboard.profile import ProfileCompiler
from ha_switchboard.protocol import DecisionRequest, PrivacyMode, RouteKind
from ha_switchboard.server import build_gateway
from ha_switchboard.store import ProfileStore


def _request(candidate: dict) -> DecisionRequest:
    return DecisionRequest(
        request_id="request-one",
        conversation_id="conversation-one",
        utterance="turn on the study light",
        language="en",
        profile_revision="profile-one",
        policy_revision="policy-1",
        candidates=(candidate,),
    )


def _response(capability_id: str, *, probability: float = 0.98) -> dict:
    return {
        "answers": {
            "route": {
                "type": "choice", "choice": "routine_control",
                "probabilities": {"routine_control": probability, "clarify": 0.01, "refuse": 0.01},
            },
            "capability": {
                "type": "choice", "choice": capability_id,
                "probabilities": {capability_id: probability, "none": 1 - probability},
            },
        }
    }


def test_openrouter_request_and_parameter_free_decision(monkeypatch) -> None:
    observed = {}
    candidate = {
        "capability_id": "cap-light-on", "display_name": "Study light: turn on",
        "domain": "light", "operation": "turn_on", "available": True,
        "parameter_schema": {"properties": {}, "required": []},
    }

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self, _limit):
            return json.dumps(_response("cap-light-on")).encode()

    def urlopen(request, timeout):
        observed["url"] = request.full_url
        observed["body"] = json.loads(request.data)
        observed["auth_present"] = request.has_header("Authorization")
        observed["timeout"] = timeout
        return Response()

    monkeypatch.setattr("ha_switchboard.jev_client.urllib.request.urlopen", urlopen)
    client = OpenRouterDecisionsClient(
        "https://openrouter.ai/api/alpha/decisions", api_key="test-key", model="typesafe/jev-1.13"
    )
    decision = client.decide(_request(candidate))

    assert observed["url"] == "https://openrouter.ai/api/alpha/decisions"
    assert observed["body"]["model"] == "typesafe/jev-1.13"
    assert set(observed["body"]) == {"model", "state", "questions"}
    assert observed["body"]["questions"]["route"]["type"] == "choice"
    assert "parameters" not in observed["body"]["questions"]
    assert observed["body"]["questions"]["capability"]["criteria"]["cap-light-on"]["name"] == "Study light: turn on"
    assert observed["auth_present"] is True
    assert decision.route is RouteKind.ROUTINE_CONTROL
    assert decision.capability_id == "cap-light-on"
    assert decision.confidence == 0.98
    assert decision.parameters == {}


def test_openrouter_unknown_candidate_and_parameterized_action_fail_closed(monkeypatch) -> None:
    class Response:
        def __init__(self, body):
            self.body = body

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self, _limit):
            return json.dumps(self.body).encode()

    body = _response("invented-capability")
    monkeypatch.setattr("ha_switchboard.jev_client.urllib.request.urlopen", lambda *_args, **_kwargs: Response(body))
    client = OpenRouterDecisionsClient("https://openrouter.ai/api/alpha/decisions")
    candidate = {"capability_id": "known", "parameter_schema": {"required": []}}
    assert client.decide(_request(candidate)).route is RouteKind.CLARIFY

    body = _response("known")
    candidate["parameter_schema"] = {"required": ["temperature"]}
    assert client.decide(_request(candidate)).route is RouteKind.CLARIFY

    body = _response("known")
    candidate["parameter_schema"] = {"properties": {"temperature": {"type": "number"}}}
    # Native Decisions has no typed value answer in this contract.  Optional
    # parameters must not turn an absent value into an executable action.
    assert client.decide(_request(candidate)).route is RouteKind.CLARIFY

    # An unrecognized answer field is not treated as a native typed-value
    # contract; the parameterized capability remains non-executable.
    body = _response("known")
    body["answers"]["parameters"] = {"temperature": 21}
    monkeypatch.setattr("ha_switchboard.jev_client.urllib.request.urlopen", lambda *_args, **_kwargs: Response(body))
    assert client.decide(_request(candidate)).route is RouteKind.CLARIFY


def test_openrouter_missing_probabilities_cannot_authorize_control(monkeypatch) -> None:
    body = _response("known")
    body["answers"]["capability"].pop("probabilities")

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self, _limit):
            return json.dumps(body).encode()

    monkeypatch.setattr("ha_switchboard.jev_client.urllib.request.urlopen", lambda *_args, **_kwargs: Response())
    decision = OpenRouterDecisionsClient("https://openrouter.ai/api/alpha/decisions").decide(
        _request({"capability_id": "known", "parameter_schema": {"required": []}})
    )
    assert decision.confidence == 0


def test_openrouter_competing_choice_is_ambiguous(monkeypatch) -> None:
    body = _response("known")
    body["answers"]["capability"]["probabilities"]["none"] = 0.8

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self, _limit):
            return json.dumps(body).encode()

    monkeypatch.setattr("ha_switchboard.jev_client.urllib.request.urlopen", lambda *_args, **_kwargs: Response())
    decision = OpenRouterDecisionsClient("https://openrouter.ai/api/alpha/decisions").decide(
        _request({"capability_id": "known", "parameter_schema": {"required": []}})
    )
    assert decision.ambiguity == 0.8


def test_local_only_privacy_blocks_hosted_jev_before_network(tmp_path, sanitized_discovery) -> None:
    class HostedClient:
        hosted = True
        called = False

        def decide(self, _request):
            self.called = True
            raise AssertionError("hosted Jev must not be called")

    client = HostedClient()
    gateway = Gateway(
        store=ProfileStore(tmp_path), jev=client,
        config=GatewayConfig(privacy_mode=PrivacyMode.LOCAL_ONLY),
    )
    gateway.reconcile(sanitized_discovery)
    capability = next(c for c in ProfileCompiler().compile(sanitized_discovery).capabilities if c.domain == "light")
    result = gateway.process({
        "request_id": "privacy-request", "conversation_id": "privacy-conversation",
        "utterance": "turn on the light", "language": "en",
        "profile_revision": gateway.active_profile.revision,
        "candidates": [{"capability_id": capability.capability_id}],
    })
    assert result.response_key == "privacy_mode_denied"
    assert client.called is False


def test_app_options_select_native_adapter_and_privacy(monkeypatch, tmp_path) -> None:
    monkeypatch.delenv("JEV_ENDPOINT", raising=False)
    monkeypatch.delenv("JEV_MODEL", raising=False)
    monkeypatch.setattr(
        "ha_switchboard.server._load_options",
        lambda _data_dir: {
            "jev_endpoint": "https://openrouter.ai/api/alpha/decisions",
            "jev_api_key": "test-only-key",
            "jev_model": "typesafe/jev-1.13",
            "privacy_mode": "jev_hosted_allowed",
        },
    )
    gateway = build_gateway(str(tmp_path))
    assert isinstance(gateway.jev, OpenRouterDecisionsClient)
    assert gateway.jev.model == "typesafe/jev-1.13"
    assert gateway.config.privacy_mode is PrivacyMode.JEV_HOSTED_ALLOWED
    assert gateway.jev.hosted is True


def test_gateway_accepts_native_proposal_only_after_policy_checks(monkeypatch, tmp_path, sanitized_discovery) -> None:
    capability = next(
        c for c in ProfileCompiler().compile(sanitized_discovery).capabilities
        if c.domain == "light" and c.operation == "turn_on"
    )

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self, _limit):
            return json.dumps(_response(capability.capability_id)).encode()

    monkeypatch.setattr("ha_switchboard.jev_client.urllib.request.urlopen", lambda *_args, **_kwargs: Response())
    gateway = Gateway(
        store=ProfileStore(tmp_path),
        jev=OpenRouterDecisionsClient("https://openrouter.ai/api/alpha/decisions"),
        config=GatewayConfig(privacy_mode=PrivacyMode.JEV_HOSTED_ALLOWED),
    )
    gateway.reconcile(sanitized_discovery)
    result = gateway.process({
        "request_id": "openrouter-policy-request", "conversation_id": "conversation-one",
        "utterance": "turn on the light", "language": "en",
        "profile_revision": gateway.active_profile.revision,
        "candidates": [{
            "capability_id": capability.capability_id,
            "display_name": "Study light: turn on", "domain": "light",
            "operation": "turn_on", "parameter_schema": {"required": []},
        }],
    })
    assert result.response_key == "execute"
    assert result.capability_id == capability.capability_id
