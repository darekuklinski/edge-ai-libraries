# ChatQnA startup script

The universal launcher supports Debian 12+, Ubuntu 22.04+, Linux Mint 21.3+,
Fedora 40+, RHEL/Rocky Linux 9+, Arch Linux, and Manjaro on x86_64 hosts with
Linux kernel 5.15 or newer. CPU and Intel GPU OVMS profiles are supported; GPU
use also requires a compatible Intel driver and `/dev/dri` render device. NPU
is not implemented.

1. From `sample-applications/chat-question-and-answer`, copy `.env.example` to
   `.env`.
2. Run `./easy-deploy.sh` from the sample directory. The launcher asks for a
   Hugging Face token (optional for public models), target device, and initial
   admin password if they are not configured. On first setup, the admin
   password is entered twice and provisions the `admin` account; it must be
   8-128 characters. Redeployment does not change an existing admin password.
   Missing token-encryption and model-service authentication keys are generated
   and saved to `.env` on the first launch.

Compose named volumes survive `podman compose down` and `podman system prune
-af`; an existing PostgreSQL volume keeps its admin account and password. The
launcher warns when it finds a prior project database. Only remove the data if
you intend to erase stored accounts, conversations, and documents:

```bash
podman compose down --volumes
```

Use `docker compose down --volumes` if Docker was used.

For a complete development reset of this sample, run
`../nuclear-cleanup.sh`. It removes the ChatQnA Compose containers, orphans,
named volumes, and service images while preserving `.env`, downloaded model
files, and resources belonging to other projects. Add `--full-clean` to also
remove the configured `MODEL_PATH` (only when it is inside this sample
directory). Use `--dry-run` to review the actions first. This operation
permanently deletes ChatQnA database and object-store data.

For unattended use, set `DEVICE` and `CHATQNA_ADMIN_PASSWORD` in `.env` or the
process environment before running `./easy-deploy.sh`. Set
`HUGGINGFACEHUB_API_TOKEN` only when using gated/private models. Environment
values override `.env`; missing required values cause a non-interactive run to
exit with an error instead of prompting.

The launcher installs missing host utilities. If no usable container runtime
is installed, it installs Podman and the distro's Podman Compose provider. It
does not upgrade the operating system or install GPU drivers. Application
Python dependencies run in the service containers; the launcher does not
depend on the host Python version.

Docker is used when its Compose plugin and daemon are available; otherwise a
working Podman Compose installation is selected. Set `CONTAINER_ENGINE=docker`
or `CONTAINER_ENGINE=podman` in `.env` to choose explicitly. Docker users must
have permission to access the daemon. Podman runs rootless and uses the
`keep-id` user namespace; Docker uses the host user namespace.
For Podman, the launcher prefixes unqualified backend and UI image names with
`localhost/` so Compose uses the locally built images instead of pulling from a
remote registry.

The launcher starts the full Compose stack in detached mode and waits up to 30
minutes for the API and inference services to become healthy. Inspect services
with `podman compose ps` and follow logs with `podman compose logs -f` (use
`docker compose` if Docker was selected). Run commands inside a service with
`podman exec -it <container> <command>` or `docker exec`.
The application is served at `http://<host-ip>:8101`. The first model download
and conversion may take a long time. Configure proxy and firewall settings
yourself if required.
