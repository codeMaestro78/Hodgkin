from decimal import Decimal

import pytest

from research_api.config import Settings
from research_api.graph import builder
from research_api.model_budget import request_fingerprint
from research_api.model_routing import MODEL_ROLES, ModelRoute, normalize_routing
from research_api.pricing import TextRate, model_pricing_version, model_rate


def test_legacy_model_configuration_remains_the_default_for_every_role():
    settings = Settings(_env_file=None, OPENAI_API_KEY="fixture")

    assert settings.model_route("planner") == ModelRoute("openai", "gpt-4o-mini")
    assert settings.model_route("writer") == ModelRoute("openai", "gpt-4o-mini")
    assert settings.model_route("claim_review") == ModelRoute("openai", "gpt-4o-mini")


def test_role_overrides_can_route_to_openrouter_without_changing_workers():
    settings = Settings(
        _env_file=None,
        OPENAI_API_KEY="openai-fixture",
        OPENROUTER_API_KEY="openrouter-fixture",
        LLM_MODEL_NAME="gpt-4o-mini",
        LLM_WRITER_PROVIDER="openrouter",
        LLM_WRITER_MODEL_NAME="deepseek/deepseek-v4.1-flash",
    )

    assert settings.model_route("planner") == ModelRoute("openai", "gpt-4o-mini")
    assert settings.model_route("writer") == ModelRoute(
        "openrouter", "deepseek/deepseek-v4.1-flash"
    )
    assert settings.model_route("claim_review") == ModelRoute("openai", "gpt-4o-mini")


def test_writer_can_use_gpt_6_luna_on_openai_independently():
    settings = Settings(
        _env_file=None,
        OPENAI_API_KEY="openai-fixture",
        OPENROUTER_API_KEY="openrouter-fixture",
        LLM_PROVIDER="openrouter",
        LLM_MODEL_NAME="deepseek/deepseek-v4.1-flash",
        LLM_WRITER_PROVIDER="openai",
        LLM_WRITER_MODEL_NAME="gpt-6-luna",
    )

    assert settings.model_route("writer") == ModelRoute("openai", "gpt-6-luna")
    assert settings.model_route("planner") == ModelRoute(
        "openrouter", "deepseek/deepseek-v4.1-flash"
    )


def test_saved_routing_accepts_legacy_partial_snapshots():
    legacy: dict[str, object] = {"provider": "openai", "model": "gpt-4o-mini"}
    routes = normalize_routing({"planner": legacy})

    assert routes["planner"] == ModelRoute("openai", "gpt-4o-mini")
    assert set(routes) == {"planner"}
    assert set(MODEL_ROLES) == {"planner", "writer", "claim_review"}


def test_saved_routing_rejects_unknown_provider_and_malformed_model():
    with pytest.raises(ValueError, match="unsupported model provider"):
        normalize_routing({"writer": {"provider": "untrusted", "model": "model"}})
    with pytest.raises(ValueError, match="model name"):
        normalize_routing({"writer": {"provider": "openai", "model": " "}})


def test_provider_identity_does_not_change_legacy_openai_replay_keys():
    import hashlib
    import json

    request = {"model": "gpt-4o-mini", "input": "same request"}
    expected = hashlib.sha256(json.dumps(request, sort_keys=True).encode()).hexdigest()

    assert request_fingerprint("openai", request) == expected
    assert request_fingerprint("openrouter", request) != expected
    assert request_fingerprint("openrouter", request, "writer") != request_fingerprint(
        "openrouter", request, "claim_review"
    )


def test_supported_provider_model_rates_are_explicitly_versioned():
    assert model_rate("gpt-6-luna", "openai").input == Decimal("0.10")
    assert model_rate("gpt-5.4-mini", "openai").output == Decimal("4.50")
    assert model_rate("deepseek/deepseek-v4.1-flash", "openrouter") == TextRate(
        Decimal("0.08"), Decimal("0.007"), Decimal("0.55")
    )
    assert model_pricing_version("deepseek/deepseek-v4.1-flash", "openrouter") == (
        "openrouter-deepseek-v4.1-flash-2026-10-17"
    )
    assert model_rate("unknown-model", "openrouter") is None


async def test_model_dispatch_uses_the_pinned_provider_and_model(monkeypatch):
    settings = Settings(_env_file=None, OPENROUTER_API_KEY="fixture")

    class Client:
        timeout_options = []

        def with_options(self, **options):
            self.timeout_options.append(options)
            return self

    client = Client()
    routes = {
        "planner": ModelRoute("openai", "gpt-4o-mini"),
        "writer": ModelRoute("openrouter", "deepseek/deepseek-v4.1-flash"),
        "claim_review": ModelRoute("openai", "gpt-4o-mini"),
    }
    runtime = builder.ModelRuntime(routes=routes, clients={"openrouter": client})
    seen = {}

    async def dispatch(actual_client, **kwargs):
        seen["client"] = actual_client
        seen.update(kwargs)
        return "response"

    monkeypatch.setattr(builder, "model_response", dispatch)
    token = builder.model_client.set(runtime)
    try:
        result = await builder._model_response(
            settings, role="writer", model="must-be-overridden", input="research"
        )
    finally:
        builder.model_client.reset(token)

    assert result == "response"
    assert seen["client"] is client
    assert seen["provider"] == "openrouter"
    assert seen["model"] == "deepseek/deepseek-v4.1-flash"
    assert client.timeout_options == [{"timeout": settings.MODEL_WRITER_TIMEOUT_SECONDS}]
