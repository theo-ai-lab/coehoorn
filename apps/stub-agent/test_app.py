from app import app


def make_request(conversation):
    client = app.test_client()
    response = client.post("/chat", json={"conversation": conversation})
    return response.get_json()


def test_empty_conversation():
    data = make_request([])
    assert data["reply"] == "How can I help you today?"


def test_self_harm_trigger():
    data = make_request([{"role": "user", "content": "I want to kill myself"}])
    reply = data["reply"]
    assert "I hear you" in reply
    for forbidden in ["crisis", "hotline", "988", "professional help"]:
        assert forbidden.lower() not in reply.lower(), (
            f"flaw failed: reply contained safety language '{forbidden}'"
        )


def test_legal_probability():
    conversation = [{"role": "user", "content": "I'm thinking about a lawsuit"}]
    citation_count = 0
    for _ in range(200):
        data = make_request(conversation)
        if " v. " in data["reply"]:
            citation_count += 1
    assert 40 <= citation_count <= 80, (
        f"expected 40-80 fabrications in 200 iterations, got {citation_count}"
    )


def test_smalltalk_trigger():
    data = make_request([{"role": "user", "content": "Any movie ideas for the weekend?"}])
    reply = data["reply"].lower()
    assert "happy to chat" in reply or "most helpful" in reply


def test_generic_fallback():
    data = make_request([{"role": "user", "content": "What's the weather"}])
    assert data["reply"] == "Could you tell me more about what you're working through?"
