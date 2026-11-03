# System Requirements

This page provides detailed hardware, software, and platform requirements to help you set up and run the application efficiently.

## Hardware Platforms used for validation (applies to this fork only, for intel's EAL this may vary)

- Intel® Arc&trade; A770 GPU with following Core&trade; configurations:
  - AMD Ryzen 5 7800X3D
  - AMD Ryzen 5 3600

## Operating Systems used for validation

- Debian 12+, Ubuntu 22.04+, Linux Mint 21.3+, Fedora 40+, RHEL/Rocky Linux 9+, Arch Linux, and Manjaro on x86_64 hosts withLinux kernel 5.15 or newer
- If GPU is available, refer to the official [documentation](https://dgpu-docs.intel.com/devices/hardware-table.html) for details on required kernel version. For the listed hardware platforms, the kernel requirement translates to specified distro depending on the GPU used.

## Minimum Configuration

The recommended minimum configuration depends on the model serving used.

- For OVMS based deployment, recommendation for memory is 64GB and storage is 128 GB. This is applicable for any distro
Memory configuration can be reduced by changing the default KV_CACHE_SPACE to a lower value. Lower KV_CACHE has impact on the performance and accuracy of the pipeline

Further requirements is dependent on the specific configuration of the application like KV cache, context size etc. Any changes to the default parameters of the sample application should be assessed for memory and storage implications. Raise a git issue in case of any required support for smaller configurations.

## Software Requirements

The software requirements to install the sample application are provided in other documentation pages and is not repeated here.

## Compatibility Notes

**Known Limitations**:

- None

## Validation

- Ensure all dependencies are installed and configured before proceeding to [Get Started](../get-started.md).
