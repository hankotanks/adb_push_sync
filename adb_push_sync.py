import argparse
import os
import sys
import subprocess
import typing

def run_on_device(cmd):
    if not isinstance(cmd, list): cmd = [cmd]
    result = subprocess.run(["adb", "shell", *cmd, "&&", "echo", "$?"], 
        capture_output = True, text = True)

    output = result.stdout.strip().split("\n")
    if len(output) == 0:
        raise RuntimeError("Unreachable!")

    try:
        exit_code = int(output[-1])
    except ValueError as e:
        exit_code = 1

    return exit_code, output[:-1]

def exists_on_device(path):
    exit_code, _ = run_on_device([f"[ -e \"{path}\" ]"])
    return True if exit_code == 0 else False

def push_to_device(path_source, path_device):
    if not isinstance(path_source, list): path_source = [path_source]
    result = subprocess.run(["adb", "push", *path_source, f"{path_device}"],
        stdout = sys.stdout, stderr = sys.stderr)
    if result.returncode != 0:
        raise RuntimeError(f"Failed to copy file: {entry}")

def count_children(path):
    count = len(os.listdir(path))
    count_full = 0
    for _, _, fnames in os.walk(path): count_full += len(fnames)
    return count, count_full

def count_children_on_device(path):
    exit_code, output = run_on_device(["ls", "-l", f"\"{path}\""])
    if exit_code != 0:
        raise RuntimeError(f"Failed to query directory: {path}")

    count = len(output)

    exit_code, output = run_on_device(["ls", "-lR", f"\"{path}\"", "|", "grep", "'^-'"])
    if exit_code != 0:
        raise RuntimeError(f"Failed to query directory: {path}")

    count_full = len(output)

    return count, count_full

class Entry(typing.NamedTuple):
    stub: str
    path_source: str
    path_device: str
    child_dirnames: list[str]
    child_fnames: list[str]

    def exists_on_device(self):
        exit_code, _ = run_on_device([f"[ -e \"{self.path_device}\" ]"])
        return True if exit_code == 0 else False

    def count_children(self):
        count_source = len(os.listdir(self.path_source))

        exit_code, output = run_on_device(["ls", "-l", f"\"{self.path_device}\""])
        if exit_code != 0:
            raise RuntimeError(f"Failed to query entry on device: {self.stub}")

        count_device = len(output)

        return count_source, count_device

    def count_children_recursive(self):
        count_source = 0
        for _, _, fnames in os.walk(self.path_source): count_source += len(fnames)

        exit_code, output = run_on_device(["ls", "-lR", f"\"{self.path_device}\"", "|", "grep", "'^-'"])
        if exit_code != 0:
            raise RuntimeError(f"Failed to query entry on device: {self.stub}")

        count_device = len(output)

        return count_source, count_device

def walk(path_source, path_device, topdown = True):
    for dirpath, dirnames, filenames in os.walk(path_source, topdown = topdown):
        stub = dirpath.removeprefix(path_source).lstrip("/")
        yield Entry(
            stub = stub, 
            path_source = dirpath,
            path_device = os.path.join(path_device, stub),
            child_dirnames = dirnames,
            child_fnames = filenames)

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("source")
    parser.add_argument("destination")

    args = parser.parse_args()
    if not os.path.exists(args.source):
        raise ValueError("Provided <source> path does not exist: {args.source}")

    result = subprocess.run(["which", "adb"],
        stdout = subprocess.DEVNULL,
        stderr = subprocess.DEVNULL)

    if result.returncode != 0:
        raise RuntimeError("Unable to find adb in PATH!")

    result = subprocess.run(["adb", "devices"],
        capture_output = True,
        text = True)

    if result.returncode != 0 or len(result.stdout.strip().split("\n")) != 2:
        raise RuntimeError("Couldn't find device!")

    if not exists_on_device(args.destination):
        raise ValueError(f"Provided <destination> path does not exist: {args.destination}")

    path_source = args.source.rstrip("/")
    path_device = os.path.join(args.destination, os.path.basename(path_source))

    if not exists_on_device(path_device):
        push_to_device(path_source, args.destination)
        exit(0)

    entries_to_skip = set()
    entries = []
    for entry in walk(path_source, path_device):
        if len(entry.child_dirnames) == 0 and len(entry.child_fnames) == 0: continue

        if len(entry.stub) == 0: continue
        if any(entry.stub.startswith(skip) for skip in entries_to_skip): continue

        if not entry.exists_on_device():
            push_to_device(entry.path_source, entry.path_device)
            entries_to_skip.add(entry.stub)
            continue

        count_source, count_device = entry.count_children()
        count_full_source, count_full_device = entry.count_children_recursive()
        if count_device == 0:
            push_to_device(entry.path_source, os.path.dirname(entry.path_device))
            entries_to_skip.add(entry.stub)
            continue

        if count_full_source == count_full_device:
            entries_to_skip.add(entry.stub)
            continue

        entry_child_fnames_missing = []
        for fname in entry.child_fnames:
            if exists_on_device(os.path.join(entry.path_device, fname)): continue
            entry_child_fnames_missing.append(os.path.join(entry.path_source, fname))
        
        if len(entry_child_fnames_missing) > 0:
            push_to_device(entry_child_fnames_missing, entry.path_device)