## Setup

### Using Docker

The docker container I've pushed is using Pyston instead of CPython. I found that Pyston allowed me to create many more watches, so this is recommended if you're planning on doing more than ~1K watches.

1. Export your $KUBECONFIG, being sure to use an absolute path
1. Run `docker run --rm -it --mount type=bind,source="$KUBECONFIG",target=/app/kubeconfig.yaml evanfoster/secret-watchy:latest bash`
1. Inside the container, run `export KUBECONFIG=kubeconfig.yaml`

### Using `make` on your system

This depends on you having Python 3.7+ on your system. A working compiler may or may not be necessary depending on wheels and such.

1. Run `make setup` to create a Python `venv` and install the needed dependencies in it
1. Run `source venv/bin/activate`

## Usage

Both tools will use `~/.kube/config` if no `$KUBECONFIG` is set. There's currently no option to switch contexts, so select the proper one before you start.

The following auth methods are supported by the [async k8s client](https://github.com/tomplus/kubernetes_asyncio) I'm using:
> gcp-token (only via gcloud command), user-token, oidc-token, user-password, in-cluster

1. Run `make create-secrets` to generate some secrets. Accepted env vars are `NAMESPACE` and `SECRET_COUNT`
1. Run `make run` (or just `make`) to watch all secrets across the cluster. Specify the `WATCH_COUNT` env var if you don't want the default of `50`
