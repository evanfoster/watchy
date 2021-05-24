import signal
import os
import argparse
from pathlib import Path

from kubernetes_asyncio import client, config, watch
from kubernetes_asyncio.client.api_client import ApiClient
import multiprocessing
import functools
import random
import asyncio
from concurrent.futures import Future, Executor, ProcessPoolExecutor, as_completed
from threading import Lock
import enum


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
    watch_type: WatchTypes = WatchTypes.all,
    namespace: str = "default",
) -> None:
    print(
        f"watcher {watcher_count} sleeping a random amount"
    )  # We're a thundering herd, but maybe this takes the edge off?
    await asyncio.sleep(random.randint(0, 4))
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
        async with w.stream(
            *args, timeout_seconds=86400, _request_timeout=86400
        ) as stream:
            async for _ in stream:
                if secrets <= 1000:
                    secrets += 1
                if shutdown_event.is_set():
                    await stream.close()
                    break


async def start(
    *,
    number_of_watches: int,
    shutdown_event: multiprocessing.Event,
    watch_type: WatchTypes,
    core_number: int,
    namespace: str,
) -> None:
    if shutdown_event.wait(10 * core_number):
        return
    print(f"core {core_number} starting with {number_of_watches} watches")
    await config.load_kube_config(
        config_file=os.getenv("KUBECONFIG", str(Path("~/.kube/config").expanduser())),
        persist_config=False,
    )
    jobs = [
        watch_it(n, shutdown_event, watch_type=watch_type, namespace=namespace)
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
    namespace: str,
) -> None:
    asyncio.run(
        start(
            number_of_watches=number_of_watches,
            shutdown_event=shutdown_event,
            watch_type=watch_type,
            core_number=core_number,
            namespace=namespace,
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
    parser.add_argument("watch_count", type=int, default=50)
    args = parser.parse_args()
    print("I'm watching you...")
    watch_count: int = args.watch_count
    debug: bool = args.debug
    watch_type = WatchTypes[args.watch_type]
    namespace: str = args.namespace
    _executor = ProcessPoolExecutor
    cpu_count = min(multiprocessing.cpu_count(), watch_count)
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
            namespace=namespace,
        )
        signal.signal(signal.SIGINT, lambda x, y: signal_handler(shutdown_event, x, y))
        signal.signal(signal.SIGTERM, lambda x, y: signal_handler(shutdown_event, x, y))

        futures = []
        with _executor(max_workers=cpu_count) as executor:
            if debug:
                breakpoint()
            for core in range(cpu_count):
                futures.append(executor.submit(chunked_watcher, core))

            for future in as_completed(futures):
                future.result()
            executor.shutdown(wait=True)


main()
