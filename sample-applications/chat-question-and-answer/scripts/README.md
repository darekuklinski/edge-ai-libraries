# ChatQnA startup script

The universal launcher supports Debian 12+, Ubuntu 22.04+, Linux Mint 21.3+,
Fedora 40+, RHEL/Rocky Linux 9+, Arch Linux, and Manjaro on x86_64 hosts with
Linux kernel 5.15 or newer. CPU and Intel GPU OVMS profiles are supported; GPU
use also requires a compatible Intel driver and `/dev/dri` render device. NPU
is not implemented.

1. From `sample-applications/chat-question-and-answer`, copy `.env.example` to
   `.env` and update the required settings.
2. Run `bash scripts/run_chatQnA.sh`.
3. Provide a Hugging Face token and choose CPU or GPU if they are not set in
   `.env`.

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

The launcher starts the full Compose stack in a tmux session and waits up to 30
minutes for the API. Attach to its logs with `tmux attach-session -t chatqna`.
The application is served at `http://<host-ip>:8101`. The first model download
and conversion may take a long time. Configure proxy and firewall settings
yourself if required.

`run_chatQnA_fedora44.sh` remains as a compatibility alias to the universal
launcher.
