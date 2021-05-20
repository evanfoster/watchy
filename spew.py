import argparse
import asyncio
import base64
import random
import string
from pathlib import Path

from kubernetes_asyncio import client, config, utils


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
    await config.load_kube_config(
        config_file=str(Path(".").absolute() / "kubeconfig.yaml"),
        context="default",
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
