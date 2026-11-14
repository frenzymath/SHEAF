# Tools

The code that runs the process: which items are open, who works on what, checking and landing a delivery, building the library, checking the targets. How to do the mathematics is up to the agents; nothing here decides it.

What must hold, and why, is written in `AGENTS.md` and in the stage documents. The scripts are one way to carry it out. The usage of each script is in the comment at its top.

## Changing the tools

The scripts were written quickly, for one machine and one project, and are meant to be changed freely to fit the project at hand: another DAG layout, another layout of the Lean project, a limit that is too tight, a check that refuses correct work or misses wrong work.

The main agent decides on a change and makes it, since the code runs for every agent and a change reaches all of them at once. Workers report what does not fit in their delivery reports. The main agent:

- keeps what the contract asks for: a changed script still does what the stage documents say the step does;
- tries the change on a copy, then replaces the script in one step, never editing it in place while others may be running it;
- updates this file in the same change, and writes one line in `coord/ledger.md`: what changed and why.

## Configuration

Three files, all committed with the project, so every machine sees the settings of the others. The main agent writes them.

`coord/sheaf.env`, for the project:

```bash
SHEAF_LIB=MyLib               # the library's top-level source directories under lean/, space separated
SHEAF_EARLY_REVIEW=0          # 1 when SETUP.md asks for an early review of the target statements: stage 2 then states the targets first
```

`coord/machines/<host name>.env`, for one machine; optional, and its values override the project's:

```bash
SHEAF_FILE_TIMEOUT=60         # seconds a single-file compile may take
SHEAF_BUILD_THREADS=3         # threads of the global build
SHEAF_BUILD_WAIT=600          # seconds the global build waits for a landing when none has arrived
```

`coord/dispatch.json`, for `dispatch.py`, read again on every pass: the number of workers at once (`slots`), the starts per minute, the command that starts a worker and the one that resumes its session. The comment at the top of `dispatch.py` lists every setting.

The scripts that compile and land take the name of the group from `SHEAF_GROUP`: `dispatch.py` sets it for each worker, `w001`, `w002`, …. The sandbox of a task is `lean/.sandbox/<group>/<task>/`.

## Running the project

One process runs for the whole project; `keepalive.py`, run every minute from cron (`keepalive.py install`), starts it whenever it is not running, with the variables of `local/dispatch/env` (`local/dispatch/OFF` keeps it stopped):

| Process | What it does |
|---|---|
| `dispatch.py run` | Hands every open task to a worker, whatever its stage, up to `slots` at once; accepts what the workers deliver; gives a worker that delivered the next task next to its item, in the same session; runs `tasks.py gen` now and then. `dispatch.py status` shows what runs, with the high-risk workers marked; `dispatch.py stop <run>` stops one, which the code never does by itself. `local/dispatch/STOP` stops new starts. |

And these, which the processes call or a human or the main agent runs to look:

| Tool | What it is for |
|---|---|
| `tasks.py gen / refresh / list / show / summary / add` | The tasks, `coord/tasks/<task>.json`, and the readable view `coord/queue.md`. `gen` computes what is open in all three stages; `refresh <node>…` does it for these nodes and the nodes that use them, after an event; Besides the items of the stages it opens the work around them: target reviews and their fixes, `Challenge.lean`, corrections of disputed statements, diagnoses of tasks that failed 5, 10, 20, 40 times. `add` writes a task of the main agent's own. The state of each task is the last line of `coord/tasks/events.tsv` that names it. |
| `accept.py <task> <group>` | Checks a delivery and, if it passes, puts it in: the nodes into the DAG, the Lean files through the submit command. It answers only by its exit code, accepted or not; `dispatch.py` then has `tasks.py settle` handle the task from that code: done, or back to the list with the reason, and what the result opens or closes. |
| `submit_frozen.py [--pr] <group> <dir> <file>…` | The default submit command, and the one of the layouts with frozen statements: compiles the files in import order against the library's compiled files and puts sources and compiled files in. A statement change is refused, or with `--pr` (the layout with isolation repositories) sent to the managing agent as a pull request. Without `--pr` it is the safest layout, and stays the default until the main agent and the human have confirmed the machine's resources and chosen a layout in `skills/compiling/SKILL.md`; `submit_cmd` in `coord/dispatch.json` then names the chosen command. |
| `submit_pr.sh <group> <dir> <file>…` | The submit command of the layout with one worktree per worker: the files become a pull request to the main repository, and it waits until the managing agent merges it or sends it back. Each waiting submission holds an acceptance, so `accept_slots` must be about `slots`. |
| `submit.sh <group> <dir> <file>…` | The submit command of SHEAF's first application: one library, a delivery landed by `land.sh` or `land_set.sh` below and verified afterwards by the global build. A change to proofs alone enters without a compile, which `skills/compiling/SKILL.md` does not allow: change that before using it. |
| `prs.py open / wait / list / apply / close` | The pull requests to the managing agent: `list` shows each with what it changes for other modules, `apply` writes chosen ones into the managing agent's copy, `close` merges or sends back. Building and merging the batch is the managing agent's work. |
| `worker_prompt.md` | The prompt a worker starts with, and the one for its next task in the same session. |
| `coord/attention.md` | Not a tool: where the code writes what it cannot decide. A high-risk worker, the report of a diagnosis, a dispatcher error. |

## Compiling and landing

`lean_file.sh` is used in every layout; the other tools of this section and the global build below are those of `submit.sh`.

| Tool | What it is for |
|---|---|
| `lean_file.sh <file>` | Compile one file, with 2 threads and a limit of 60 s. A library file compiled here is visible to the group's later compiles before the next global build, so a group can land a new lemma module and then the module that imports it. |
| `land.sh <sandbox file> <library file>` | Put a finished file into the library. Compiles it in place when it changes what other modules see; a change to proofs alone enters on the worker's compile. Refuses it (putting the old version back) if it removes an import or a declaration some other module still needs, adds a name another module already declares, adds a theorem whose statement the library already states word for word, or closes an import cycle. |
| `land_set.sh <set directory>` | Put a set of files into the library at once: a changed statement or definition together with the modules adapted to it. Compiles in place the files that change what other modules see and the files of the set that import them, and runs the same checks on each file; the modules downstream of the set are compiled by the global build, which starts over as soon as the set has landed. |
| `landing.py status / mine <group> / revert <id> <reason>` | The landings that are being checked or wait for the global build, and the last build's result; a group's open and reverted landings; `revert` is for repairing a failed build. |
| `build.py [--retry]` | The global build (§ The global build). When nothing has landed it waits for the next landing, and builds as soon as it arrives. After a failed build, `--retry` builds the same snapshot again with the main agent's own repairs and without the landings it reverted, and nothing else. |

A single-file compile of a module cannot show its effect on other modules, because they still load its old `.olean`. That is why landing runs `import_prune_check.py`, and why every landing is verified afterwards by the global build. The check reads source text: it does not see a removed import that only provided an instance, which the build shows.

## Planning a change

| Tool | What it is for |
|---|---|
| `downstream.py <module> [--uses <name>]` | Which modules depend on a module, and which of them mention a declaration. Run it before changing a statement or definition. |
| `import_prune_check.py <module> <old> <new>` | The check `land.sh` and `land_set.sh` run; it can be run by hand on a planned change. |

## The DAG

| Tool | What it is for |
|---|---|
| `dag_queue.py summary / items / waiting` | The DAG reader `tasks.py` builds on: what each node is, what it uses, how far it is from a target and from Mathlib. The DAG layout is the project's own, so the field names it reads are in its `FIELDS` table at the top; the main agent adapts them to the project's nodes, and `SHEAF_DAG` in `coord/sheaf.env` names the node directory when it is not `dag/nodes`. |

## Checking

| Tool | What it is for |
|---|---|
| `target_types.sh check` | Whether each target statement in the library is exactly the one in `lean/Challenge.lean`, by comparing elaborated types; also prints each target's axioms. For the end of stage 2 and before the final check; it is not part of a build. |
| `hollow_defs.sh` | The definitions the targets reach that depend on `sorry` in any way. They are candidates: each is read to decide whether it is hollow or only refers to an unproved theorem for a proof it needs. For the main agent, to have the definitions checked. |

## The global build

The global build never compiles the tree the groups work in. `build.py` builds a copy, `local/buildtree/`, and brings the compiled files back, so nothing is frozen while it runs, a failed build leaves the groups' compiled files untouched, and a build can be stopped at any moment without harm. The copy shares `lean/.lake/packages` through a link and holds its own build output.

The groups and the build talk through records in `local/builds/`, the way claims are files in `coord/tasks/claims/`:

| Record | Written by | Meaning |
|---|---|---|
| `inflight/<id>.json` | `land.sh`, `land_set.sh`, when they write the files | The group is still checking the landing. A build started now takes the previous version of its files, from `backup/<id>/`. |
| `requests/<id>.json` | the same scripts, when the checks have passed | The landing waits for a build. Its kind is `interface` when it changes what other modules see (a statement, a definition, an instance or attribute, a removed import, a deleted module, any set), otherwise `proof`. |
| `done/<id>.json` | `build.py` after a passing build, or `landing.py revert` | Verified, with the commit; or reverted, with the reason. Kept for a week. |
| `last.json` | `build.py` | The last build: result, commit, failing modules, and the landings that may have caused them. |

One build:

1. **Snapshot**, holding `local/tree.lock` for a few seconds: commit the tree, copy the sources into the copy, replace the files of in-flight landings by their previous version, and note which requests the snapshot contains.
2. **Build** the copy with `lake build`.
3. **Start over** when an `interface` request arrives while the running build contains none: that landing is the one most likely to break other modules, and the groups should learn it soon. A build that contains an interface landing is never stopped; what arrives during it waits for the next build. So a build is stopped at most once.
4. **Passed**: publish. The changed compiled files are copied into `lean/.lake/build`, each written completely before it replaces the old one; `local/PUBLISHING` exists meanwhile, and single-file compiles wait for it. The requests of the snapshot move to `done/`.
   **Failed**: nothing is published. `build.py` prints the failing modules and, for each, the landings of the snapshot it depends on, interface landings first. The build is repaired and `build.py --retry` run. `landing.py revert` puts a landing's files back, unless one of them was changed again since.

The first build in a new copy may compile the whole library once.
