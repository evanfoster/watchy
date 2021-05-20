import argparse
from kubernetes import client, config, watch
import multiprocessing
from concurrent.futures import ThreadPoolExecutor, ProcessPoolExecutor
import functools
import random
import time


def watch_it(watcher_count: int):
    print(f"watcher {watcher_count} sleeping a random amount")
    time.sleep(random.randint(0, 240))
    time.sleep(30)
    # Configs can be set in Configuration class directly or using helper
    # utility. If no argument provided, the config will be loaded from
    # default location.
    config.load_kube_config(
        config_file="/kubeconfig.yaml",
        context="ethos11-thrash-va7",
        persist_config=False,
    )

    v1 = client.CoreV1Api()
    w = watch.Watch()
    secrets = 0
    for event in w.stream(v1.list_secret_for_all_namespaces, timeout_seconds=3600):
        if secrets <= 1000:
            secrets += 1
            print(f"watcher {watcher_count} found {secrets} secrets")
        # print(f"Found {secrets} secrets so far")

        # print("Event: %s %s %s" % (
        #     event['type'],
        #     event['object'].kind,
        #     event['object'].metadata.name)
        # )
    print("Finished pod stream.")


def thread_it(number_of_watches, core_number):
    time.sleep(core_number * 300)
    print(f"core {core_number} starting with {number_of_watches} watches")
    with ThreadPoolExecutor(max_workers=number_of_watches + 1) as executor:
        for result in executor.map(watch_it, range(number_of_watches)):
            pass


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("watch_count", type=int, default=50)
    args = parser.parse_args()
    print("I'm watching you...")
    watch_count: int = args.watch_count
    cpu_count = multiprocessing.cpu_count() * 4
    watch_chunks = watch_count // cpu_count
    chunked_watcher = functools.partial(thread_it, watch_chunks)
    with ProcessPoolExecutor(max_workers=cpu_count) as executor:
        for result in executor.map(chunked_watcher, range(cpu_count)):
            pass


main()
