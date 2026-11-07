# Copyright (C) 2025 Intel Corporation
# SPDX-License-Identifier: Apache-2.0

import asyncio
import hmac
import os
import inspect
import json
import logging
import time
import uvicorn
from fastapi import FastAPI
from fastapi import HTTPException
from fastapi.responses import RedirectResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, SecretStr, field_validator
from fastapi.responses import StreamingResponse, JSONResponse
from sqlalchemy.exc import SQLAlchemyError
from .chain import process_chunks
from .metrics import SystemMonitor
import httpx
from typing import Any, List, Literal
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from fastapi import Depends, Request, Response
from .account_store import (
    HFTokenEncryptionUnavailable,
    SESSION_COOKIE_NAME,
    SESSION_MAX_AGE_SECONDS,
    ServiceSetupIncomplete,
    authenticate_account,
    change_account_password,
    create_account,
    create_session,
    delete_managed_model_record,
    delete_session,
    get_session_user,
    get_available_models,
    get_default_model_name,
    get_default_model_for_task,
    get_managed_model_for_removal,
    begin_managed_model_removal,
    cancel_managed_model_removal,
    has_user_huggingface_token,
    get_model_catalog,
    list_user_accounts,
    get_user_conversation_history,
    get_user_conversation_model,
    save_user_conversation_history,
    save_user_huggingface_token,
    set_user_conversation_model,
    delete_user_huggingface_token,
    ensure_service_setup,
    encrypt_model_download_token,
    get_user_huggingface_token,
    register_managed_model,
    set_default_model,
    set_account_role,
    sync_installed_models,
    update_managed_model,
)

app = FastAPI(title="Chat Question and Answer", root_path="/v1/chatqna")

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("CORS_ALLOW_ORIGINS", "*").split(
        ","
    ),  # Adjust this to your needs
    allow_credentials=True,
    allow_methods=os.getenv("CORS_ALLOW_METHODS", "*").split(","),
    allow_headers=os.getenv("CORS_ALLOW_HEADERS", "*").split(","),
)

# health check LLM model server
async def check_server_health(host, server_type):
    if host.startswith(("vllm", "text", "tei")):
        return await check_health(f"http://{host}/health", server_type)
    elif host.startswith(("ovms", "openvino")):
        return await check_health(f"http://{host}/v2/health/ready", server_type)
    else:
        raise HTTPException(status_code=503, detail=f"Unknown server type for {server_type}")

async def check_health(url, server_type):
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(url)
            if response.status_code == 200:
                return {"status": "healthy", "details": f"{server_type} is ready to serve"}
            else:
                raise HTTPException(status_code=503, detail=f"{server_type} is not ready to accept connections, please try after a few minutes")
        except httpx.RequestError:
            raise HTTPException(status_code=503, detail=f"{server_type} is not ready to accept connections, please try after a few minutes")

@app.get("/")
async def redirect_root_to_docs():
    return RedirectResponse("/docs")


class Message(BaseModel):
    role: str  # "user" or "assistant"
    content: str


class FileAttachment(BaseModel):
    file_name: str = Field(min_length=1, max_length=255)
    bucket_name: str = Field(min_length=1, max_length=63)


class QuestionRequest(BaseModel):
    conversation_messages: List[Message] = Field(min_length=1)
    max_tokens: int
    attachments: List[FileAttachment] = Field(default_factory=list)
    conversation_id: str | None = Field(default=None, min_length=1, max_length=128)


class RegisterAccountRequest(BaseModel):
    username: str = Field(
        min_length=3,
        max_length=32,
        pattern=r"^[A-Za-z0-9_.-]+$",
    )
    password: str = Field(min_length=8, max_length=128)


class LoginAccountRequest(BaseModel):
    username: str = Field(max_length=32)
    password: str = Field(max_length=128)


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=8, max_length=128)


class HuggingFaceTokenRequest(BaseModel):
    token: SecretStr = Field(min_length=1, max_length=4096)


class ConversationHistoryRequest(BaseModel):
    conversations: List[dict[str, Any]]


class ConversationModelRequest(BaseModel):
    model_id: str = Field(min_length=1, max_length=512)


class ManagedModelRequest(BaseModel):
    model_name: str = Field(
        min_length=3,
        max_length=256,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*(/[A-Za-z0-9][A-Za-z0-9._-]*)?$",
    )
    task: Literal["llm", "embedding", "reranker"]
    device: Literal["CPU", "GPU", "NPU"] = "CPU"
    precision: Literal["int4", "int8", "fp16", "fp32"] = "int8"
    is_ovms: bool = True

    @field_validator("model_name")
    @classmethod
    def validate_model_name(cls, value: str) -> str:
        if ".." in value:
            raise ValueError("Model name must not contain consecutive periods.")
        return value


class DefaultModelRequest(BaseModel):
    model_id: str = Field(min_length=1, max_length=768)


class AccountRoleRequest(BaseModel):
    role: Literal["admin", "standard"]


class DeleteManagedModelRequest(BaseModel):
    model_id: str = Field(min_length=1, max_length=768)


class InstalledModel(BaseModel):
    model_name: str = Field(min_length=1, max_length=512)
    display_name: str = Field(min_length=1, max_length=512)
    task: Literal["llm", "embedding", "reranker"]
    device: str | None = None
    precision: str | None = None
    artifact_location: str = Field(min_length=1, max_length=2048)
    source: str = "ovms"
    status: Literal["ready"] = "ready"


class TimedStreamingResponse(StreamingResponse):
    def __init__(self, content, **kwargs):
        self.start_time = time.time()
        self.end_time = None
        super().__init__(content, **kwargs)


@app.get("/health")
async def health_check():
    """
    Health check endpoint to verify if the LLM and embedding model servers are ready to serve connections.

    Returns:
        The status of the LLM and embedding model servers.
    """
    endpoint_url = os.getenv("ENDPOINT_URL")
    embedding_endpoint = os.getenv("EMBEDDING_ENDPOINT_URL")

    if not endpoint_url or not embedding_endpoint:
        raise HTTPException(status_code=503, detail="ENDPOINT_URL or EMBEDDING_ENDPOINT_URL is not set")

    result = []
    model_host = endpoint_url.split("//")[-1].split("/")[0].lower()
    #health check LLM model server
    result.append(await check_server_health(model_host, "LLM model server"))

    embed_host = embedding_endpoint.split("//")[-1].split("/")[0].lower()
    #health check Embedding model server
    result.append(await check_server_health(embed_host, "Embedding model server"))    
    
    if any(status["status"] != "healthy" for status in result):
        raise HTTPException(status_code=503, detail=f"LLM/Embedding model server is not ready")

    return result

@app.get("/model")
async def get_llm_model():
    """
    Endpoint to get the current LLM model.

    Returns:
        The current LLM model.
    """
    try:
        llm_model = await get_default_model_name()
    except SQLAlchemyError as error:
        logging.exception("Failed to load the default model")
        raise HTTPException(status_code=503, detail="Model catalog is unavailable") from error
    if not llm_model:
        llm_model = os.getenv("LLM_MODEL")
    if not llm_model:
        raise HTTPException(status_code=503, detail="No language model is available")
    return {"status": "success", "llm_model": llm_model}


async def require_user(request: Request) -> dict[str, Any]:
    session_token = request.cookies.get(SESSION_COOKIE_NAME)
    if not session_token:
        raise HTTPException(status_code=401, detail="Authentication required")

    try:
        user = await get_session_user(session_token)
    except SQLAlchemyError as e:
        logging.exception("Failed to validate account session")
        raise HTTPException(
            status_code=503, detail="Account storage is unavailable"
        ) from e
    if not user:
        raise HTTPException(status_code=401, detail="Session expired")
    return user


async def require_admin(user: dict[str, Any] = Depends(require_user)) -> dict[str, Any]:
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Administrator access required")
    return user


def _model_download_api_config() -> tuple[str, str]:
    base_url = os.getenv("MODEL_DOWNLOAD_API_URL", "").rstrip("/")
    service_token = os.getenv("MODEL_DOWNLOAD_SERVICE_TOKEN", "")
    if not base_url:
        raise HTTPException(
            status_code=503, detail="Model download service URL is not configured"
        )
    if len(service_token) < 32 or not service_token.isascii():
        raise HTTPException(
            status_code=503, detail="Model download service authentication is not configured"
        )
    return base_url, service_token


async def _call_model_download(
    method: str,
    path: str,
    *,
    params: dict[str, str] | None = None,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    base_url, service_token = _model_download_api_config()
    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(20.0), follow_redirects=False, trust_env=False
        ) as client:
            response = await client.request(
                method,
                f"{base_url}/{path.lstrip('/')}",
                params=params,
                json=payload,
                headers={"Authorization": f"Bearer {service_token}"},
            )
    except httpx.RequestError as error:
        logging.exception("Model download service request failed")
        raise HTTPException(
            status_code=503, detail="Model download service is unavailable"
        ) from error

    if response.status_code >= 400:
        try:
            detail = response.json().get("detail")
        except (ValueError, AttributeError):
            detail = None
        raise HTTPException(
            status_code=502,
            detail=detail if isinstance(detail, str) else "Model download request failed",
        )
    try:
        result = response.json()
    except ValueError as error:
        raise HTTPException(
            status_code=502, detail="Model download service returned an invalid response"
        ) from error
    if not isinstance(result, dict):
        raise HTTPException(
            status_code=502, detail="Model download service returned an invalid response"
        )
    return result


async def _refresh_managed_model_statuses(models: list[dict[str, Any]]) -> None:
    for model in models:
        if model.get("status") != "downloading":
            continue
        metadata = model.get("metadata")
        job_ids = metadata.get("job_ids") if isinstance(metadata, dict) else None
        if not isinstance(job_ids, list) or not job_ids:
            continue

        jobs: list[dict[str, Any]] = []
        for job_id in job_ids:
            if not isinstance(job_id, str):
                continue
            jobs.append(await _call_model_download("GET", f"/jobs/{job_id}"))

        statuses = [job.get("status") for job in jobs]
        if any(status in {"failed", "canceled"} for status in statuses):
            logs: list[str] = []
            for job_id, status in zip(job_ids, statuses):
                if status in {"failed", "canceled"}:
                    job_logs = await _call_model_download(
                        "GET", f"/jobs/{job_id}/logs"
                    )
                    logs.append(str(job_logs.get("logs", "")))
            await update_managed_model(
                model["id"], "failed", logs="\n\n".join(logs)
            )
        elif statuses and all(status == "completed" for status in statuses):
            await update_managed_model(model["id"], "ready")


def set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=token,
        max_age=SESSION_MAX_AGE_SECONDS,
        httponly=True,
        secure=os.getenv("AUTH_COOKIE_SECURE", "false").lower() == "true",
        samesite="lax",
        path="/v1/chatqna",
    )


@app.post("/auth/register")
async def register_account(payload: RegisterAccountRequest, response: Response):
    try:
        await ensure_service_setup()
        user = await create_account(
            payload.username, payload.password, role="standard"
        )
        token = await create_session(user["id"])
        set_session_cookie(response, token)
        return user
    except ServiceSetupIncomplete as e:
        logging.error(
            "Service setup is incomplete; configure CHATQNA_ADMIN_PASSWORD before "
            "enabling account registration."
        )
        raise HTTPException(
            status_code=503, detail="Service setup error."
        ) from e
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    except SQLAlchemyError as e:
        logging.exception("Failed to register account")
        raise HTTPException(
            status_code=503, detail="Account storage is unavailable"
        ) from e


@app.post("/auth/login")
async def login_account(payload: LoginAccountRequest, response: Response):
    try:
        await ensure_service_setup()
        user = await authenticate_account(payload.username, payload.password)
        if not user:
            raise HTTPException(status_code=401, detail="Invalid username or password")
        token = await create_session(user["id"])
        set_session_cookie(response, token)
        return user
    except ServiceSetupIncomplete as e:
        logging.error(
            "Service setup is incomplete; configure CHATQNA_ADMIN_PASSWORD before "
            "enabling account login."
        )
        raise HTTPException(
            status_code=503, detail="Service setup error."
        ) from e
    except SQLAlchemyError as e:
        logging.exception("Failed to log in")
        raise HTTPException(
            status_code=503, detail="Account storage is unavailable"
        ) from e


@app.get("/auth/me")
async def get_current_user(user: dict[str, Any] = Depends(require_user)):
    return user


@app.get("/admin/users")
async def get_admin_users(_admin: dict[str, Any] = Depends(require_admin)):
    try:
        return {"users": await list_user_accounts()}
    except SQLAlchemyError as error:
        logging.exception("Failed to load user accounts")
        raise HTTPException(
            status_code=503, detail="Account storage is unavailable"
        ) from error


@app.post("/admin/users", status_code=201)
async def create_admin_account(
    payload: RegisterAccountRequest,
    _admin: dict[str, Any] = Depends(require_admin),
):
    try:
        return await create_account(payload.username, payload.password, role="admin")
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except SQLAlchemyError as error:
        logging.exception("Failed to create administrator account")
        raise HTTPException(
            status_code=503, detail="Account storage is unavailable"
        ) from error


@app.put("/admin/users/{user_id}/role")
async def update_account_role(
    user_id: int,
    payload: AccountRoleRequest,
    _admin: dict[str, Any] = Depends(require_admin),
):
    try:
        user = await set_account_role(user_id, payload.role, _admin["id"])
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except SQLAlchemyError as error:
        logging.exception("Failed to update account group")
        raise HTTPException(
            status_code=503, detail="Account storage is unavailable"
        ) from error
    if user is None:
        raise HTTPException(status_code=404, detail="Account not found")
    return user


@app.post("/auth/change-password")
async def change_password(
    payload: ChangePasswordRequest,
    user: dict[str, Any] = Depends(require_user),
):
    try:
        changed = await change_account_password(
            user["id"], payload.current_password, payload.new_password
        )
    except SQLAlchemyError as error:
        logging.exception("Failed to change account password")
        raise HTTPException(
            status_code=503, detail="Account storage is unavailable"
        ) from error
    if not changed:
        raise HTTPException(status_code=400, detail="Current password is incorrect.")
    return {"status": "success"}


@app.get("/auth/huggingface-token")
async def get_huggingface_token_status(
    user: dict[str, Any] = Depends(require_user),
):
    try:
        configured = await has_user_huggingface_token(user["id"])
    except SQLAlchemyError as error:
        logging.exception("Failed to load Hugging Face token status")
        raise HTTPException(
            status_code=503, detail="Account storage is unavailable"
        ) from error
    return {"configured": configured}


@app.put("/auth/huggingface-token")
async def put_huggingface_token(
    payload: HuggingFaceTokenRequest,
    user: dict[str, Any] = Depends(require_user),
):
    try:
        await save_user_huggingface_token(
            user["id"], payload.token.get_secret_value()
        )
    except HFTokenEncryptionUnavailable as error:
        logging.error("Hugging Face token encryption is not configured correctly")
        raise HTTPException(
            status_code=503,
            detail="Secure token storage is not configured. Contact the administrator.",
        ) from error
    except SQLAlchemyError as error:
        logging.exception("Failed to save Hugging Face token")
        raise HTTPException(
            status_code=503, detail="Account storage is unavailable"
        ) from error
    return {"status": "success"}


@app.delete("/auth/huggingface-token")
async def remove_huggingface_token(
    user: dict[str, Any] = Depends(require_user),
):
    try:
        await delete_user_huggingface_token(user["id"])
    except SQLAlchemyError as error:
        logging.exception("Failed to delete Hugging Face token")
        raise HTTPException(
            status_code=503, detail="Account storage is unavailable"
        ) from error
    return {"status": "success"}


@app.get("/internal/model-download/users/{user_id}/huggingface-token")
async def exchange_huggingface_token(user_id: int, request: Request):
    service_token = os.getenv("MODEL_DOWNLOAD_SERVICE_TOKEN")
    authorization = request.headers.get("authorization", "")
    supplied_token = authorization.removeprefix("Bearer ").strip()
    if not service_token or len(service_token) < 32 or not service_token.isascii():
        raise HTTPException(
            status_code=503, detail="Service authentication is not configured"
        )
    if (
        not supplied_token
        or not supplied_token.isascii()
        or not hmac.compare_digest(supplied_token, service_token)
    ):
        raise HTTPException(status_code=401, detail="Service authentication required")

    try:
        token = await get_user_huggingface_token(user_id)
        if token is None:
            raise HTTPException(
                status_code=404, detail="No Hugging Face token is configured"
            )
        encrypted_token = encrypt_model_download_token(token)
    except HFTokenEncryptionUnavailable as error:
        logging.error("Hugging Face token exchange encryption is unavailable")
        raise HTTPException(
            status_code=503, detail="Secure token exchange is not configured"
        ) from error
    except SQLAlchemyError as error:
        logging.exception("Failed to load Hugging Face token for model download")
        raise HTTPException(
            status_code=503, detail="Account storage is unavailable"
        ) from error
    return {"encrypted_token": encrypted_token}


@app.post("/auth/logout")
async def logout_account(request: Request, response: Response):
    session_token = request.cookies.get(SESSION_COOKIE_NAME)
    if session_token:
        try:
            await delete_session(session_token)
        except SQLAlchemyError as e:
            logging.exception("Failed to end account session")
            raise HTTPException(
                status_code=503, detail="Account storage is unavailable"
            ) from e
    response.delete_cookie(
        key=SESSION_COOKIE_NAME,
        httponly=True,
        secure=os.getenv("AUTH_COOKIE_SECURE", "false").lower() == "true",
        samesite="lax",
        path="/v1/chatqna",
    )
    return {"status": "success"}


@app.get("/conversations")
async def get_conversations(user: dict[str, Any] = Depends(require_user)):
    try:
        exists, conversations = await get_user_conversation_history(user["id"])
        return {"exists": exists, "conversations": conversations}
    except SQLAlchemyError as e:
        logging.exception("Failed to load conversation history")
        raise HTTPException(
            status_code=503, detail="Conversation history storage is unavailable"
        ) from e


@app.get("/models")
async def list_models(_user: dict[str, Any] = Depends(require_user)):
    try:
        return {"models": await get_available_models()}
    except SQLAlchemyError as error:
        logging.exception("Failed to load available models")
        raise HTTPException(status_code=503, detail="Model catalog is unavailable") from error


@app.get("/settings/models")
async def list_managed_models(_user: dict[str, Any] = Depends(require_user)):
    try:
        installed_response = await _call_model_download("GET", "/models/available")
        installed_models = installed_response.get("models")
        if not isinstance(installed_models, list):
            raise HTTPException(
                status_code=502,
                detail="Model download service returned an invalid model catalog",
            )
        validated_models = [
            InstalledModel.model_validate(item).model_dump()
            for item in installed_models
        ]
        await sync_installed_models(validated_models)
        models = await get_model_catalog()
        await _refresh_managed_model_statuses(models)
        return {"models": await get_model_catalog()}
    except HTTPException:
        raise
    except SQLAlchemyError as error:
        logging.exception("Failed to load managed models")
        raise HTTPException(
            status_code=503, detail="Model catalog is unavailable"
        ) from error
    except (ValueError, TypeError) as error:
        logging.exception("Model download service returned invalid catalog data")
        raise HTTPException(
            status_code=502, detail="Model download service returned invalid catalog data"
        ) from error


@app.post("/settings/models", status_code=202)
async def request_managed_model(
    payload: ManagedModelRequest,
    user: dict[str, Any] = Depends(require_user),
):
    task_to_model_type = {
        "llm": "llm",
        "embedding": "embeddings",
        "reranker": "rerank",
    }
    try:
        model_id = await register_managed_model(
            payload.model_name,
            payload.task,
            payload.device,
            payload.precision,
            payload.is_ovms,
            user["id"],
        )
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except SQLAlchemyError as error:
        logging.exception("Failed to register requested model")
        raise HTTPException(
            status_code=503, detail="Model catalog is unavailable"
        ) from error

    try:
        response = await _call_model_download(
            "POST",
            "/models/download",
            params={"download_path": "settings-managed"},
            payload={
                "models": [
                    {
                        "name": payload.model_name,
                        "hub": "huggingface",
                        "type": task_to_model_type[payload.task],
                        "is_ovms": payload.is_ovms,
                        "config": {
                            "device": payload.device,
                            "precision": payload.precision,
                        },
                    }
                ],
                "credential_user_id": user["id"],
            },
        )
        job_ids = response.get("job_ids")
        if (
            not isinstance(job_ids, list)
            or not job_ids
            or not all(isinstance(job_id, str) for job_id in job_ids)
        ):
            raise HTTPException(
                status_code=502,
                detail="Model download service did not return valid job IDs",
            )
        await update_managed_model(model_id, "downloading", job_ids=job_ids)
    except HTTPException as error:
        try:
            await update_managed_model(
                model_id, "failed", logs=str(error.detail)
            )
        except SQLAlchemyError:
            logging.exception("Failed to persist model download failure")
        raise
    except SQLAlchemyError as error:
        logging.exception("Failed to save model download job")
        raise HTTPException(
            status_code=503, detail="Model download request could not be saved"
        ) from error
    return {"model_id": model_id, "job_ids": job_ids, "status": "downloading"}


@app.put("/settings/models/default")
async def update_default_model(
    payload: DefaultModelRequest,
    _user: dict[str, Any] = Depends(require_user),
):
    try:
        await set_default_model(payload.model_id)
        return {"status": "success"}
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except SQLAlchemyError as error:
        logging.exception("Failed to update default model")
        raise HTTPException(
            status_code=503, detail="Model catalog is unavailable"
        ) from error


@app.delete("/settings/models")
async def delete_managed_model(
    payload: DeleteManagedModelRequest,
    _admin: dict[str, Any] = Depends(require_admin),
):
    try:
        model = await get_managed_model_for_removal(payload.model_id)
        if model is None:
            raise HTTPException(status_code=404, detail="Model not found")
        if model["is_default"]:
            raise HTTPException(
                status_code=409,
                detail="Change the default model before removing it.",
            )
        if (
            model["status"] != "ready"
            or model["backend"] != "ovms"
            or not model["artifact_location"]
        ):
            raise HTTPException(
                status_code=409,
                detail="Only ready, installed OVMS models can be removed.",
            )

        if not await begin_managed_model_removal(payload.model_id):
            raise HTTPException(
                status_code=409,
                detail="The model changed while it was being removed. Refresh and retry.",
            )
        try:
            await _call_model_download(
                "DELETE",
                "/models/available",
                payload={
                    "model_name": model["model_name"],
                    "artifact_location": model["artifact_location"],
                },
            )
        except HTTPException:
            try:
                await cancel_managed_model_removal(payload.model_id)
            except SQLAlchemyError:
                logging.exception("Failed to restore model status after removal failed")
            raise
        if not await delete_managed_model_record(payload.model_id):
            raise HTTPException(
                status_code=409,
                detail="The model changed while it was being removed. Refresh and retry.",
            )
        return {"status": "success"}
    except HTTPException:
        raise
    except SQLAlchemyError as error:
        logging.exception("Failed to remove managed model")
        raise HTTPException(
            status_code=503, detail="Model catalog is unavailable"
        ) from error


@app.put("/conversations/{conversation_id}/model")
async def put_conversation_model(
    conversation_id: str,
    payload: ConversationModelRequest,
    user: dict[str, Any] = Depends(require_user),
):
    try:
        await set_user_conversation_model(
            user["id"], conversation_id, payload.model_id
        )
        return {"status": "success"}
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except SQLAlchemyError as error:
        logging.exception("Failed to save conversation model selection")
        raise HTTPException(
            status_code=503, detail="Conversation settings storage is unavailable"
        ) from error


@app.put("/conversations")
async def put_conversations(
    payload: ConversationHistoryRequest,
    user: dict[str, Any] = Depends(require_user),
):
    try:
        await save_user_conversation_history(user["id"], payload.conversations)
        return {"status": "success"}
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except SQLAlchemyError as e:
        logging.exception("Failed to save conversation history")
        raise HTTPException(
            status_code=503, detail="Conversation history storage is unavailable"
        ) from e



async def add_timing_to_generator(generator_func, *args, **kwargs):
    """Add timing to a generator function"""
    start_time = time.time()
    
    async def timed_generator():
        last_chunk_time = start_time
        
        try:
            async for chunk in generator_func(*args, **kwargs):
                last_chunk_time = time.time()
                yield chunk
            
            # Add timing info
            total_time = round((last_chunk_time - start_time) * 1000, 2)
            timing_data = f"data: {json.dumps({'response_time_ms': total_time, 'finished': True})}\n\n"
            yield timing_data
            
        except Exception as e:
            error_time = time.time()
            error_response_time = round((error_time - start_time) * 1000, 2)
            error_data = f"data: {json.dumps({'error': str(e), 'response_time_ms': error_response_time})}\n\n"
            yield error_data
    
    return timed_generator()

@app.post("/chat", response_class=StreamingResponse)
async def query_chain(
    payload: QuestionRequest,
    _user: dict[str, Any] = Depends(require_user),
):
    try:
        conversation_messages = payload.conversation_messages
        logging.info(conversation_messages)
        question_text = conversation_messages[-1].content

        max_tokens = payload.max_tokens if payload.max_tokens else 32768
        if max_tokens > 131073:
            raise HTTPException(status_code=422, detail="max tokens cannot be greater than 131073")
        if not question_text or question_text == "":
            raise HTTPException(status_code=422, detail="Question is required")
        
        if len(question_text.strip()) == 0:
            raise HTTPException(status_code=422, detail="Question cannot be empty or whitespace only")

        model_name = None
        if payload.conversation_id:
            model_name = await get_user_conversation_model(
                _user["id"], payload.conversation_id
            )

        # Add timing to the generator
        timed_generator = await add_timing_to_generator(
            process_chunks, 
            conversation_messages, 
            max_tokens,
            [attachment.model_dump() for attachment in payload.attachments],
            model_name,
        )
        
        return StreamingResponse(timed_generator, media_type="text/event-stream")
        
    except HTTPException:
        raise
    except SQLAlchemyError as error:
        logging.exception("Failed to load the conversation model selection")
        raise HTTPException(
            status_code=503, detail="Conversation settings storage is unavailable"
        ) from error
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")

  
    
@app.get("/metrics", tags=["metrics"], summary="Get system metrics")
async def get_system_metrics(ram_type: str):

    try:
        monitor = SystemMonitor()
        return StreamingResponse(monitor.return_all(), media_type="text/event-stream")
        
    
    except Exception as e:
        logging.error(f"Error getting system metrics. {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Error getting system metrics: {str(e)}",
        )
    

FastAPIInstrumentor.instrument_app(app)

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8080, reload=True)
