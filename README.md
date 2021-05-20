## Usage

1. Run `make setup` to create a Python `venv` and install the needed dependencies in it
1. Run `source venv/bin/activate`
1. Run `make create-secrets` to generate some secrets. Accepted env vars are `NAMESPACE` and `SECRET_COUNT`
1. Run `make run` (or just `make`) to watch all secrets across the cluster. Specify the `WATCH_COUNT` env var if you don't want the default of `50`
