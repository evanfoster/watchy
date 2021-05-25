import signal
import os
import argparse
from pathlib import Path
from typing import List

from kubernetes_asyncio import client, config
from kubernetes_asyncio.client.api_client import ApiClient
import multiprocessing
import functools
import random
import asyncio
from concurrent.futures import Future, Executor, ProcessPoolExecutor, as_completed
from threading import Lock
import itertools


# Adapted from https://bugs.python.org/issue36054#msg353690
def get_cpu_count():
    cgroup_quota_file = Path('/sys/fs/cgroup/cpu/cpu.cfs_quota_us')
    cgroup_cfs_period_seconds_file = Path('/sys/fs/cgroup/cpu/cpu.cfs_period_us')
    cgroup_cpu_shares_file = Path('/sys/fs/cgroup/cpu/cpu.shares')
    if not cgroup_quota_file.exists():
        return multiprocessing.cpu_count()
    else:
        # Not useful for AWS Batch based jobs as result is -1, but works on local linux systems
        cpu_quota = int(cgroup_quota_file.read_text().rstrip())
    if cpu_quota != -1 and cgroup_cfs_period_seconds_file.exists():
        cpu_period = int(cgroup_cfs_period_seconds_file.read_text().rstrip())
        avail_cpu = int(cpu_quota / cpu_period)  # Divide quota by period and you should get num of allotted CPU to the container, rounded down if fractional.
    elif cgroup_cpu_shares_file.exists():
        cpu_shares = int(cgroup_cpu_shares_file.read_text().rstrip())
        # For AWS, gives correct value * 1024.
        avail_cpu = int(cpu_shares / 1024)
    return avail_cpu


def chunks(sequence: List, n: int):
    """Yield successive n-sized chunks from sequence."""
    for i in range(0, len(sequence), n):
        yield sequence[i:i + n]


class DummyExecutor(Executor):
    def __init__(self, **kwargs):
        self._shutdown = False
        self._shutdownLock = Lock()

    def submit(self, fn, *args, **kwargs):
        with self._shutdownLock:
            if self._shutdown:
                raise RuntimeError("cannot schedule new futures after shutdown")

            f = Future()
            try:
                result = fn(*args, **kwargs)
            except BaseException as e:
                f.set_exception(e)
            else:
                f.set_result(result)

            return f

    def shutdown(self, wait=True, **kwargs):
        with self._shutdownLock:
            self._shutdown = True


async def gab_loudly(
    gabber_count: int,
    shutdown_event: multiprocessing.Event,
    namespace: str = "default",
) -> None:
    print(
        f"gabber {gabber_count} sleeping a random amount before starting"
    )  # We're a thundering herd, but maybe this takes the edge off?
    await asyncio.sleep(random.randint(0, 4))
    async with ApiClient() as api:
        v1 = client.CoreV1Api(api)
        while not shutdown_event.is_set():
            await v1.list_namespaced_secret(namespace=namespace, timeout_seconds=86400, _request_timeout=86400, _preload_content=False,)


async def start(
    *,
    number_of_gabbers: int,
    shutdown_event: multiprocessing.Event,
    core_number: int,
    namespaces: List[str],
) -> None:
    if shutdown_event.wait(10 * core_number):
        return
    print(f"core {core_number} starting with {number_of_gabbers} gabbers")
    await config.load_kube_config(
        config_file=os.getenv("KUBECONFIG", str(Path("~/.kube/config").expanduser())),
        persist_config=False,
    )
    namespace_cycler = itertools.cycle(namespaces)
    jobs = [
        gab_loudly(n, shutdown_event, namespace=next(namespace_cycler))
        for n in range(number_of_gabbers)
    ]
    await asyncio.gather(*jobs)
    print("Job's done!")


def run(
    core_number,
    *,
    number_of_gabbers: int,
    shutdown_event: multiprocessing.Event,
    namespaces: List[str],
) -> None:
    asyncio.run(
        start(
            number_of_gabbers=number_of_gabbers,
            shutdown_event=shutdown_event,
            core_number=core_number,
            namespaces=namespaces,
        )
    )


def signal_handler(shutdown_event, sig, frame) -> None:
    print("You pressed Ctrl+C!")
    shutdown_event.set()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--debug", default=False, action="store_true")
    parser.add_argument("-n", "--namespace", default="default", type=str)
    parser.add_argument("gabber_count", type=int, default=50)
    args = parser.parse_args()
    print("I'm talking to you...")
    gabber_count: int = args.gabber_count
    debug: bool = args.debug
    namespaces: List[str] = list(filter(None, args.namespace.split(',')))
    _executor = ProcessPoolExecutor
    cpu_count = min(get_cpu_count(), gabber_count)
    if debug:
        _executor = DummyExecutor
        cpu_count = 1
    gab_chunks = gabber_count // cpu_count
    with multiprocessing.Manager() as manager:
        shutdown_event = manager.Event()
        gabber = functools.partial(
            run,
            number_of_gabbers=gab_chunks,
            shutdown_event=shutdown_event,
        )
        signal.signal(signal.SIGINT, lambda x, y: signal_handler(shutdown_event, x, y))
        signal.signal(signal.SIGTERM, lambda x, y: signal_handler(shutdown_event, x, y))

        futures = []
        with _executor(max_workers=cpu_count) as executor:
            if debug:
                breakpoint()
            for core, namespace_chunk in zip(range(cpu_count), itertools.cycle(chunks(namespaces, cpu_count))):
                futures.append(executor.submit(gabber, core, namespaces=namespace_chunk))

            for future in as_completed(futures):
                future.result()
            executor.shutdown(wait=True)


main()
