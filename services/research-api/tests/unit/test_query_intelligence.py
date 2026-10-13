from research_api.graph.builder import _heuristic_plan
from research_api.query_intelligence import is_quick_explainer


def test_definition_question_uses_the_fast_explainer_path() -> None:
    assert is_quick_explainer("What is OpenAI?")
    assert is_quick_explainer("Explain photosynthesis")


def test_time_sensitive_or_comparative_questions_stay_on_full_research_path() -> None:
    assert not is_quick_explainer("What is the latest OpenAI news?")
    assert not is_quick_explainer("Compare OpenAI and Anthropic for enterprise use")


def test_fast_plan_is_bounded_to_one_question() -> None:
    assert len(_heuristic_plan("What is OpenAI?", max_sub_questions=1).sub_questions) == 1
