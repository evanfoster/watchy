import argparse
import asyncio
import base64
from distutils.util import strtobool
import os
import random
import string

from kubernetes_asyncio import client, config, utils
from pathlib import Path


def random_string(length: int) -> str:
    """Return a string of random lowercase letters"""
    return "".join(random.choices(string.ascii_lowercase, k=length))


def secret(*, name: str, namespace: str) -> dict:
    """Generate a Secret"""
    return {
        "apiVersion": "v1",
        "kind": "Secret",
        "metadata": {
            "labels": {"generated": "true"},
            "name": name,
            "namespace": namespace,
        },
        "type": "Opaque",
        "data": {
            "helloworld": base64.b64encode((random_string(4096)).encode()).decode(
                "utf-8"
            ),
        },
    }


async def run(secret_count: int, namespace: str):
    if bool(strtobool(os.getenv("USE_IN_CLUSTER_CONFIG", "false"))):
        config.load_incluster_config()
    else:
        await config.load_kube_config(
            config_file=os.getenv(
                "KUBECONFIG", str(Path("~/.kube/config").expanduser())
            ),
            persist_config=False,
        )
    async with client.ApiClient() as k8s_client:
        # we don't want to nom all the memory we just want to spew
        chunk_size = min(1000, secret_count)
        for _ in range(0, secret_count, chunk_size):
            futures = []
            for count in range(chunk_size):
                futures.append(
                    asyncio.ensure_future(
                        utils.create_from_dict(
                            k8s_client,
                            data=secret(name=random_string(8), namespace=namespace),
                            namespace=namespace,
                        )
                    )
                )
            await asyncio.gather(*futures)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("secret_count", type=int, default=50)
    parser.add_argument("-n", "--namespace", type=str, default="secretload")
    args = parser.parse_args()
    secret_count: int = args.secret_count
    namespace: str = args.namespace
    asyncio.run(run(secret_count, namespace))


if __name__ == "__main__":
    main()
