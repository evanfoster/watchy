import signal
import os
import argparse
from distutils.util import strtobool
from pathlib import Path
from typing import List

import aiohttp
import aiohttp.client_exceptions
from kubernetes_asyncio import client, config, watch
from kubernetes_asyncio.client.api_client import ApiClient
import multiprocessing
import functools
import random
import asyncio
from concurrent.futures import Future, Executor, ProcessPoolExecutor, as_completed
from threading import Lock
import enum
import itertools


# Adapted from https://bugs.python.org/issue36054#msg353690
def get_cpu_count():
    cgroup_quota_file = Path("/sys/fs/cgroup/cpu/cpu.cfs_quota_us")
    cgroup_cfs_period_seconds_file = Path("/sys/fs/cgroup/cpu/cpu.cfs_period_us")
    cgroup_cpu_shares_file = Path("/sys/fs/cgroup/cpu/cpu.shares")
    if not cgroup_quota_file.exists():
        return multiprocessing.cpu_count()
    else:
        # Not useful for AWS Batch based jobs as result is -1, but works on local linux systems
        cpu_quota = int(cgroup_quota_file.read_text().rstrip())
    if cpu_quota != -1 and cgroup_cfs_period_seconds_file.exists():
        cpu_period = int(cgroup_cfs_period_seconds_file.read_text().rstrip())
        avail_cpu = int(
            cpu_quota / cpu_period
        )  # Divide quota by period and you should get num of allotted CPU to the container, rounded down if fractional.
    elif cgroup_cpu_shares_file.exists():
        cpu_shares = int(cgroup_cpu_shares_file.read_text().rstrip())
        # For AWS, gives correct value * 1024.
        avail_cpu = int(cpu_shares / 1024)
    return avail_cpu


def chunks(sequence: List, n: int):
    """Yield successive n-sized chunks from sequence."""
    for i in range(0, len(sequence), n):
        yield sequence[i : i + n]


class WatchTypes(enum.Enum):
    # Stub for different watch types, doesn't do anything yet
    all = enum.auto()
    namespace = enum.auto()


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


async def watch_it(
    watcher_count: int,
    shutdown_event: multiprocessing.Event,
    *,
    ramp_time: int,
    watch_type: WatchTypes = WatchTypes.all,
    namespace: str = "default",
) -> None:
    print(
        f"watcher {watcher_count} sleeping a random amount before starting"
    )  # We're a thundering herd, but maybe this takes the edge off?
    if watch_type != WatchTypes.all:
        print(f"watcher {watcher_count} will be watching namespace {namespace}")
    await asyncio.sleep(random.randint(0, ramp_time))
    async with ApiClient() as api:
        v1 = client.CoreV1Api(api)
        watches = {
            WatchTypes.all: v1.list_secret_for_all_namespaces,
            WatchTypes.namespace: v1.list_namespaced_secret,
        }
        watch_object = watches[watch_type]
        args = [watch_object]
        if watch_type != WatchTypes.all:
            args.append(namespace)
        w = watch.Watch()
        secrets = 0
        while not shutdown_event.is_set():
            try:
                async with w.stream(
                    *args, timeout_seconds=86400, _request_timeout=86400
                ) as stream:
                    async for _ in stream:
                        if secrets <= 1000:
                            secrets += 1
                        if shutdown_event.is_set():
                            await stream.close()
                            break
            except aiohttp.client_exceptions.ClientConnectorError:
                pass


async def start(
    *,
    number_of_watches: int,
    shutdown_event: multiprocessing.Event,
    watch_type: WatchTypes,
    core_number: int,
    namespaces: List[str],
    ramp_time: int,
) -> None:
    if shutdown_event.wait(ramp_time * core_number):
        return
    print(f"core {core_number} starting with {number_of_watches} watches")
    if bool(strtobool(os.getenv("USE_IN_CLUSTER_CONFIG", "false"))):
        await config.load_incluster_config()
    else:
        await config.load_kube_config(
            config_file=os.getenv(
                "KUBECONFIG", str(Path("~/.kube/config").expanduser())
            ),
            persist_config=False,
        )
    namespace_cycler = itertools.cycle(namespaces)
    jobs = [
        watch_it(
            n,
            shutdown_event,
            ramp_time=ramp_time,
            watch_type=watch_type,
            namespace=next(namespace_cycler),
        )
        for n in range(number_of_watches)
    ]
    await asyncio.gather(*jobs)
    print("Job's done!")


def run(
    core_number,
    *,
    number_of_watches: int,
    shutdown_event: multiprocessing.Event,
    watch_type: WatchTypes,
    namespaces: List[str],
    ramp_time: int,
) -> None:
    asyncio.run(
        start(
            number_of_watches=number_of_watches,
            shutdown_event=shutdown_event,
            watch_type=watch_type,
            core_number=core_number,
            namespaces=namespaces,
            ramp_time=ramp_time,
        )
    )


def signal_handler(shutdown_event, sig, frame) -> None:
    print("You pressed Ctrl+C!")
    shutdown_event.set()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--debug", default=False, action="store_true")
    parser.add_argument(
        "--watch-type",
        default=WatchTypes.all.name,
        choices=[enumeration.name for enumeration in WatchTypes],
    )
    parser.add_argument("-n", "--namespace", default="default", type=str)
    parser.add_argument(
        "-r",
        "--ramp-time",
        type=int,
        default=30,
        help="time each process has to scale up to full load",
    )
    parser.add_argument("watch_count", type=int, default=50)
    args = parser.parse_args()
    print("I'm watching you...")
    watch_count: int = args.watch_count
    debug: bool = args.debug
    watch_type = WatchTypes[args.watch_type]
    namespaces: List[str] = list(filter(None, args.namespace.split(",")))
    ramp_time: int = max(0, args.ramp_time)
    _executor = ProcessPoolExecutor
    cpu_count = min(get_cpu_count(), watch_count)
    if debug:
        _executor = DummyExecutor
        cpu_count = 1
    watch_chunks = watch_count // cpu_count
    with multiprocessing.Manager() as manager:
        shutdown_event = manager.Event()
        chunked_watcher = functools.partial(
            run,
            number_of_watches=watch_chunks,
            shutdown_event=shutdown_event,
            watch_type=watch_type,
            ramp_time=ramp_time,
        )
        signal.signal(signal.SIGINT, lambda x, y: signal_handler(shutdown_event, x, y))
        signal.signal(signal.SIGTERM, lambda x, y: signal_handler(shutdown_event, x, y))

        futures = []
        with _executor(max_workers=cpu_count) as executor:
            if debug:
                breakpoint()
            for core, namespace_chunk in zip(
                range(cpu_count), itertools.cycle(chunks(namespaces, cpu_count))
            ):
                futures.append(
                    executor.submit(chunked_watcher, core, namespaces=namespace_chunk)
                )

            for future in as_completed(futures):
                future.result()
            executor.shutdown(wait=True)


main()
