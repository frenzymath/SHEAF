# AGENTS.md

This directory is one project: formalizing a paper in Lean 4, over Mathlib, with many agents working at once. Read this file first, then [`roles/worker.md`](roles/worker.md) and the stage document your task names.

## 1. Who does what

Agents do the mathematics; code does the process. There are two kinds of agent:

- **Workers** do tasks: a node to split, a node to state, a module to prove, or a task the main agent wrote. `tools/dispatch.py` starts them, one per task, and gives a worker that delivered the next task next to its item. Your first prompt names your task; your role document is [`roles/worker.md`](roles/worker.md).
- **The main agent** is the one the human talks to. It works outside this directory: it set the project up, keeps the code running, and decides what the code cannot (`coord/attention.md`), with the human when it must (`coord/HUMAN.md`). It writes no mathematics: what needs an agent becomes a task.

Everything else is code, in `tools/`: which items are open, who works on what, checking a delivery and putting it into the library.

### Three stages at once

The three stages are three kinds of work on a node, and they run at the same time on different parts of the DAG. Which stage a node is in follows from its own state, never from a calendar:

- a node is split (stage 1) while a target reaches it and its proof is not written in steps;
- it is stated (stage 2) as soon as it is split and every node its statement uses is stated;
- its module is proved (stage 3) as soon as every node its proof uses is stated.

The order of the dependencies is never overridden: stage 1 runs from the targets downward, stage 2 from Mathlib upward, stage 3 from the targets downward. `tools/tasks.py` computes what is open from the DAG and the library. When a delivery lands, the nodes it touches and the nodes that use them are computed again at once, so the work it unblocks opens in that moment, in whichever stage, without waiting for any round. A task is a file, `coord/tasks/<task>.json`, that holds everything a worker needs to start.

## 2. The project directory

This directory is the project, and a git repository of its own. Everything you read and write is in it.

```
AGENTS.md  roles/  stages/   the contract: how a worker works, and what each stage produces
tools/                       the code that runs the process (tools/README.md)
skills/                      choices that depend on the machine: how deliveries are compiled
SETUP.md                     the human's settings and requirements; every agent follows them
GOAL.md                      the goal of every agent: the targets and the completion criterion
literature/                  the papers and textbooks the proofs follow; LIST.md lists those obtained and those wanted
dag/nodes/                   the DAG, one JSON file per node
lean/                        the Lean project; sandboxes in lean/.sandbox/<group>/<task>/
coord/                       the tasks (tasks/, queue.md), the deliveries (deliveries/), what the main agent and the
                             human must decide (attention.md, HUMAN.md), STATE.md, ledger.md, targets-review/,
                             changes/, settings (sheaf.env, dispatch.json)
local/                       what this machine builds for itself; not committed
```

## 3. One library, many agents

All agents work on one Lean library and compile against it, so a wrong file in it stops everyone who imports it. How deliveries are compiled depends on the machine; the main agent chooses it with [`skills/compiling/SKILL.md`](skills/compiling/SKILL.md) and records it in `coord/STATE.md`. Three rules hold whatever the choice.

- Compile single files in your sandbox; build the whole library only in a worktree of your own, when `coord/STATE.md` gives you one.
- A file enters the library only through the submit command that `tools/accept.py` runs on a delivery, never by copying.
- What you compile against is the library as the submit command leaves it (`tools/README.md`).

Where `coord/STATE.md` says the statements are frozen, no delivery changes a statement or definition that is in the library: a correction is a new declaration, its node records the new declaration, and the proofs that use the old one move to it.

The scripts in `tools/` carry this out; [`tools/README.md`](tools/README.md) says which does what. They are one implementation, written for one machine and one project, and the main agent changes them when they do not fit this one. If a script refuses correct work, lets wrong work through or does not fit the project, report it (§6); do not work around it and do not edit it yourself.

## 4. The targets

The project is accepted when two things hold (`GOAL.md`):

1. **Lean comparator accepts it.** [Lean comparator](https://github.com/leanprover/comparator) checks the library against `lean/Challenge.lean`: every target is proved with exactly the statement written there, using no axiom beyond `propext`, `Classical.choice` and `Quot.sound`.
2. **`Challenge.lean` says what the paper says.** Every target statement, read together with the definitions it uses, means exactly what the statement in the paper means: no hypothesis added, none dropped, no conclusion weakened, no definition that differs from the paper's. The comparator cannot check this; it is checked by a review (`stages/2-statements.md` §4).

So the target statements change only on the human's instruction. A change to a definition that a target statement uses can change what the target means without changing its text: it reopens the second check for that target. Never weaken a statement to make it provable.

## 5. Standards

- A target is proved when `#print axioms` shows nothing beyond `propext`, `Classical.choice`, `Quot.sound`.
- No hollow definitions. A definition is hollow when its data is written as `sorry`: everything built on it then proves something about an unknown object. A definition may take its data from a theorem that is still `sorry`, as an inverse does from a bijection not yet proved; only the proof is postponed. A proof that a definition itself needs is stated as a named theorem of its own, which the definition refers to, not left inside it as `sorry`.
- Every `sorry` you leave is a named theorem with its source and a complete natural-language proof in its docstring, and a DAG node matching it, so that anyone can take it over from those two alone.
- Test a new statement on its edge cases before writing it. Mark one you believe false with `STATEMENT-DISPUTED: <reason>` and report it; a false lemma makes everything above it look proved.
- The number of `sorry`s is not a measure of progress.

## 6. When the process fails

The process of this project is what lets many agents work on one library. When you notice something going against it, a rule that does not fit, a tool that misbehaves, an agent working around the contract, handle it at once if it is yours to handle; otherwise say so in the report of your delivery. The main agent reads the reports through `coord/attention.md` and the task notes, and brings to the human what needs the human.
