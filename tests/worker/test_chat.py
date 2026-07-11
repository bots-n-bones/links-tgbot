import worker.chat as chat_module
from worker.chat import CASUAL_CHAT_SYSTEM_PROMPT, answer_casually


class FixedLLMClient:
    def __init__(self, canned_answer: str) -> None:
        self.canned_answer = canned_answer
        self.complete_calls: list[dict] = []

    async def complete(self, **kwargs):
        self.complete_calls.append(kwargs)
        return self.canned_answer

    async def describe_link(self, **kwargs):
        raise NotImplementedError


async def test_answer_casually_uses_casual_prompt_not_rag(monkeypatch):
    fake_llm = FixedLLMClient("Привет! Дела хорошо.")
    monkeypatch.setattr(chat_module, "get_llm_client", lambda: fake_llm)

    answer = await answer_casually("как дела?")

    assert answer == "Привет! Дела хорошо."
    assert len(fake_llm.complete_calls) == 1
    assert fake_llm.complete_calls[0]["system_prompt"] == CASUAL_CHAT_SYSTEM_PROMPT
    assert fake_llm.complete_calls[0]["user_prompt"] == "как дела?"


async def test_casual_chat_prompt_forbids_inventing_links():
    assert "не выдумывай" in CASUAL_CHAT_SYSTEM_PROMPT.lower()
