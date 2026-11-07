# How It Works

The Chat Question & Answer (Chat Q&A) sample application is a RAG based chatbot pipeline that allows developers to customize and deploy the sample application in an on-prem environment and on their private documents without compromising on the accuracy of the responses. The application is built on a modular microservices approach using popular [LangChain framework](https://www.langchain.com/). This page provides a technical overview of the application’s architecture, components, and extensibility.

## Purpose

The Chat Q&A sample application is designed to:

- Demonstrate how Intel Edge AI catalog of inference microservices can be used to quickly build and deploy on Intel Edge AI systems portfolio.
- Serve as a blueprint for building similar scalable and modular solutions that can be deployed on Intel Edge AI systems.
- Showcase how popular frameworks like LangChain can be used to quickly implement a sample application and deploy the same on Intel Edge AI systems.
- Showcase the competitiveness of Intel Edge AI systems to address varied deployment scenario requirements (edge to cloud).
- Provide reference sample microservices for capabilities like document ingestion and UI front end that reduces the effort to customize the application.

## Detailed Architecture

The Chat Q&A application is a combination of the core LangChain application logic that implements the Chat Q&A pipeline and the set of microservices that implements the salient blocks of a RAG based Chat Q&A application. The figure below illustrates the setup. The Chat Q&A UI communicates with the Chat Q&A backend application. The LLM, Reranker, and Embedding microservices are provided as part of Intel Edge AI inference microservices catalog supporting a rich set of open-source models that can be downloaded from popular model hubs like [Hugging Face OpenVINO](https://huggingface.co/OpenVINO). The document ingestion microservice provides capability to ingest popular document types, convert it into embedding space, and store it in the VectorDB. A copy of the document can also be saved to the object store.

### Technical Architecture Diagram

![Technical Architecture Diagram](./_assets/TEAI_ChatQnA_Arch.png)
**Figure 1**: Detailed Architecture of the Chat Q&A sample application

### Application Flow

1. **Input Sources**:
   - **Documents**: The document ingestion microservice supports processing files in multiple formats, including .pdf, .txt, and .docx.

   - **Web pages (PoC)**: Contents of accessible web pages can also be parsed and used as input for the RAG pipeline.

     > **Note**: URL-based ingestion is currently implemented as a proof of concept (PoC). This application works best with non–JavaScript-heavy pages (e.g., Wikipedia, blogs, news sites) that render most of their content directly in HTML. JavaScript-heavy pages (e.g., social media platforms, single-page applications) load content dynamically via JavaScript, so their raw HTML often lacks useful text. The current implementation only parses raw HTML and does not execute JavaScript, so such pages may return incomplete or inaccurate results and should be avoided or handled separately.

     > Sometimes, even certain static Wikipedia pages may not yield meaningful content, as the current HTML-to-text conversion can extract navigation menus or metadata instead of the main article body. Since URL processing is primarily a proof of concept, it can be extended based on specific use cases by enhancing the document-ingestion microservice capabilities.

2. **Create the context**
   - **Upload input documents and web links**: The UI microservice allows the developer to interact with the Chat Q&A backend. It provides the interface to upload the documents and weblinks on which the RAG pipeline will be executed. The documents are uploaded and stored in an S3-compatible object store (RustFS in Docker Compose, MinIO in Helm).
   - **Convert to embeddings space**: The Chat Q&A backend microservice creates the embeddings out of the uploaded documents and web pages using the document ingestion microservice. The Embeddings microservice is used to create the embeddings. The embeddings are stored in a vector database. PGVector is used in the sample application.
3. **Chat flow**
   - **Ask a query**: The UI microservice provides prompt window in which the query is asked.
   - **Chat history management**: The application maintains conversation history, allowing users to:
     - Continue conversations across sessions
     - View and manage multiple conversation threads
     - Switch between conversations and access previous questions and responses for context
   - **Accounts**: Before first use, configure `CHATQNA_ADMIN_PASSWORD` in Compose `.env` or provide the Helm Secret named by `global.adminPasswordSecretName` with a `password` entry. This securely provisions the default `admin` account during first authentication when the database has not already been initialized. It does not reset an existing account's password when a deployment reuses its PostgreSQL volume. Until setup is complete, login and account creation are disabled and return a generic service setup error. After setup, public sign-up creates standard accounts only. Administrators can use Settings → Admin to create admin accounts and promote or downgrade existing accounts; only administrators can remove installed OVMS models from the server and database. Password hashes, account groups, sessions, and each user's conversation history are stored in PostgreSQL. The UI uses an HTTP-only session cookie and displays the signed-in username in the header; use its menu to log out. Passwords must be 8–128 characters when creating an account or changing a password.

### Account groups and administrator tasks

Chat Q&A has two account groups:

- **Standard**: the group assigned to every account created through the public
  sign-up form. Standard users can use the chat, manage their own password and
  Hugging Face token, and request or select models.
- **Admin**: can do everything a standard user can, and can open Settings →
  **Admin** to review accounts, promote or downgrade users, or create an
  administrator account. Admins can also remove installed OVMS models from
  Settings → **Models**.

The bootstrap `admin` account is assigned to the Admin group. The Admin tab is
only shown to administrators, but the backend independently authorizes every
administrative API request. At least one administrator must remain, and an
administrator cannot remove their own administrator privileges.

For automation, the authenticated API is rooted at `/v1/chatqna`. Sign in first
to receive the HTTP-only `chatqna_session` cookie. Public registration has no
role field and always creates a standard account:

```bash
curl -sS -o /dev/null -w 'HTTP %{http_code}\n' -c chatqna.cookies \
  -H 'Content-Type: application/json' \
  -d '{"username":"new-user","password":"replace-with-a-unique-password"}' \
  http://localhost:8100/v1/chatqna/auth/register
```

Use the browser sign-in flow or `/auth/login` to authenticate an existing
administrator. For example, sign in and save the session cookie with:

```bash
curl -sS -o /dev/null -w 'HTTP %{http_code}\n' -c admin.cookies \
  -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"replace-with-the-admin-password"}' \
  http://localhost:8100/v1/chatqna/auth/login
```

Keep the cookie jar private. An administrator can list accounts,
promote an account, or create another administrator as follows:

```bash
curl -b admin.cookies http://localhost:8100/v1/chatqna/admin/users

curl -X PUT -b admin.cookies \
  -H 'Content-Type: application/json' \
  -d '{"role":"admin"}' \
  http://localhost:8100/v1/chatqna/admin/users/42/role

curl -X POST -b admin.cookies \
  -H 'Content-Type: application/json' \
  -d '{"username":"backup-admin","password":"replace-with-a-unique-password"}' \
  http://localhost:8100/v1/chatqna/admin/users
```

Replace user ID `42` with the ID returned by the user-list endpoint. To
downgrade an account, send `"role":"standard"` to the same role endpoint.

### Removing an installed model

From Settings → Models, an administrator can remove an installed model that is
not currently a task default. The confirmation removes the model files from
the shared OVMS model directory, its OVMS configuration references, and the
ChatQnA catalog record. Change the task default first if the model is currently
marked **Default**. In-progress, failed, non-OVMS, and otherwise uninstalled
entries cannot be removed through this action. Existing conversations that
referenced the removed model will no longer have that model selection.

The UI performs this operation through the authenticated
`DELETE /v1/chatqna/settings/models` endpoint:

```bash
curl -X DELETE -b admin.cookies \
  -H 'Content-Type: application/json' \
  -d '{"model_id":"MODEL_CATALOG_ID"}' \
  http://localhost:8100/v1/chatqna/settings/models
```

This is a destructive operation on shared model files. Back up or redownload a
model if it may be needed later.
   - **Execute the RAG AI pipeline**: The Chat Q&A backend microservice performs the following actions to generate the output response using the RAG pipeline.
      -   The query is converted into embedding space using the Embeddings microservice.
      - Semantic retrieval is done to fetch the relevant documents or data points from VectorDB. The reranker microservice ranks them in order of accuracy.
      - The retrieved documents and data points is used as part of the prompt to the LLM model and a response is generated using the LLM microservice which hosts the configured LLM model.
   - **Optional file attachments**: Use the paperclip beside the prompt to upload a local PDF, TXT, or DOCX file, or select a file already in the Data Source library. Uploaded files are added to that shared library and embedded by the document-ingestion service (maximum upload size: 100 MB). Retrieval for that question is limited to its selected files; if no file is attached, the application keeps its existing retrieval across the shared knowledge base. Retrieved text is included in the LLM prompt alongside the question and model knowledge.
4. **Output Generation**:
   - **Response**: The generated response from the LLM microservice is sent to the UI for display and consumption by the user.
   - **Observability dashboard**: If set up, the dashboard displays real-time logs, metrics, and traces providing a view of the performance, accuracy, and resource consumption by the application.

Conversation history is synchronized to the pgvector PostgreSQL database and restored after login. History is scoped to the account, not the browser. The Compose deployment stores PostgreSQL data in the `pgvector-data` named volume, which survives `docker compose down` and container recreation; `docker compose down -v` removes it. Chat messages are no longer persisted in browser localStorage.

### Hugging Face token exchange

Per-user Hugging Face tokens are stored encrypted in PostgreSQL and are never returned by the user-facing API. When an authenticated service requests a model download for a user, `model-download` authenticates to ChatQnA with `MODEL_DOWNLOAD_SERVICE_TOKEN`. ChatQnA encrypts the token with the separate `MODEL_DOWNLOAD_TOKEN_EXCHANGE_KEY`; only model-download decrypts it, in memory, for that request. The downloader rejects requests that specify a user credential without the service token.

Configure both values as high-entropy secrets shared only by the ChatQnA and model-download containers. In Compose, set them in `.env`; in Kubernetes, create the same `service-token` and `encryption-key` Secret entries for both deployments and configure the corresponding secret names. The Fernet exchange key must be generated once and kept stable. It is separate from `HF_TOKEN_ENCRYPTION_KEY`, which protects tokens at rest. The model-download exchange URL should resolve to the ChatQnA service over the private container/cluster network; the encrypted response protects the HF token in transit. Existing non-user-scoped downloads and startup-model configuration retain their current environment-token behavior.

Create an optional host-side database dump while the database is running:

```bash
bash scripts/backup-pgvector.sh
```

The dump is written to `backups/` by default (or to the directory passed as the script's first argument). It includes account records, sessions, vector data, and conversation history. The database stores password hashes rather than plaintext passwords. For deployments served over HTTPS, set `AUTH_COOKIE_SECURE=true` in `.env` so session cookies are restricted to secure connections. This sample does not include password reset or account recovery.

The application flow is illustrated in the flow diagram below. The diagram shows the API used and the data sharing protocol.
![Data flow diagram](./_assets/request.jpg)
**Figure 2:** Dataflow for the Chat Q&A sample application

## Key Components and Their Roles

1. **Intel Edge AI Inference microservices**:
   - **What it is**: Inference microservices are the LLM, Embeddings, and Reranker microservices that run the chosen models optimally on the hardware.
   - **How it's used**: Each of the microservices uses OpenAI APIs to support their functionality. The microservices are configured to use the required models and launched. The Chat Q&A backend accesses these microservices in the LangChain application which creates a RAG chain out of these microservices.
   - **Benefits**: The default configuration of these microservices as provided by the sample application is guaranteed to perform optimally for the chosen models and on the target deployment hardware. Standard OpenAI API ensures easy portability of different inference microservices.

2. **Document ingestion microservice**:
   - **What it is**: Document ingestion microservice provides capability to ingest contents from documents and web links, create the necessary context, and retrieve the right context based on user query.
   - **How it's used**: Document ingestion microservice provides a `documents` REST API endpoint that can be used to manage the contents. The Chat Q&A backend uses this API to access its capabilities.
   - **Benefits**: The core part of the document ingestion microservice is the vector handling capability which is optimized for target deployment hardware. Selection of the vectorDB is based on performance considerations. Rest of the document ingestion microservice can be treated as sample reference implementation.

3. **Chat Q&A backend microservice**:
   - **What it is**: The Chat Q&A backend microservice is a LangChain based implementation of the Chat Q&A RAG pipeline providing required handling of the user queries.
   - **How it’s used**: A `streamlog` REST API endpoint is provided which is used by the UI front end to send user queries and trigger the RAG pipeline.
   - **Benefits**: The microservice provides a reference of how LangChain framework is used to implement Chat Q&A using Intel Edge AI inference microservices.

4. **Chat Q&A UI**:
   - **What it is**: A reference front end providing an interface for users to interact with the Chat Q&A RAG pipeline.
   - **How it’s used**: The UI microservice runs on the deployed HW on a certain configured port. Accessing the specific URL allows users to use the UI. Signed-in users can open Settings from the username menu to change their password, save a Hugging Face token, and manage models. The Models tab lists models found in the shared OVMS model directory, lets users request downloads/conversions from Hugging Face, and set task-specific defaults for LLM, embedding, and reranker models. Download status and failure logs are available in the same tab.
   - **Benefits**: This microservice should be treated as a sample reference implementation.

5. **pgvector database**
   - **What it is**: PostgreSQL with the pgvector extension.
   - **How it's used**: It stores document embeddings and application account data. The Chat Q&A backend also maintains a model catalog (`chat_models`), each user's conversation-to-LLM selection (`chat_user_conversations`), and a SHA-256 digest plus encrypted Hugging Face token per account.
     Conversation history remains in its existing JSONB table for compatibility.
   - **Benefits**: Model metadata and per-conversation choices are persistent database records, separate from model weight files. Hugging Face tokens are not returned by the API; the digest supports one-way storage while the encrypted copy is reserved for future authenticated model downloads. Configure a stable `HF_TOKEN_ENCRYPTION_KEY` outside the database (for example via a secrets manager) and back it up securely; without it, tokens cannot be saved or decrypted. For Helm, create the Kubernetes Secret named by `global.huggingface.tokenEncryptionKeySecretName` with an `encryption-key` entry.
     The catalog stores model names, task, status, defaults, and artifact locations; model weights remain in the shared OVMS model directory. Per-conversation LLM selections are stored separately. Hugging Face tokens are not returned by the API; the digest supports one-way storage while the encrypted copy is used for authenticated model downloads. Configure a stable `HF_TOKEN_ENCRYPTION_KEY` outside the database (for example via a secrets manager) and back it up securely; without it, tokens cannot be saved or decrypted. For Helm, create the Kubernetes Secret named by `global.huggingface.tokenEncryptionKeySecretName` with an `encryption-key` entry. Model downloads also require the ChatQnA and model-download service credentials and token-exchange key to be configured; Compose users can set these in `.env`, while Helm users should configure the corresponding chart secrets.

6. **Metrics Manager microservice**
   - **What it is**:
   - **How it's used**:
   - **Benefits**:


## Extensibility

The Chat Q&A sample application is designed with modularity in mind, allowing developers to:

1. **Change inference microservices**:
   - The default option is OVMS for LLM and embeddings, and TEI for the reranker.
   - (*Deprecated effective 2025.2.0*) Use other model servers like vLLM with OpenVINO backend, and TGI to host LLM models.
   - Mandatory requirement is OpenAI API compliance. Note that other model servers are not guaranteed to provide same performance as default options.
2. **Load different LLM, Embedding, and Reranker models**:
   - Use different models from Hugging Face OpenVINO model hub or vLLM model hub. The models are passed as a parameter to corresponding model servers. (*vLLM support is deprecated effective 2025.2.0*)
3. **Use other GenAI frameworks like Haystack and LlamaIndex**:
   - Integrate the inference microservices into an application backend developed on other frameworks similar to the LangChain integration provided in this sample application.
4. **Deploy on diverse Intel target hardware and deployment scenarios**:
   - Follow the system requirements guidelines on the different options available.

## Next Steps

- [Get Started](./get-started.md)
- [Benchmarks](./benchmarks.md)