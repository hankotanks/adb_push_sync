import argparse
import os
import sys
import subprocess
import datetime
import tqdm
import pathlib
import re

def run_on_device(cmd):
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

"""
def getmtime_on_device(path):
    exit_code, result = run_on_device(["ls", "-l",  f"{path}"])
    print(result)
    return None
    if exit_code != 0 or len(result) < 2: 
        return None

    cols = result[-1].split()
    if len(cols) == 0:
        return None

    is_file = cols[0][0] == '-'
    if len(cols) < (6 if is_file else 5): 
        return None

    time_str = " ".join(cols[4:6] if is_file else cols[3:5])
    return datetime.datetime.strptime(time_str, "%Y-%m-%d %H:%M").timestamp()
"""

def listing_on_device(path):
    exit_code, output = run_on_device(["ls", "-l", f"\"{path}\"", "|", "grep", "'^-'"])
    print(output)
    if exit_code != 0:
        raise RuntimeError(f"Failed to query directory: {path}")

    return list(map(lambda line: line.split(maxsplit = 6)[6], output))

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
        result = subprocess.run(["adb", "push", path_source, args.destination], 
            stdout = sys.stdout, stderr = sys.stderr)
        if result.returncode != 0:
            raise RuntimeError("Failed to perform initial sync!")
        exit(0)

    entries_to_skip = set()
    entries = []
    for entry_source, children_dirname, children_fname in os.walk(path_source, topdown = True):
        if len(children_dirname) == 0 and len(children_fname) == 0: continue

        entry = entry_source.removeprefix(path_source).lstrip("/")
        if len(entry) == 0: continue
        if any(entry.startswith(skip) for skip in entries_to_skip): continue

        entry_device = os.path.join(path_device, entry)
        if not exists_on_device(entry_device):
            result = subprocess.run(["adb", "push", f"{entry_source}", f"{entry_device}"],
                stdout = sys.stdout, stderr = sys.stderr)
            if result.returncode != 0:
                raise RuntimeError(f"Failed to copy file: {entry}")
            
            entries_to_skip.add(entry)
        else:
            count_source, count_full_source = count_children(entry_source)
            count_device, count_full_device = count_children_on_device(entry_device)
            if count_device == 0:
                result = subprocess.run(["adb", "push", f"{entry_source}", f"{os.path.dirname(entry_device)}"],
                    stdout = sys.stdout, stderr = sys.stderr)
                if result.returncode != 0:
                    raise RuntimeError(f"Failed to copy file: {entry}")
                
                entries_to_skip.add(entry)
            elif count_full_source == count_full_device:
                entries_to_skip.add(entry)
            else:
                children_fname_missing = []
                for f in children_fname:
                    if exists_on_device(os.path.join(entry_device, f)): continue
                    children_fname_missing.append(os.path.join(entry_source, f))
                
                if len(children_fname_missing) > 0:
                    result = subprocess.run(["adb", "push", *children_fname_missing, f"{entry_device}"],
                        stdout = sys.stdout, stderr = sys.stderr)
                    if result.returncode != 0:
                        raise RuntimeError(f"Failed to copy file: {entry}")
