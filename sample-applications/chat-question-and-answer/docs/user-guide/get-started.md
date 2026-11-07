# Get Started

The Chat Question & Answer (Chat Q&A) sample application is a modular
Retrieval-Augmented Generation (RAG) pipeline designed to help developers create
intelligent chatbots that answer questions based on enterprise data. This guide
covers the supported first-time deployment and basic use of the application.

## Prerequisites

- Verify that your system meets the [minimum requirements](./get-started/system-requirements.md).
- Use a supported x86_64 Linux distribution. The deployment launcher supports
  Debian 12+, Ubuntu 22.04+, Linux Mint 21.3+, Fedora 40+, RHEL/Rocky Linux 9+,
  Arch Linux, and Manjaro, with Linux kernel 5.15 or newer.
- A Hugging Face token is optional for the public default models. You need a
  token with access to use gated or private models.

## Default CPU Models

All embedding, reranker, and LLM models supported by the selected model serving
can be used with this sample application. Models can be downloaded from model
hubs such as Hugging Face. These public defaults are intended to allow a
tokenless CPU deployment.

| Task | Default Model |
| --- | --- |
| LLM | `TinyLlama/TinyLlama-1.1B-Chat-v1.0` |
| Embedding | `BAAI/bge-base-en-v1.5` |
| Reranker | `cross-encoder/ms-marco-MiniLM-L-2-v2` |

The TinyLlama OpenVINO artifact is about 640 MB; the BGE embedding artifact is
about 112 MB. Other models can be configured in `.env`.

### Gated Models

The default CPU models are public and can be downloaded without a token. To run
a gated or private model, provide a Hugging Face token and request access on
the model's Hugging Face page. Create a token at
[Hugging Face tokens](https://huggingface.co/settings/tokens).

## Deploying for the first time

Use the sample's deployment launcher as the supported way to deploy. Do not
start the Compose stack directly; the launcher configures the selected device,
downloads and prepares the models, starts the services, and waits for the
application health check.

1. Clone the repository (use your fork URL if applicable) and enter the sample:

   ```bash
   git clone https://github.com/open-edge-platform/edge-ai-libraries.git
   cd edge-ai-libraries/sample-applications/chat-question-and-answer
   ```

2. Create your local configuration:

   ```bash
   cp .env.example .env
   ```

   The default CPU models are public, so you can leave
   `HUGGINGFACEHUB_API_TOKEN` blank. Set a token in `.env` or enter one when
   prompted to use gated/private models. Set `DEVICE=CPU` or `DEVICE=GPU` in
   `.env`; CPU is the default in the example. The launcher generates and saves
   the local encryption and service-authentication keys needed by account
   token settings when those values are blank.
   GPU deployment requires a supported Intel GPU driver and `/dev/dri` render
   device.

3. Start the deployment:

   ```bash
   ./easy-deploy.sh
   ```

   If `CHATQNA_ADMIN_PASSWORD` is not configured, the launcher securely prompts
   for and confirms an initial admin password (8-128 characters). On first
   setup, it provisions the `admin` account with that password. After the
   deployment is healthy, the launcher displays the admin username and
   password once for this new database. Store them securely. The password is
   not displayed while typing. A later deployment does not reset or redisplay
   an existing account's password; the launcher warns if it finds an existing
   database volume that will be reused.

The launcher installs missing host utilities and selects Docker Compose or
Podman Compose. It starts the stack in detached mode and waits up to 30 minutes
for the API and inference models to become healthy. Check service status and
follow deployment logs with:

```bash
podman compose ps
podman compose logs -f
```

Use `docker compose` instead if Docker was selected. You can interact with a
running service using `podman exec -it <container> <command>` (or
`docker exec`); for example, `podman exec -it chatqna-ui sh`.
For Podman, the launcher uses local image names for the backend and UI builds
so Compose runs the images it just built rather than resolving them from a
remote registry.

When ready, open `http://localhost:8101` (or `http://<host-ip>:8101` from
another device). Use the dashboard to add documents or HTTPS links to a context
and start a Q&A session. The first model download can take a while.

### Unattended deployment

For CI or other non-interactive deployments, configure required inputs in
`.env` or export them before running the launcher. Provide the target device
and a unique initial admin password. A Hugging Face token is optional when
using public models:

```bash
export DEVICE=CPU
export CHATQNA_ADMIN_PASSWORD='your-unique-password'
./easy-deploy.sh
```

Add `HUGGINGFACEHUB_API_TOKEN` to the environment or `.env` when using a
gated/private model. Environment values take precedence over `.env`.
Alternatively, set these values in the local `.env` file. Keep `.env` private
and do not commit it. The launcher exits with an error instead of waiting for
input when required values are missing in a non-interactive session.

### Resetting a deployment

Compose keeps named data volumes when containers are stopped or removed.
`podman system prune -af` does not remove these named volumes, so running
`./easy-deploy.sh` again reuses the PostgreSQL database and its existing
accounts. The initial admin password is not a password-reset mechanism.

To deliberately start with an empty database and object store, stop the stack
and remove its project volumes with the same container engine used to deploy:

```bash
podman compose down --volumes
```

Use `docker compose down --volumes` if Docker was selected. This permanently
deletes this deployment's stored accounts, conversations, and uploaded
documents. Do this only when you intend to discard that data. Otherwise, sign
in with the existing admin password and change it in the application settings.

For a development reset that also removes this Compose project's service
images and orphan containers, use the sample cleanup script:

```bash
./nuclear-cleanup.sh
```

It preserves `.env`, the model cache, and resources belonging to other
projects. Add `--full-clean` to also remove the configured model cache under
the sample directory, or `--dry-run` to inspect the cleanup actions first.
The cleanup deletes this project's database and object-store data.

### Verify the application

The launcher reports the application URL once the API and configured inference
models are healthy. You can also check the services with:

```bash
podman ps
```

If Docker was selected, use `docker ps` instead.

## Running in Kubernetes

Refer to [Deploy with Helm](./get-started/deploy-with-helm.md) for details.
This section requires validation; Kubernetes deployment is not guaranteed for
this fork.

## Running Tests

1. Ensure you have the environment variables set up as mentioned in the setup
   section.
2. Run the tests using `pytest`:

   ```sh
   cd sample-applications/chat-question-and-answer/tests/unit_tests/
   poetry run pytest
   ```

## Advanced Setup Options

For building the sample from source, see [How to Build from Source](./get-started/build-from-source.md).

## Related Links

- [How to Test Performance](./how-to-performance.md)

<!--hide_directive
:::{toctree}
:hidden:

./get-started/system-requirements
./get-started/build-from-source
./get-started/deploy-with-helm

:::
hide_directive-->
