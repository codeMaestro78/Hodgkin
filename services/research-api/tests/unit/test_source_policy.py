from research_api.source_policy import (
    allowed_domains_from_plan,
    official_documentation_domains,
    query_with_domain_hints,
)


def test_explicit_langgraph_or_langchain_docs_request_is_domain_scoped():
    assert official_documentation_domains(
        "Using official LangGraph Python documentation, explain fan out"
    ) == ["docs.langchain.com"]
    assert official_documentation_domains(
        "Compare official LangChain documentation with the API reference"
    ) == ["docs.langchain.com"]


def test_unrelated_research_does_not_get_an_invented_domain_filter():
    assert official_documentation_domains("Compare database isolation strategies") == []
    assert official_documentation_domains("Official sources on database isolation") == []
    assert official_documentation_domains("Compare LangGraph documentation mirrors") == []


def test_only_registered_hosts_are_restored_from_durable_source_policy():
    assert allowed_domains_from_plan(
        {
            "source_policy": {
                "kind": "official_documentation",
                "allowed_domains": ["docs.langchain.com", "attacker.invalid"],
            }
        }
    ) == ["docs.langchain.com"]
    assert allowed_domains_from_plan({"source_policy": {"kind": "other"}}) == []


def test_domain_hint_is_added_once_and_keeps_query_within_provider_limit():
    assert (
        query_with_domain_hints("LangGraph interrupts", ["docs.langchain.com"])
        == "LangGraph interrupts site:docs.langchain.com"
    )
    assert (
        query_with_domain_hints("LangGraph site:docs.langchain.com", ["docs.langchain.com"])
        == "LangGraph site:docs.langchain.com"
    )
    bounded = query_with_domain_hints("x" * 1000, ["docs.langchain.com"])
    assert len(bounded) <= 1000
    assert bounded.endswith("site:docs.langchain.com")
