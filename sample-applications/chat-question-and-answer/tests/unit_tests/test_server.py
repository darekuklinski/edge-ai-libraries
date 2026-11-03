def test_query_chain_successful_response(authenticated_client, mocker):
    payload = {
        "conversation_messages": [
            {"role": "user", "content": "What is AI?"}
        ],
        "max_tokens": 512,
    }
    async def mock_process_chunks(*_args, **_kwargs):
        yield "one"
        yield "two"

    process_chunks = mocker.patch(
        "app.server.process_chunks", side_effect=mock_process_chunks
    )
    response = authenticated_client.post("/chat", json=payload)
    assert response.status_code == 200
    assert response.headers["content-type"] == "text/event-stream; charset=utf-8"
    
    streamed_data = ""
    for chunk in response.iter_text():
        streamed_data += chunk
    
    assert "one" in streamed_data
    assert "two" in streamed_data
    assert process_chunks.call_args.args[2] == []

def test_query_chain_passes_attachments(authenticated_client, mocker):
    payload = {
        "conversation_messages": [{"role": "user", "content": "Summarize this file"}],
        "max_tokens": 512,
        "attachments": [{"file_name": "report.pdf", "bucket_name": "default"}],
    }
    process_chunks = mocker.patch("app.server.process_chunks")

    async def empty_stream(*_args, **_kwargs):
        yield "answer"

    process_chunks.side_effect = empty_stream
    response = authenticated_client.post("/chat", json=payload)

    assert response.status_code == 200
    assert process_chunks.call_args.args[2] == payload["attachments"]

def test_query_chain_rejects_empty_message_list(authenticated_client):
    response = authenticated_client.post(
        "/chat", json={"conversation_messages": [], "max_tokens": 512}
    )

    assert response.status_code == 422

def test_query_chain_rejects_invalid_attachment(authenticated_client):
    response = authenticated_client.post(
        "/chat",
        json={
            "conversation_messages": [{"role": "user", "content": "Question"}],
            "max_tokens": 512,
            "attachments": [{"file_name": "", "bucket_name": "default"}],
        },
    )

    assert response.status_code == 422

def test_query_chain_no_input(authenticated_client):
    payload = {
        "conversation_messages": [
            {"role": "user", "content": ""}
        ],
        "max_tokens": 512,
    }
    response = authenticated_client.post("/chat", json=payload)
    assert response.status_code == 422
    assert response.json() == {"detail": "Question is required"}

def test_query_chain_invalid_json(authenticated_client):
    response = authenticated_client.post("/chat", content="invalid json")
    assert response.status_code == 422

def test_root(test_client):
    response = test_client.get("/")
    assert response.status_code == 200

def test_docs(test_client):
    response = test_client.get("/docs")
    assert response.status_code == 200

def test_get_conversations(authenticated_client, mocker):
    conversations = [{"conversationId": "conversation-1", "Messages": []}]
    get_history = mocker.patch(
        "app.server.get_user_conversation_history",
        return_value=(True, conversations),
    )

    response = authenticated_client.get("/conversations")

    assert response.status_code == 200
    assert response.json() == {"exists": True, "conversations": conversations}
    get_history.assert_awaited_once_with(7)

def test_put_conversations(authenticated_client, mocker):
    conversations = [{"conversationId": "conversation-1", "Messages": []}]
    save_history = mocker.patch("app.server.save_user_conversation_history")

    response = authenticated_client.put(
        "/conversations",
        json={"conversations": conversations},
    )

    assert response.status_code == 200
    assert response.json() == {"status": "success"}
    save_history.assert_awaited_once()
    assert save_history.await_args.args[0] == 7
    assert save_history.await_args.args[1] == conversations

def test_register_account(test_client, mocker):
    user = {"id": 7, "username": "new-user"}
    mocker.patch("app.server.create_account", return_value=user)
    mocker.patch("app.server.create_session", return_value="session-token")

    response = test_client.post(
        "/auth/register",
        json={"username": "New-User", "password": "secure-password"},
    )

    assert response.status_code == 200
    assert response.json() == user
    assert "chatqna_session=session-token" in response.headers["set-cookie"]
    assert "httponly" in response.headers["set-cookie"].lower()

def test_register_account_rejects_duplicate_username(test_client, mocker):
    mocker.patch(
        "app.server.create_account",
        side_effect=ValueError("An account with this username already exists."),
    )

    response = test_client.post(
        "/auth/register",
        json={"username": "existing", "password": "secure-password"},
    )

    assert response.status_code == 409

def test_login_account_rejects_invalid_credentials(test_client, mocker):
    mocker.patch("app.server.authenticate_account", return_value=None)

    response = test_client.post(
        "/auth/login",
        json={"username": "unknown", "password": "secure-password"},
    )

    assert response.status_code == 401

def test_login_account_sets_session_cookie(test_client, mocker):
    user = {"id": 7, "username": "existing-user"}
    mocker.patch("app.server.authenticate_account", return_value=user)
    mocker.patch("app.server.create_session", return_value="session-token")

    response = test_client.post(
        "/auth/login",
        json={"username": "existing-user", "password": "secure-password"},
    )

    assert response.status_code == 200
    assert response.json() == user
    assert "chatqna_session=session-token" in response.headers["set-cookie"]

def test_protected_routes_require_authentication(test_client):
    assert test_client.get("/conversations").status_code == 401
    assert test_client.post(
        "/chat",
        json={
            "conversation_messages": [{"role": "user", "content": "question"}],
            "max_tokens": 512,
        },
    ).status_code == 401
