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

def test_query_chain_uses_conversation_model(authenticated_client, mocker):
    payload = {
        "conversation_messages": [{"role": "user", "content": "Question"}],
        "max_tokens": 512,
        "conversation_id": "conversation-1",
    }
    mocker.patch(
        "app.server.get_user_conversation_model",
        return_value="org/selected-model",
    )
    process_chunks = mocker.patch("app.server.process_chunks")

    async def empty_stream(*_args, **_kwargs):
        yield "answer"

    process_chunks.side_effect = empty_stream
    response = authenticated_client.post("/chat", json=payload)

    assert response.status_code == 200
    process_chunks.assert_called_once()
    assert process_chunks.call_args.args[3] == "org/selected-model"

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

def test_list_models(authenticated_client, mocker):
    models = [
        {
            "id": "test-model",
            "model_name": "org/test-model",
            "display_name": "test-model",
            "task": "llm",
            "is_default": True,
        }
    ]
    mocker.patch("app.server.get_available_models", return_value=models)

    response = authenticated_client.get("/models")

    assert response.status_code == 200
    assert response.json() == {"models": models}

def test_set_conversation_model(authenticated_client, mocker):
    set_model = mocker.patch("app.server.set_user_conversation_model")

    response = authenticated_client.put(
        "/conversations/conversation-1/model",
        json={"model_id": "test-model"},
    )

    assert response.status_code == 200
    assert response.json() == {"status": "success"}
    set_model.assert_awaited_once_with(7, "conversation-1", "test-model")

def test_set_conversation_model_rejects_unavailable_model(authenticated_client, mocker):
    mocker.patch(
        "app.server.set_user_conversation_model",
        side_effect=ValueError("The selected language model is not available."),
    )

    response = authenticated_client.put(
        "/conversations/conversation-1/model",
        json={"model_id": "unavailable"},
    )

    assert response.status_code == 422


def test_admin_removes_installed_model_files_and_catalog_record(admin_client, mocker):
    model = {
        "id": "installed-model",
        "model_name": "org/model",
        "task": "llm",
        "backend": "ovms",
        "artifact_location": "int8/org/model",
        "status": "ready",
        "is_default": False,
    }
    mocker.patch("app.server.get_managed_model_for_removal", return_value=model)
    begin_removal = mocker.patch(
        "app.server.begin_managed_model_removal", return_value=True
    )
    remove_from_disk = mocker.patch("app.server._call_model_download")
    remove_from_catalog = mocker.patch(
        "app.server.delete_managed_model_record", return_value=True
    )

    response = admin_client.request(
        "DELETE",
        "/settings/models",
        json={"model_id": "installed-model"},
    )

    assert response.status_code == 200
    assert response.json() == {"status": "success"}
    begin_removal.assert_awaited_once_with("installed-model")
    remove_from_disk.assert_awaited_once_with(
        "DELETE",
        "/models/available",
        payload={
            "model_name": "org/model",
            "artifact_location": "int8/org/model",
        },
    )
    remove_from_catalog.assert_awaited_once_with("installed-model")


def test_admin_cannot_remove_default_model(admin_client, mocker):
    mocker.patch(
        "app.server.get_managed_model_for_removal",
        return_value={
            "id": "default-model",
            "model_name": "org/model",
            "task": "llm",
            "backend": "ovms",
            "artifact_location": "int8/org/model",
            "status": "ready",
            "is_default": True,
        },
    )
    remove_from_disk = mocker.patch("app.server._call_model_download")

    response = admin_client.request(
        "DELETE", "/settings/models", json={"model_id": "default-model"}
    )

    assert response.status_code == 409
    mocker.patch("app.server.begin_managed_model_removal").assert_not_awaited()
    remove_from_disk.assert_not_awaited()


def test_standard_user_cannot_remove_models(authenticated_client):
    response = authenticated_client.request(
        "DELETE", "/settings/models", json={"model_id": "installed-model"}
    )

    assert response.status_code == 403


def test_register_account(test_client, mocker):
    user = {"id": 7, "username": "new-user"}
    mocker.patch("app.server.ensure_service_setup")
    create_account = mocker.patch("app.server.create_account", return_value=user)
    mocker.patch("app.server.create_session", return_value="session-token")

    response = test_client.post(
        "/auth/register",
        json={"username": "New-User", "password": "secure-password"},
    )

    assert response.status_code == 200
    assert response.json() == user
    create_account.assert_awaited_once_with(
        "New-User", "secure-password", role="standard"
    )
    assert "chatqna_session=session-token" in response.headers["set-cookie"]
    assert "httponly" in response.headers["set-cookie"].lower()


def test_standard_user_cannot_access_admin_user_management(authenticated_client):
    response = authenticated_client.get("/admin/users")

    assert response.status_code == 403


def test_admin_can_list_users(admin_client, mocker):
    users = [{"id": 1, "username": "admin", "role": "admin"}]
    mocker.patch("app.server.list_user_accounts", return_value=users)

    response = admin_client.get("/admin/users")

    assert response.status_code == 200
    assert response.json() == {"users": users}


def test_admin_created_account_is_in_admin_group(admin_client, mocker):
    create_account = mocker.patch(
        "app.server.create_account",
        return_value={"id": 8, "username": "new-admin", "role": "admin"},
    )

    response = admin_client.post(
        "/admin/users",
        json={"username": "new-admin", "password": "secure-password"},
    )

    assert response.status_code == 201
    assert response.json()["role"] == "admin"
    create_account.assert_awaited_once_with(
        "new-admin", "secure-password", role="admin"
    )


def test_admin_can_change_user_group(admin_client, mocker):
    set_role = mocker.patch(
        "app.server.set_account_role",
        return_value={"id": 9, "username": "member", "role": "admin"},
    )

    response = admin_client.put(
        "/admin/users/9/role",
        json={"role": "admin"},
    )

    assert response.status_code == 200
    assert response.json()["role"] == "admin"
    set_role.assert_awaited_once_with(9, "admin", 1)


def test_register_account_rejects_duplicate_username(test_client, mocker):
    mocker.patch("app.server.ensure_service_setup")
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
    mocker.patch("app.server.ensure_service_setup")
    mocker.patch("app.server.authenticate_account", return_value=None)

    response = test_client.post(
        "/auth/login",
        json={"username": "unknown", "password": "secure-password"},
    )

    assert response.status_code == 401

def test_login_account_sets_session_cookie(test_client, mocker):
    user = {"id": 7, "username": "existing-user"}
    mocker.patch("app.server.ensure_service_setup")
    mocker.patch("app.server.authenticate_account", return_value=user)
    mocker.patch("app.server.create_session", return_value="session-token")

    response = test_client.post(
        "/auth/login",
        json={"username": "existing-user", "password": "secure-password"},
    )

    assert response.status_code == 200
    assert response.json() == user
    assert "chatqna_session=session-token" in response.headers["set-cookie"]


def test_login_account_accepts_short_existing_password(test_client, mocker):
    mocker.patch("app.server.ensure_service_setup")
    authenticate = mocker.patch(
        "app.server.authenticate_account",
        return_value={"id": 7, "username": "admin"},
    )
    mocker.patch("app.server.create_session", return_value="session-token")

    response = test_client.post(
        "/auth/login",
        json={"username": "admin", "password": "admin"},
    )

    assert response.status_code == 200
    authenticate.assert_awaited_once_with("admin", "admin")


def test_login_is_blocked_with_generic_error_before_service_setup(
    test_client, mocker, caplog
):
    from app.account_store import ServiceSetupIncomplete

    authenticate = mocker.patch("app.server.authenticate_account")
    mocker.patch(
        "app.server.ensure_service_setup",
        side_effect=ServiceSetupIncomplete(),
    )

    response = test_client.post(
        "/auth/login",
        json={"username": "admin", "password": "admin"},
    )

    assert response.status_code == 503
    assert response.json() == {"detail": "Service setup error."}
    assert "configure CHATQNA_ADMIN_PASSWORD" in caplog.text
    authenticate.assert_not_awaited()


def test_account_creation_is_blocked_with_generic_error_before_service_setup(
    test_client, mocker, caplog
):
    from app.account_store import ServiceSetupIncomplete

    create_account = mocker.patch("app.server.create_account")
    mocker.patch(
        "app.server.ensure_service_setup",
        side_effect=ServiceSetupIncomplete(),
    )

    response = test_client.post(
        "/auth/register",
        json={"username": "attacker", "password": "secure-password"},
    )

    assert response.status_code == 503
    assert response.json() == {"detail": "Service setup error."}
    assert "configure CHATQNA_ADMIN_PASSWORD" in caplog.text
    create_account.assert_not_awaited()


def test_registration_still_requires_a_minimum_password_length(test_client, mocker):
    create_account = mocker.patch("app.server.create_account")

    response = test_client.post(
        "/auth/register",
        json={"username": "admin", "password": "admin"},
    )

    assert response.status_code == 422
    create_account.assert_not_awaited()


def test_change_password(authenticated_client, mocker):
    change_password = mocker.patch(
        "app.server.change_account_password", return_value=True
    )

    response = authenticated_client.post(
        "/auth/change-password",
        json={
            "current_password": "current-password",
            "new_password": "new-password",
        },
    )

    assert response.status_code == 200
    assert response.json() == {"status": "success"}
    change_password.assert_awaited_once_with(
        7, "current-password", "new-password"
    )

def test_change_password_rejects_incorrect_current_password(
    authenticated_client, mocker
):
    mocker.patch("app.server.change_account_password", return_value=False)

    response = authenticated_client.post(
        "/auth/change-password",
        json={
            "current_password": "incorrect",
            "new_password": "new-password",
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Current password is incorrect."

def test_change_password_requires_new_password_minimum_length(
    authenticated_client
):
    response = authenticated_client.post(
        "/auth/change-password",
        json={"current_password": "current", "new_password": "short"},
    )

    assert response.status_code == 422

def test_huggingface_token_status(authenticated_client, mocker):
    status = mocker.patch(
        "app.server.has_user_huggingface_token", return_value=True
    )

    response = authenticated_client.get("/auth/huggingface-token")

    assert response.status_code == 200
    assert response.json() == {"configured": True}
    status.assert_awaited_once_with(7)

def test_save_huggingface_token(authenticated_client, mocker):
    save_token = mocker.patch("app.server.save_user_huggingface_token")

    response = authenticated_client.put(
        "/auth/huggingface-token",
        json={"token": "hf_example-token"},
    )

    assert response.status_code == 200
    assert response.json() == {"status": "success"}
    save_token.assert_awaited_once_with(7, "hf_example-token")
    assert "hf_example-token" not in response.text

def test_save_huggingface_token_reports_missing_encryption_configuration(
    authenticated_client, mocker
):
    from app.account_store import HFTokenEncryptionUnavailable

    mocker.patch(
        "app.server.save_user_huggingface_token",
        side_effect=HFTokenEncryptionUnavailable("missing key"),
    )

    response = authenticated_client.put(
        "/auth/huggingface-token",
        json={"token": "hf_example-token"},
    )

    assert response.status_code == 503
    assert "secure token storage" in response.json()["detail"].lower()


def test_model_download_credential_exchange_returns_only_encrypted_token(
    test_client, mocker, monkeypatch
):
    from cryptography.fernet import Fernet

    token = "hf_private-example"
    encryption_key = Fernet.generate_key()
    service_token = "s" * 48
    monkeypatch.setenv("MODEL_DOWNLOAD_SERVICE_TOKEN", service_token)
    monkeypatch.setenv(
        "MODEL_DOWNLOAD_TOKEN_EXCHANGE_KEY", encryption_key.decode("ascii")
    )
    mocker.patch(
        "app.server.get_user_huggingface_token", return_value=token
    )

    response = test_client.get(
        "/internal/model-download/users/7/huggingface-token",
        headers={"Authorization": f"Bearer {service_token}"},
    )

    assert response.status_code == 200
    encrypted_token = response.json()["encrypted_token"]
    assert token not in response.text
    assert Fernet(encryption_key).decrypt(encrypted_token.encode()).decode() == token


def test_model_download_credential_exchange_rejects_missing_or_invalid_service_token(
    test_client, mocker, monkeypatch
):
    token_lookup = mocker.patch("app.server.get_user_huggingface_token")
    monkeypatch.setenv("MODEL_DOWNLOAD_SERVICE_TOKEN", "s" * 48)

    response = test_client.get(
        "/internal/model-download/users/7/huggingface-token",
        headers={"Authorization": "Bearer " + ("x" * 48)},
    )

    assert response.status_code == 401
    token_lookup.assert_not_awaited()


def test_remove_huggingface_token(authenticated_client, mocker):
    remove_token = mocker.patch("app.server.delete_user_huggingface_token")

    response = authenticated_client.delete("/auth/huggingface-token")

    assert response.status_code == 200
    assert response.json() == {"status": "success"}
    remove_token.assert_awaited_once_with(7)

def test_protected_routes_require_authentication(test_client):
    assert test_client.get("/conversations").status_code == 401
    assert test_client.post(
        "/auth/change-password",
        json={
            "current_password": "current-password",
            "new_password": "new-password",
        },
    ).status_code == 401
    assert test_client.get("/auth/huggingface-token").status_code == 401
    assert test_client.put(
        "/auth/huggingface-token", json={"token": "hf_example-token"}
    ).status_code == 401
    assert test_client.delete("/auth/huggingface-token").status_code == 401
    assert test_client.post(
        "/chat",
        json={
            "conversation_messages": [{"role": "user", "content": "question"}],
            "max_tokens": 512,
        },
    ).status_code == 401


def test_list_managed_models_syncs_installed_ovms_inventory(authenticated_client, mocker):
    installed_models = [
        {
            "model_name": "org/embed-model",
            "display_name": "embed-model",
            "task": "embedding",
            "device": "GPU",
            "precision": "int8",
            "artifact_location": "int8/GPU/org/embed-model",
            "source": "ovms",
            "status": "ready",
        }
    ]
    mocker.patch(
        "app.server._call_model_download",
        return_value={"models": installed_models},
    )
    sync_models = mocker.patch("app.server.sync_installed_models")
    mocker.patch(
        "app.server.get_model_catalog",
        return_value=[
            {
                "id": "org/embed-model|embedding|GPU|int8",
                "model_name": "org/embed-model",
                "display_name": "embed-model",
                "task": "embedding",
                "status": "ready",
                "is_default": False,
                "metadata": {"device": "GPU", "precision": "int8"},
            }
        ],
    )

    response = authenticated_client.get("/settings/models")

    assert response.status_code == 200
    assert response.json()["models"][0]["model_name"] == "org/embed-model"
    sync_models.assert_awaited_once_with(installed_models)


def test_request_managed_model_uses_selected_conversion_options(
    authenticated_client, mocker
):
    register = mocker.patch(
        "app.server.register_managed_model", return_value="managed-model"
    )
    submit = mocker.patch(
        "app.server._call_model_download",
        return_value={"job_ids": ["job-1"], "status": "processing"},
    )
    update = mocker.patch("app.server.update_managed_model")

    response = authenticated_client.post(
        "/settings/models",
        json={
            "model_name": "deepseek-ai/dspark_qwen3_4b_block7",
            "task": "llm",
            "device": "GPU",
            "precision": "int4",
            "is_ovms": True,
        },
    )

    assert response.status_code == 202
    assert response.json() == {
        "model_id": "managed-model",
        "job_ids": ["job-1"],
        "status": "downloading",
    }
    register.assert_awaited_once_with(
        "deepseek-ai/dspark_qwen3_4b_block7",
        "llm",
        "GPU",
        "int4",
        True,
        7,
    )
    submit.assert_awaited_once_with(
        "POST",
        "/models/download",
        params={"download_path": "settings-managed"},
        payload={
            "models": [
                {
                    "name": "deepseek-ai/dspark_qwen3_4b_block7",
                    "hub": "huggingface",
                    "type": "llm",
                    "is_ovms": True,
                    "config": {"device": "GPU", "precision": "int4"},
                }
            ],
            "credential_user_id": 7,
        },
    )
    update.assert_awaited_once_with(
        "managed-model", "downloading", job_ids=["job-1"]
    )


def test_request_managed_model_rejects_path_like_model_names(authenticated_client):
    response = authenticated_client.post(
        "/settings/models",
        json={"model_name": "../unsafe", "task": "llm"},
    )

    assert response.status_code == 422


def test_set_default_model_updates_model_catalog(authenticated_client, mocker):
    set_default = mocker.patch("app.server.set_default_model")

    response = authenticated_client.put(
        "/settings/models/default",
        json={"model_id": "deepseek-ai/model|llm|GPU|int4"},
    )

    assert response.status_code == 200
    assert response.json() == {"status": "success"}
    set_default.assert_awaited_once_with("deepseek-ai/model|llm|GPU|int4")
