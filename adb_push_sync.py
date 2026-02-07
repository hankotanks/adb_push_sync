import os
import sys
import argparse
import typing
import collections
import subprocess

class Device:
    def validate():
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

    def run(cmd: str | list[str]) -> (int, list[str]):
        if not isinstance(cmd, list): cmd = [cmd]
        cmd = ["adb", "shell", *cmd, "&&", "echo", "$?"]
        result = subprocess.run(cmd, capture_output = True, text = True)

        output = result.stdout.strip().split("\n")
        if len(output) == 0:
            cmd = " ".join(cmd)
            raise RuntimeError(f"Failed to run command: {cmd}")

        try:
            exit_code = int(output[-1])
        except ValueError as e:
            exit_code = 1

        return exit_code, output[:-1]
    
    def exists(path: str) -> bool:
        exit_code, _ = Device.run([f"[ -e \"{path}\" ]"])
        return True if exit_code == 0 else False

    def push(path_source: str, path_device: str):
        if not isinstance(path_source, list): path_source = [path_source]
        result = subprocess.run(["adb", "push", *path_source, f"{path_device}"],
            stdout = sys.stdout, stderr = sys.stderr)
        if result.returncode != 0:
            raise RuntimeError(f"Failed to copy file: {entry}")

class Entry(typing.NamedTuple):
    stub: str
    path_source: str
    path_device: str
    child_dirnames: list[str]
    child_fnames: list[str]

    def count_children_on_device(self, recurse: bool = False, regex: str | None = None) -> int:
        exit_code, output = Device.run([
            "ls", "-l", 
            *(["-R"] if recurse else []), 
            f"\"{self.path_device}\"",
            *(["|", "grep", f"'{regex}'"] if regex is not None else [])])

        if exit_code != 0:
            raise RuntimeError(f"Failed to query entry on device: {self.stub}")

        return len(output)

    # returns True when the entry should be added to the skip list
    def sync(self) -> bool:
        if not Device.exists(self.path_device):
            Device.push(self.path_source, self.path_device)
            return True

        if self.count_children_on_device() == 0:
            Device.push(self.path_source, os.path.dirname(self.path_device))
            return True

        fnames_to_push = []
        for fname in self.child_fnames:
            if Device.exists(os.path.join(self.path_device, fname)): continue
            fnames_to_push.append(os.path.join(self.path_source, fname))
        
        if len(fnames_to_push) > 0:
            Device.push(fnames_to_push, entry.path_device)

        count_source = len(os.listdir(self.path_source))
        count_device = self.count_children_on_device(recurse = True, regex = "^-")

        return count_source == count_device        

def walk_root(path_source: str, path_device: str, topdown: bool = True) -> collections.abc.Iterator[Entry]:
    for dirpath, dirnames, filenames in os.walk(path_source, topdown = topdown):
        if len(dirnames) == 0 and len(filenames) == 0: continue

        stub = dirpath.removeprefix(path_source).lstrip("/")
        if len(stub) == 0: continue

        yield Entry(
            stub = stub, 
            path_source = dirpath,
            path_device = os.path.join(path_device, stub),
            child_dirnames = dirnames,
            child_fnames = filenames)

if __name__ == "__main__":
    try:
        Device.validate()
    except Exception as e:
        print(f"{e}")
        exit(1)

    parser = argparse.ArgumentParser()
    parser.add_argument("source")
    parser.add_argument("destination")

    args = parser.parse_args()
    if not os.path.exists(args.source):
        print(f"Provided <source> path does not exist: {args.source}")

    try:
        if not Device.exists(args.destination):
            print(f"Provided <destination> path does not exist: {args.destination}")
            exit(1)
    except Exception as e:
        print(f"{e}")
        exit(1)

    path_source = args.source.rstrip("/")
    path_device = os.path.join(args.destination, os.path.basename(path_source))

    try:
        if not Device.exists(path_device):
            Device.push(path_source, args.destination)
            exit(0)
    except Exception as e:
        print(f"{e}")
        exit(1)

    entries_to_skip = set()
    failed = 0
    for entry in walk_root(path_source, path_device):
        if any(entry.stub.startswith(skip) for skip in entries_to_skip): continue
        
        try:
            if entry.sync():
                entries_to_skip.add(entry.stub)
        except Exception as e:
            print(f"{e}")
            print(f"{entry.stub}")
            failed += 1

    if failed == 0:
        print("Success!")
    else:
        print(f"Failed to sync {failed} entries!")
        exit(1)
        