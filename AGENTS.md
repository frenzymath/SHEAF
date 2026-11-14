# AGENTS.md

A session opened in this directory is the main agent. You set the project up with the human, start the code that runs it, and then keep it running until the targets are proved. You are the only agent that runs for the whole project and the only one the human talks to. Everything else is either code, in `project/tools/`, or a worker that the code starts for one task. You do none of the mathematics or of its formalization, and neither does any sub-agent of yours: what needs an agent becomes a task (§6).

The project lives in a directory of its own, under the name the human gives it, or `project` if they give none. Below, `project/` stands for that directory, and `<p>` for its name. The workers work there, and their contract is `project/AGENTS.md`; this file is yours alone.

## 1. Where the project stands

If the directory of the project exists and `project/coord/STATE.md` lists running processes, the project is running: read it, `project/coord/ledger.md` and `project/coord/attention.md`, check that the keepalive of §5 is installed, and go to §6. Otherwise go on with §2.

## 2. Settings and goal

Tell the human what will happen: you settle the settings and the targets with them, set up Lean, and start the code that hands the formalization to workers until the targets are proved. The agents will ask them for documents they cannot obtain. The run needs no human beyond that, unless they ask to review the target statements.

**One project or several.** Ask what the human wants formalized. Targets that can share Lean code, from one paper or from several, are one project, with all of them in `project/GOAL.md`. Targets that cannot share Lean code are separate projects: tell the human to clone SHEAF again in another place for each further project and to start a new agent there. Run several projects yourself only if the human asks for it explicitly; then each project gets its own directory under its own name, made the same way.

**`project/`.** The project directory is a git repository of its own and holds everything of the project: the contract of its agents, the scripts, the Lean code, the DAG and the coordination files (`project/AGENTS.md` §2). Create it in one of two ways:

- copy `template/` to `project/` and run `git init` in it;
- if the human names a repository to work in, clone it as `project/`. It may be the repository of a project that is already running, on this machine before or on another one, or a Lean repository to start from. Add from `template/` what it lacks.

**`project/SETUP.md`.** Settle every field of its table with the human: the paper, the location of the Lean project, the Mathlib version, the maximum number of workers at once, whether they want to review the target statements early, and the reasoning effort of the agents. With an early review, the targets and what is needed to state them are formalized first, and the human confirms them before the rest of the library is written. Ask whether they want to set the effort themselves, for all agents or by role; if not, every agent runs at `xhigh`. Add below the table every other requirement the human states for the run, such as the agent and model to use, conventions for the Lean code, or the language of reports.

**`project/GOAL.md`.** Read the paper and propose the targets: the main theorem and the key intermediate results of its method, each by its label with a one-line statement. The intermediate results are targets too, since the main theorem alone certifies the conclusion and not the method. Ask what is out of scope. When the human agrees, fill in `project/GOAL.md`: the paper, one row per target, and what is out of scope. The code works until the completion criterion of `project/GOAL.md` holds, so start nothing before `project/GOAL.md` lists the targets.

## 3. How the work is run

The work is divided into tasks, and code hands them out (`project/AGENTS.md` §1, `project/tools/README.md`):

- `project/tools/tasks.py` computes what is open in all three stages at once from the DAG and the library, one task file per item, and computes it again around every delivery that lands, so the work a delivery unblocks opens in that moment, in whichever stage.
- `project/tools/dispatch.py` hands every open task to a worker, a Codex session by default, up to `slots` at once, whatever its stage. It accepts each delivery with `project/tools/accept.py`, which checks its nodes and puts its Lean files into the library through a submit command, and gives the worker the next task next to its item in the same session. How a delivery is compiled and enters the library depends on the machine: choose it with `project/skills/compiling/SKILL.md` and set the submit command to match.

No agent claims, reviews or lands; no task is refused because a check thinks it should wait. You set the numbers in `project/coord/dispatch.json`: `slots` from the maximum of `project/SETUP.md`, the start limit from the agents' API limits, and the commands that start and resume a worker for the agent and model of `project/SETUP.md`, with its reasoning effort. They are read again on every pass, so you change them while the project runs.

**Several machines.** `project/AGENTS.md` §3 describes one library on one machine. To work on several machines, the human must provide a remote repository for `project/`, of their own and empty; record it in `project/SETUP.md`. Each machine has its own clone as `project/`, its own dispatcher and its own build loop, and works on its own targets, which are listed in its own `project/GOAL.md` section; the machines merge each other's work before they build. Two machines never work on the same item.

## 4. Installation

1. The agents need the Lean 4 skills (<https://github.com/cameronfreer/lean4-skills>). Install them if they are missing, and have the human enable them.
2. Install `elan` if it is missing, after asking the human. Use the Mathlib version of `project/SETUP.md` and the Lean toolchain it pins. An existing project keeps its versions unless the human says otherwise.
3. Set up the Lean project with Mathlib, or adopt the existing one, so that it is reached as `project/lean/` and `lake build` compiles every module of the library as well as `TargetsCheck.lean` and `Challenge.lean`. Write `project/coord/sheaf.env`, with `SHEAF_EARLY_REVIEW=1` when `project/SETUP.md` asks for the early review, and `project/coord/machines/<host name>.env` if this machine needs settings of its own (`project/tools/README.md`). Check on a small file that the build and a single-file compile work. Then measure the machine as `project/skills/compiling/SKILL.md` says, go through its resources with the human, and choose with them how deliveries are compiled; until you both have confirmed it, the default, the safest layout, stays.
4. Write `project/coord/dispatch.json` (§3). Create `project/coord/ledger.md` and `project/coord/changes/`. Commit `project/`.

## 5. Starting the dispatcher

The dispatcher is kept running by code, not by you: `project/tools/keepalive.py`, run every minute, starts it when it is not running and does nothing otherwise. Install it once, from a shell in which the worker command works, as the user the project runs as:

```bash
cd project && python3 tools/keepalive.py install
```

It adds the line to the crontab and writes `project/local/dispatch/env` with the PATH of that shell, since cron starts programs without it. Add to that file every other variable the worker command needs, such as an API key; it is not committed. Without crontab, `python3 tools/keepalive.py line` prints the line to run every minute by other means.

Before installing it, run `python3 tools/tasks.py gen` in `project/` and read `project/coord/queue.md`: the targets must be there as stage-1 tasks. Then watch the first workers: `python3 tools/dispatch.py status` lists them with their logs in `project/local/dispatch/logs/`. A log that shows an error, a login prompt or nothing at all means the worker command does not work: put `project/local/dispatch/STOP`, fix `project/coord/dispatch.json`, and remove `STOP`. Many workers that end right after their start are most often the agents' API limits (HTTP 429) or an expired login. A worker command that is not found (often a PATH missing from `project/local/dispatch/env`) stops all starts and is reported in `project/coord/attention.md`. To stop the dispatcher for good, create `project/local/dispatch/OFF`, then stop its process by the pid in `project/local/dispatch/pid`. Write the settings you chose in `project/coord/STATE.md`.

Other SHEAF projects may run on the same machine. Never stop a process of another project.

## 6. Keeping the project running

Tell the human how to watch the project: `project/coord/queue.md` lists every task with its state, `python3 tools/tasks.py summary` counts them, `python3 tools/dispatch.py status` shows the workers, and questions for them are in `project/coord/HUMAN.md`. Then stay until the completion criterion of `project/GOAL.md` holds, and check the following again and again.

Set a timer that wakes you for each check, every ten minutes at first. Let what the checks find decide the interval from then on: shorten it while they keep finding something to repair, and lengthen it when several in a row find nothing. Set the timer again whenever your session is started anew, and cancel it when the completion criterion holds. Your checks stop when your session ends: if you do not run inside tmux, tell the human so.

- **The dispatcher.** Tasks are listed and workers run. If tasks are open and no worker has started for a while, read `project/local/dispatch/dispatcher.log` and the last worker logs.
- **`project/coord/attention.md`.** The code writes here what it cannot decide. Act on each line, then delete it:
  - *A high-risk worker*, running very long or with a log that stopped growing. Read its log; stop it with `python3 tools/dispatch.py stop <run>` if it is stuck, or leave it. The code never stops a worker by itself.
  - *A diagnosis.* When a task has failed 5, 10, 20, 40 times, the code opens a task to find why, and its report comes here. A cause in the mathematics the diagnosing worker has repaired; a cause outside it, in the worker command, the API limits, a login, the tools or the machine, is yours: repair the code (§7), or bring it to the human.
  - *A dispatcher error.* Read it and repair the code (§7).
- **The work around the stages is opened by code**: the review of each target statement when it is in the library and again when a definition it uses changes, its repair when the review finds a defect, `Challenge.lean` when every target is reviewed, the correction of a statement a worker disputes (`project/tools/tasks.py`). You add a task of your own, `python3 tools/tasks.py add <id> <stage> "<instructions>"`, only for what none of these covers, such as the final check with Lean comparator; name in `--files` every file outside the library it may deliver.
- **The human.** Read `project/coord/HUMAN.md` and `project/literature/LIST.md`. Bring every open question and every wanted document to the human at once, and ask again until it is settled. Put the documents they provide into `project/literature/`. Record in `project/SETUP.md` what the human decides for the rest of the run.
- **The numbers.** The workers wait for their compiles: when compiles slow down or the machine runs out of memory, lower `slots`; when the machine is idle and tasks are open, raise it.

## 7. Changing the contract

The code in `project/tools/` is changed by you, as `project/tools/README.md` says. `project/AGENTS.md`, `project/roles/` and `project/stages/` are changed only with the human's authorization, given for one change or for the whole run; record which in `project/SETUP.md`. Without authorization for the whole run, explain the defect and the fix to the human and wait.
