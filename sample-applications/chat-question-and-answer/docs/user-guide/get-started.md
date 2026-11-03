# Get Started

<!--
**Sample Description**: Provide a brief overview of the application and its purpose.
-->

The Chat Question & Answer (Chat Q&A) sample application is a modular Retrieval Augmented Generation (RAG) pipeline designed to help developers create intelligent chatbots that can answer questions based on enterprise data. This guide will help you set up, run, and modify the Chat Q&A sample application on Intel Edge AI systems.

<!--
**What You Can Do**: Highlight the developer workflows supported by the guide.
-->

By following this guide, you will learn how to:

- **Set up the sample application**: Use Docker Compose to quickly deploy the application in your environment.
- **Run the application**: Execute the application to see real-time question answering based on your data.
- **Modify application parameters**: Customize settings like inference models and deployment configurations to adapt the application to your specific requirements.

## Prerequisites

- Verify that your system meets the [minimum requirements](./get-started/system-requirements.md).
- Install Docker or equivalent (f.ex. podman)
- Install Docker Compose or equivalent (f.ex podman compose)
- Install `Python 3.12`.
- `jq` command-line JSON processor: [Installation Guide](https://jqlang.org/download/).

<!--
**Setup and First Use**: Include installation instructions, basic operation, and initial validation.
-->

## Supported Models

All models - embedding, reranker, and LLM - which are supported by the chosen model serving can be used with this sample application. The models can be downloaded from popular model hubs like Hugging Face. Refer to respective model hub documentation for details on how to access and download models.

The sample application has been validated with a few models just to validate the functionality. This list is only illustrative and the user is not limited to only these models.

### Embedding Models validated for each model server

   | Model Server | Models Validated |
   |--------------|------------------|
   | `OVMS` | `Alibaba-NLP/gte-large-en-v1.5`, `nomic-ai/nomic-embed-text-v1.5` |

### LLM Models validated for each model server
| Model Server | Models Validated |
   |--------------|-------------------|
   | `OVMS` | `Intel/neural-chat-7b-v3-3`, `Qwen/Qwen2.5-7B-Instruct`, `OpenAI/gpt-oss-20b` |

**Note:**

1. Limited validation was done on gpt-oss model.

### Reranker Models validated

   | Model Server | Models Validated  |
   |--------------|-------------------|
   | `TEI` | `BAAI/bge-reranker-base` |

### Getting access to models

To run a **GATED MODEL** like llama models, the user will need to pass their [Hugging Face token](https://huggingface.co/docs/hub/security-tokens#user-access-tokens). The user will need to request access to specific model by going to the respective model page in HuggingFace.

Visit the [Hugging Face tokens](https://huggingface.co/settings/tokens) page to get your token.

## Running the application using Docker Compose

<!--
**User Story 1**: Setting Up the Application
- **As a developer**, I want to set up the application in my environment, so that I can start exploring its functionality.

**Acceptance Criteria**:
1. Step-by-step instructions for downloading and installing the application.
2. Verification steps to ensure successful setup.
3. Troubleshooting tips for common installation issues.
-->

1. **Clone the Repository**:
   Clone the repository.

   ```bash
   # Clone the latest on mainline
   git clone https://github.com/darekuklinski/edge-ai-libraries.git edge-ai-libraries

   Note: Adjust the repo link appropriately in case of forked repo.


2. **Navigate to the Directory**:
   Go to the directory where the Docker Compose file is located:

   ```bash
   cd edge-ai-libraries/sample-applications/chat-question-and-answer
   ```

3. **Set Up Environment Variables**:
    Set up the environment variables based on the inference method you plan to use:

    ```bash
    cp .env.example .env
    ```

   > Adjust section in .env with required fields like hf_token, and if needed adjust device, if Your system does not have GPU

    For detailed guidance on configuring __ALLOWED_HOSTS__ for different deployment scenarios, refer to [ALLOWED_HOSTS Configuration](https://docs.openedgeplatform.intel.com/dev/edge-ai-libraries/pgvector/get-started.html#allowed-hosts-configuration)

    __NOTE__: If the system has an integrated GPU, its id is always 0 (GPU.0). The GPU is an alias for GPU.0. If a system has multiple GPUs (for example, an integrated and a discrete Intel GPU) It is done by specifying GPU.1,GPU.0 as a __DEVICE__

    Refer to the supported model list in the [Get Started](./get-started.md) document.

   Usage of scripts/run_chatQnA.sh is strongly recommended for users using other distro than fedora.
   Setup script is interactive, so it will perform full setup. No need of applying .env changes manually

   Power users can launch compose directly as well.
   When launching Compose directly instead of using `setup.sh`, keep `DEVICE`, `COMPOSE_PROFILES`, and `STARTUP_MODELS_CONFIG_HOST_PATH` aligned in `.env`:

   | Device | `COMPOSE_PROFILES` | `STARTUP_MODELS_CONFIG_HOST_PATH` |
   | --- | --- | --- |
   | CPU | `OVMS` | `./startup-models-cpu.yaml` |
   | GPU | `GPU-OVMS` | `./startup-models-gpu.yaml` |

   The GPU OVMS profile exposes `/dev/dri`. Selecting the CPU OVMS profile with GPU-configured models leaves OVMS without a GPU device and can make it terminate during model initialization.

4. **Start the Application**:
   Start the application using Podman Compose:

   ```bash
   podman compose up # Replace with other solution in case of using Debina-based linux
   ```

   If you changed the `metrics-manager` Dockerfile, rebuild that service first; plain `docker compose up` may reuse an older image:

   ```bash
   podman compose build metrics-manager
   podman compose up
   ```

   - Refer to [the application architecture diagram](./how-it-works.md#technical-architecture-diagram) .

6. **Verify the Application**:
   Check that the application is running:

   ```bash
   podman ps
   ```

7. **Access the Application**:
   Open a browser and go to `http://localhost:8101` to access the application dashboard. The application dashboard allows the user to,
    - Create and manage context by adding documents (pdf, docx, etc.) and web links (only https).
    > **Note**:
    > - There are restrictions on the max size of the document allowed.
    > - Only HTTPS URLs are allowed for web links.
    - Start Q&A session with the created context.

## Running in Kubernetes

Refer to [Deploy with Helm](./get-started/deploy-with-helm.md) for the details. Ensure the prerequisites mentioned on this page are addressed before proceeding to deploy with Helm.
> This section requires validation. No warranty on kubernetes with this fork

## Running Tests

1. Ensure you have the necessary environment variables set up as mentioned in the setup section.

2. Run the tests using `pytest`:

   ```sh
   cd sample-applications/chat-question-and-answer/tests/unit_tests/
   poetry run pytest
   ```

## Advanced Setup Options

For alternative ways to set up the sample application, see:

- [How to Build from Source](./get-started/build-from-source.md)

## Related Links

- [How to Test Performance](./how-to-performance.md)

## Supporting Resources

- [Docker Compose Documentation](https://docs.docker.com/compose/)

<!--hide_directive
:::{toctree}
:hidden:

./get-started/system-requirements
./get-started/build-from-source
./get-started/deploy-with-helm

:::
hide_directive-->
