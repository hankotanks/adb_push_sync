import argparse
import os
import sys
import subprocess
import datetime

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

        self.run("export PS1='__PROMPT__'")

    def run(self, cmd):
        SENTINEL = "__ADB_PUSH_SYNC_DONE__"
        SENTINEL_CMD = f"echo {SENTINEL}"

        cmds = [
            cmd,
            "echo $?",
            SENTINEL_CMD
        ]

        for cmd_i in cmds: self.proc.stdin.write(cmd_i + "\n")
        self.proc.stdin.flush()

        out = []

        for idx, line in enumerate(self.proc.stdout):
            line = line.rstrip("\n")
            if line == SENTINEL:
                break
            if len(line) == 0 or line.startswith("__PROMPT__") or line == SENTINEL_CMD: continue
            out.append(line)

        try:
            exit_code = int(out[-1])
        except:
            raise RuntimeError("Unreachable!")

        return exit_code, out[:-1]

    def exists(self, path):
        exit_code, _ = self.run(f"[ -e \"{path}\" ]")
        return True if exit_code == 0 else False

    def get_mod_stamp(self, path):
        exit_code, result = shell.run(f"ls -l \"{path_dst}\"")
        if exit_code != 0 or len(result) < 2: 
            return None

        cols = result[-1].split()
        if len(cols) < 7: 
            return None

        return datetime.datetime.strptime(" ".join(cols[4:6]), "%Y-%m-%d %H:%M").timestamp()

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

    files = [os.path.join(dirname, fname).removeprefix(args.source).lstrip("/") 
        for dirname, _, fnames in os.walk(args.source) for fname in fnames]

    files_to_push = []

    for file in files:
        path_src = os.path.join(args.source, file)
        path_dst = os.path.join(args.destination, file)

        push_file = False
        if shell.exists(path_dst):
            mod_src = os.path.getmtime(path_src)
            mod_dst = shell.get_mod_stamp(path_dst)
            if mod_dst is None:
                raise RuntimeError(f"Failed to parse file: {path_dst}")

            push_file = mod_dst < mod_src
        else:
            push_file = True

        if push_file:
            files_to_push.append((path_src, path_dst))

    for path_src, path_dst in files_to_push:
        cmd = subprocess.run(["adb", "push", path_src, path_dst],
            stdout = sys.stdout, stderr = sys.stderr)
        if cmd.returncode != 0:
            raise RuntimeError(f"Failed to copy file: {path_src}")
