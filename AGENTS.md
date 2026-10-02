# AGENTS.md

A session opened in this directory is the launcher. You set the project up with the human, start the other agents, and then keep the project running. You do none of the mathematics or of its formalization, and neither does any sub-agent of yours (§3).

The project lives in a directory of its own, under the name the human gives it, or `project` if they give none. Below, `project/` stands for that directory, and `<p>` for its name. The agents you start work there, and their contract is `project/AGENTS.md`; this file is yours alone.

## 1. Where the project stands

If the directory of the project exists and `project/coord/STATE.md` names a stage, the project is running: read it and `project/coord/ledger.md`, restart the sessions that are missing (§5), and go to §6. Never start a second maintainer. Otherwise go on with §2.

## 2. Settings and goal

Tell the human what will happen: you settle the settings and the targets with them, set up Lean, and start agents that formalize the paper until the targets are proved. The agents will ask them for documents they cannot obtain. The run needs no human beyond that, unless they ask to review the target statements.

**One project or several.** Ask what the human wants formalized. Targets that can share Lean code, from one paper or from several, are one project, with all of them in `project/GOAL.md`. Targets that cannot share Lean code are separate projects: tell the human to clone SHEAF again in another place for each further project and to start a new agent there. Run several projects yourself only if the human asks for it explicitly; then each project gets its own directory under its own name, made the same way.

**`project/`.** The project directory is a git repository of its own and holds everything of the project: the contract of its agents, the scripts, the Lean code, the DAG and the coordination files (`project/AGENTS.md` §2). Create it in one of two ways:

- copy `template/` to `project/` and run `git init` in it;
- if the human names a repository to work in, clone it as `project/`. It may be the repository of a project that is already running, on this machine before or on another one, or a Lean repository to start from. Add from `template/` what it lacks.

**`project/SETUP.md`.** Settle every field of its table with the human: the paper, the location of the Lean project, the Mathlib version, the maximum number of concurrent subagents, whether they want to review the target statements early, and the reasoning effort of the agents. With an early review, the targets and what is needed to state them are formalized first, and the human confirms them before the rest of the library is written. Ask whether they want to set the effort themselves, for all agents or by role; if not, every agent runs at `xhigh`. Add below the table every other requirement the human states for the run, such as the agent and model to use, conventions for the Lean code, or the language of reports.

**`project/GOAL.md`.** Read the paper and propose the targets: the main theorem and the key intermediate results of its method, each by its label with a one-line statement. The intermediate results are targets too, since the main theorem alone certifies the conclusion and not the method. Ask what is out of scope. When the human agrees, fill in `project/GOAL.md`: the paper, one row per target, and what is out of scope. Every session works until the completion criterion of `project/GOAL.md` holds, so start no session before `project/GOAL.md` lists the targets.

## 3. The plan

**Agents.** The work has six parts: building and pushing (`project/roles/maintainer.md`); keeping the project running (§6); claiming items, reviewing deliveries and landing them (`project/roles/lead.md`); doing an item (`project/roles/worker.md`). The default is one maintainer and several leads. You start these sessions; the workers are sub-agents that each lead starts itself. Give each lead a number of workers that its agent can run at once and that it can still review, and start as many leads as it takes for all their workers together to reach the maximum number of concurrent subagents in `project/SETUP.md`. You may arrange the parts differently to fit `project/SETUP.md` and the agents available, as long as every part is done by some agent and building by exactly one. The mathematics and its formalization are the one part you may not take on: no DAG node and no Lean definition, statement or proof is written or reviewed by you or by a sub-agent that you start yourself. It is done by the sessions you start and by their sub-agents.

**Several machines.** `project/AGENTS.md` §3 describes one library on one machine. To work on several machines, the human must provide a remote repository for `project/`, of their own and empty; record it in `project/SETUP.md`. Each machine has its own clone of SHEAF, its own clone of that repository as `project/`, its own launcher and its own maintainer: every maintainer merges the remote before it builds and pushes what it has built green. `project/SETUP.md` and the plan in `project/coord/STATE.md` get one entry per machine where the machines differ, and each machine has its own file in `project/coord/machines/`. Two machines must not work on the same item. Choose one way:

- *Split the queue.* One maintainer, named in the plan, divides the queue among the machines at the start and pushes the lists. It divides the new items again whenever the queue has changed. Every machine claims from its own list only. Each level of the queue, counted from the targets, is divided in proportion to the workers of the machines, so that every machine works from the targets downwards.
- *Share the queue.* All machines claim from one queue. A claim reaches the other machines when they merge, so the maintainers merge and push the claims every few minutes, apart from their builds.

Write the plan into `project/coord/STATE.md`: the names of the sessions to start (§5).

## 4. Installation

1. The agents need the Lean 4 skills (<https://github.com/cameronfreer/lean4-skills>). Install them if they are missing, and have the human enable them.
2. Install `elan` if it is missing, after asking the human. Use the Mathlib version of `project/SETUP.md` and the Lean toolchain it pins. An existing project keeps its versions unless the human says otherwise.
3. Set up the Lean project with Mathlib, or adopt the existing one, so that it is reached as `project/lean/` and `lake build` compiles every module of the library as well as `TargetsCheck.lean` and `Challenge.lean`. Write `project/coord/sheaf.env`, and `project/coord/machines/<host name>.env` if this machine needs settings of its own (`project/tools/README.md`). Check on a small file that the build and a single-file compile work.
4. Set the stage in `project/coord/STATE.md` to `1-dag`. Create `project/coord/deliveries.log`, `project/coord/ledger.md`, `project/coord/claims/` and `project/coord/changes/`. Commit `project/`.

## 5. Starting the sessions

Other SHEAF projects may run on the same machine, so first find out which tmux sessions are this project's. A session belongs to this project when it was started in `project/` (`tmux display -p -t <session> '#{session_path}'`). Never restart, answer or stop a session of another project. If you cannot tell whose a session is, ask the human whether other projects are running.

Start each session of the plan that is not running, in its own tmux session whose directory is `project/`, with the reasoning effort of `project/SETUP.md`. Put the name of the project, `<p>`, into the session names, so that they do not collide with those of another project. The first prompt tells the agent who it is and which role document to follow. For the default plan:

| Session | First prompt |
|---|---|
| `sheaf-<p>-maint` | "You are the SHEAF maintainer. Read AGENTS.md and roles/maintainer.md and follow them until the completion criterion of GOAL.md holds." |
| `sheaf-<p>-lead-<k>` | "You are SHEAF lead of group G<k>, with at most <w> workers. Read AGENTS.md and roles/lead.md and follow them until the completion criterion of GOAL.md holds." |

Every session is started by the same command, with its own session name `<session>` and its own first prompt `<first prompt>` from the table.

Claude Code:

```bash
tmux new-session -d -s <session> -c "$PWD/project" \
  "claude --dangerously-skip-permissions '/goal The completion criterion of GOAL.md holds. <first prompt>'"
```

Codex:

```bash
tmux new-session -d -s <session> -c "$PWD/project" "codex --dangerously-bypass-approvals-and-sandbox"
# wait until Codex shows its prompt, then:
tmux send-keys -t <session> "/goal The completion criterion of GOAL.md holds. <first prompt>" Enter
```

`/goal` alone shows the goal and its state. A goal that is paused, stalled or stopped by a usage limit goes on with `/goal resume`.

A session that was started is not yet a session that works. After starting each one, watch its screen (`tmux capture-pane -t <session> -p | tail -30`) until the agent is thinking or has answered. A screen that shows an error, a login or trust prompt, or nothing at all means the session did not start: fix the cause and start it again. Then list the names of the sessions in `project/coord/STATE.md`.

## 6. Keeping the project running

Tell the human which sessions run, how to watch one (`tmux attach -t <session>`, leave with `Ctrl-b d`) and stop one (`tmux kill-session -t <session>`), that progress is in `project/coord/STATE.md`, `project/coord/queue.md` and `project/coord/ledger.md`, and that questions for them are in `project/coord/HUMAN.md`. Then stay until the completion criterion of `project/GOAL.md` holds, and check the following again and again.

Set a timer that wakes you for each check, every ten minutes at first. Let what the checks find decide the interval from then on: shorten it while they keep finding something to repair, and lengthen it when several in a row find nothing. Set the timer again whenever your session is started anew, and cancel it when the completion criterion holds.

Your checks stop when your session ends. If you do not run inside tmux, tell the human so, and ask them to start you again inside tmux before they leave you alone.

- **Sessions.** Run the session check in `project/` (`project/tools/README.md`), and read the screen of every session it does not report as working. Answer a session that waits at a question, as the contract says. Restart a session that has stopped, as §5 says; its claims stay valid. On a usage limit, record it and wait.
- **The human.** Read `project/coord/HUMAN.md` and `project/literature/LIST.md`. Bring every open question and every wanted document to the human at once, and ask again until it is settled. Put the documents they provide into `project/literature/`. Write each answer under "Answered" in `project/coord/HUMAN.md` and tell the agent that asked, which deletes the entry once it has acted on it. Delete the entry yourself when that agent no longer runs. Record in `project/SETUP.md` what the human decides for the rest of the run.
- **Practice.** When an agent follows a rule in a way that defeats its purpose, or works around it, tell it what to do instead.
- **The end.** When fewer items can be claimed than there are groups, stop the idle groups.

## 7. Changing the contract

The scripts in `project/tools/` are changed by the maintainer (`project/tools/README.md`). `project/AGENTS.md`, `project/roles/` and `project/stages/` are changed only with the human's authorization, given for one change or for the whole run; record which in `project/SETUP.md`. Without authorization for the whole run, explain the defect and the fix to the human and wait.
