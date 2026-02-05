import argparse
import os
import sys
import subprocess
import datetime
import tqdm
import pathlib
import re

class DeviceShell:
    def __init__(self):
        adb_check = subprocess.run(["which", "adb"],
            stdout = subprocess.DEVNULL,
            stderr = subprocess.DEVNULL)

        if adb_check.returncode != 0:
            raise RuntimeError("Unable to find adb in PATH!")
        
        self.proc = subprocess.Popen(["adb", "shell"],
            stdin = subprocess.PIPE,
            stdout = subprocess.PIPE,
            stderr = subprocess.STDOUT,
            text = True,
            bufsize = 1)

        self.proc.stdin.write("export PS1='__PROMPT__'" + "\n")
        self.proc.stdin.flush()

    def run(self, cmd):
        SENTINEL_BEGIN = "__ADB_PUSH_SYNC_BEGIN__"
        SENTINEL_END = "__ADB_PUSH_SYNC_END__"

        for cmd_i in [f"echo {SENTINEL_BEGIN}", cmd, "echo $?", f"echo {SENTINEL_END}"]: 
            self.proc.stdin.write(cmd_i + "\n")
        self.proc.stdin.flush()

        output = []

        started = False
        for idx, line in enumerate(self.proc.stdout):
            line = line.rstrip("\n")
            if line == SENTINEL_BEGIN: 
                started = True
                continue
            if not started: continue
            if line == SENTINEL_END: break
            if len(line) == 0 or line.startswith("__PROMPT__") or "\x08" in line: continue
            output.append(line)
        
        try:
            exit_code = int(output[-1])
        except:
            raise RuntimeError("Unreachable!")

        return exit_code, output[0:-1]

    def exists(self, path):
        exit_code, _ = self.run(f"[ -e \"{path}\" ]")
        return True if exit_code == 0 else False

    def getmtime(self, path):
        exit_code, result = shell.run(f"ls -l \"{path}\"")
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

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("source")
    parser.add_argument("destination")

    args = parser.parse_args()
    if not os.path.exists(args.source):
        raise ValueError("Provided <source> path does not exist: {args.source}")

    try:
        shell = DeviceShell()
    except Exception as e:
        print(f"{e}")
        exit(1)

    if not shell.exists(args.destination):
        raise ValueError(f"Provided <destination> path does not exist: {args.destination}")

    args.source = args.source.rstrip("/")
    args.destination = os.path.join(args.destination, os.path.basename(args.source))

    dirs = [(dirname.removeprefix(args.source).lstrip("/"), fnames) 
        for dirname, _, fnames in os.walk(args.source) if fnames]

    dirs_to_push = []
    for entry, fnames in tqdm.tqdm(dirs, desc = "Indexing"):
        path_src = os.path.join(args.source, entry)
        path_dst = os.path.join(args.destination, entry)

        if shell.exists(path_dst):
            path_dst_mod = shell.getmtime(path_dst)
            exit_code, fnames_dst = shell.run(f"ls -l \"{path_dst}\"")
            if exit_code != 0:
                raise RuntimeError("Unreachable!")
            if len(fnames) == len(fnames_dst) and path_dst_mod is not None and path_dst_mod >= os.path.getmtime(path_src): continue
            dirs_to_push.append((entry, True))
        else:
            dirs_to_push.append((entry, False))

    dirs_to_push_filtered = []
    class BreakOuter(Exception): pass
    for entry_a, exists_a in dirs_to_push:
        try:
            for entry_b, exists_b in dirs_to_push:
                if entry_a == entry_b: continue
                if pathlib.Path(entry_a).resolve().is_relative_to(pathlib.Path(entry_b).resolve()):
                    raise BreakOuter;
            dirs_to_push_filtered.append((entry_a, exists_a))
        except BreakOuter:
            pass
    
    for entry, exists in tqdm.tqdm(dirs_to_push_filtered, desc = "Patching"):
        path_src = os.path.join(args.source, entry)
        path_dst = os.path.join(args.destination, entry)
        if exists: 
            path_dst = os.path.dirname(path_dst)

        cmd = subprocess.run(["adb", "push", f"{path_src}", f"{path_dst}"],
            stdout = subprocess.DEVNULL, stderr = subprocess.DEVNULL)
        if cmd.returncode != 0:
            raise RuntimeError(f"Failed to copy file: {entry}")
