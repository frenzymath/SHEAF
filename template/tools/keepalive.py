#!/usr/bin/env python3
"""Keeps the dispatcher running: starts it when it is not running, and does nothing otherwise.

Usage:
  tools/keepalive.py           check once, and start the dispatcher if it is not running; run every minute
  tools/keepalive.py install   write local/dispatch/env and add the every-minute line to the crontab of this user
  tools/keepalive.py line      print that crontab line, for a system without crontab (systemd timer, launchd)

cron starts programs with a bare environment: no PATH beyond the system directories, none of the variables of an
interactive shell. The dispatcher and its workers get the variables in local/dispatch/env (KEY=VALUE per line, not
committed): `install` writes the PATH of the shell it runs in; add what the worker command needs beyond it, such as
an API key. local/dispatch/OFF: never start the dispatcher (to stop it for good, create OFF, then stop the process
whose pid is in local/dispatch/pid).
A dispatcher holds local/dispatch/dispatcher.lock while it runs; this lock, not a pid, tells whether one runs.
"""
import fcntl, os, pathlib, shlex, shutil, subprocess, sys, time

T = pathlib.Path(__file__).resolve().parent
ROOT = T.parent
D = ROOT / "local" / "dispatch"
LOCK = D / "dispatcher.lock"
ENV = D / "env"


def dispatcher_runs() -> bool:
    D.mkdir(parents=True, exist_ok=True)
    with open(LOCK, "a") as f:
        try:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return True
        fcntl.flock(f, fcntl.LOCK_UN)
        return False


def env() -> dict:
    e = dict(os.environ)
    if ENV.exists():
        for line in ENV.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                e[k.strip()] = v.strip()
    e["PYTHONUTF8"] = "1"
    return e


def line() -> str:
    return (f"* * * * * cd {shlex.quote(str(ROOT))} && {shlex.quote(sys.executable)} tools/keepalive.py "
            f">/dev/null 2>&1")


def main() -> int:
    cmd = sys.argv[1] if len(sys.argv) > 1 else "check"
    if cmd == "line":
        print(line()); return 0
    if cmd == "install":
        D.mkdir(parents=True, exist_ok=True)
        old = ENV.read_text(encoding="utf-8").splitlines() if ENV.exists() else []
        keep = [l for l in old if not l.startswith("PATH=")]
        ENV.write_text("\n".join([f"PATH={os.environ.get('PATH', '')}"] + keep) + "\n", encoding="utf-8")
        if not shutil.which("crontab"):
            print("no crontab on this system; run this line every minute by other means:\n" + line()); return 1
        cur = subprocess.run(["crontab", "-l"], capture_output=True, text=True).stdout
        if line() not in cur:
            new = cur.rstrip("\n") + ("\n" if cur.strip() else "") + line() + "\n"
            subprocess.run(["crontab", "-"], input=new, text=True, check=True)
        print(f"installed: {line()}\nlocal/dispatch/env holds PATH; add the variables the worker command needs.")
        return 0
    if cmd != "check":
        print(__doc__); return 2
    if (D / "OFF").exists() or dispatcher_runs():
        return 0
    with open(D / "dispatcher.log", "a", encoding="utf-8") as log:
        log.write(time.strftime("%FT%TZ", time.gmtime()) + " keepalive: starting the dispatcher\n"); log.flush()
        subprocess.Popen([sys.executable, str(T / "dispatch.py"), "run"], cwd=ROOT, env=env(), stdout=log,
                         stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, start_new_session=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
