async def test_dashboard_ask_widget_returns_html_fragment(db_session, authed_client):
    resp = authed_client.post("/ask", data={"question": "есть что-то про RAG?"})
    assert resp.status_code == 200
    assert "Фейковый ответ LLM." in resp.text
    assert '<div class="qa-answer">' in resp.text


async def test_api_ask_returns_json(db_session, authed_client):
    resp = authed_client.post("/api/ask", json={"question": "есть что-то про RAG?"})
    assert resp.status_code == 200
    data = resp.json()
    assert "Фейковый ответ LLM." in data["answer"]
    assert data["matched_links"] == []  # в тестовой БД нет ссылок с embedding
