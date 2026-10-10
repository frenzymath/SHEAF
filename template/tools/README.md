# Tools

Small scripts for the few things that must be done exactly: compiling against the shared build, changing the shared library safely, building it, and checking the targets. How to do the mathematics is up to the agents; nothing here decides it.

What must hold, and why, is written in `AGENTS.md` §3 and in the role documents. The scripts are one way to carry it out. The usage of each script is in the comment at its top.

## Changing the tools

The scripts were written for one machine and one project, and may be changed to fit the project at hand: another DAG layout, another layout of the Lean project, a limit that is too tight, a check that refuses correct work or misses wrong work.

The maintainer decides on a change and makes it, since every agent runs the same scripts and a change reaches all of them at once. Leads report what does not fit to the maintainer, workers to their lead. The maintainer:

- keeps what the contract asks for: a changed script still does what the role documents say the step does;
- tries the change on a copy, then replaces the script in one step, never editing it in place while others may be running it;
- updates this file in the same change, and writes one line in `coord/ledger.md`: what changed and why.

## Configuration

Two files, both committed with the project, so every machine sees the settings of the others. The launcher writes them.

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
SHEAF_CLAIMS_PER_GROUP=10     # claims one group may hold at once
SHEAF_CLAIM_TTL=6             # hours after which an unrenewed claim may be taken over
```

The scripts that compile and land take the name of the group from `SHEAF_GROUP`: call them as `SHEAF_GROUP=<group> tools/…`. The sandbox of a group is `lean/.sandbox/<group>/`.

## Compiling and landing

| Tool | What it is for |
|---|---|
| `lean_file.sh <file>` | Compile one file, with 2 threads and a limit of 60 s. A library file compiled here is visible to the group's later compiles before the next global build, so a group can land a new lemma module and then the module that imports it. |
| `land.sh <sandbox file> <library file>` | Put a finished file into the library. Compiles it in place when it changes what other modules see; a change to proofs alone enters on the worker's compile and the lead's review. Refuses it (putting the old version back) if it removes an import or a declaration some other module still needs, adds a name another module already declares, adds a theorem whose statement the library already states word for word, or closes an import cycle. |
| `land_set.sh <set directory>` | Put a set of files into the library at once: a changed statement or definition together with the modules adapted to it. Compiles in place the files that change what other modules see and the files of the set that import them, and runs the same checks on each file; the modules downstream of the set are compiled by the global build, which starts over as soon as the set has landed. |
| `landing.py status / mine <group> / revert <id> <reason>` | The landings that are being checked or wait for the global build, and the last build's result; a group's open and reverted landings; `revert` is the maintainer's. |
| `build.py [--retry]` | The global build, for the maintainer (§ The global build). When nothing has landed it waits for the next landing, and builds as soon as it arrives. After a red build, `--retry` builds the same snapshot again with the maintainer's own landings and without the landings it reverted, and nothing else. |

A single-file compile of a module cannot show its effect on other modules, because they still load its old `.olean`. That is why landing runs `import_prune_check.py`, and why every landing is verified afterwards by the global build. The check reads source text: it does not see a removed import that only provided an instance, which the build shows.

## Planning a change

| Tool | What it is for |
|---|---|
| `downstream.py <module> [--uses <name>]` | Which modules depend on a module, and which of them mention a declaration. Run it before changing a statement or definition. |
| `import_prune_check.py <module> <old> <new>` | The check `land.sh` and `land_set.sh` run; it can be run by hand on a planned change. |

## Coordinating

| Tool | What it is for |
|---|---|
| `claim.py next [--stage N] [--after ITEM] / take / renew / done / release / mine / list / expire` | Claims on items, so that no two agents work on the same one. `next` takes from the head of the queue, or from one stage of it; with `--after` it takes first what is connected to that item in the DAG, so that a worker goes on with what its item uses or what uses it; without it, it takes first an item none of whose neighbours is claimed, since the worker of a claimed neighbour goes on into it. |
| `queue.py write / summary / outside` | The work queue, `coord/queue.md` to read and `coord/queue.tsv` for `claim.py`: the open items of every open stage, each with its stage. Stage 1 first, then 2, then 3. Stage 1 and 2 items come from the DAG through `dag_queue.py`, stage 1 nearest to a target first and stage 2 nearest to Mathlib first; stage 3 items are the modules the targets need that still contain `sorry`, repairs and disputed statements first, then nearest to a target, and a module whose proof would use a node that has no declaration yet is listed as waiting and cannot be claimed. `outside` lists the modules the targets do not need. |
| `dag_queue.py summary / items / waiting` | What `queue.py` reads from the DAG: the nodes still to split (stage 1), the nodes whose statement dependencies are all stated (stage 2), and the stated nodes whose proof uses an unstated node (the waiting modules of stage 3). It never lets a node be stated before the nodes its statement needs. The DAG layout is the project's own, so the field names it reads are in its `FIELDS` table at the top; the maintainer adapts them to the project's nodes, and `SHEAF_DAG` in `coord/sheaf.env` names the node directory when it is not `dag/nodes`. |
| `session_health.sh` | One line per session of this project: OK, QUIET, STUCK, WAITING (a question or prompt on screen), LIMIT or DEAD. |

## Checking

| Tool | What it is for |
|---|---|
| `target_types.sh check` | Whether each target statement in the library is exactly the one in `lean/Challenge.lean`, by comparing elaborated types; also prints each target's axioms. For the end of stage 2 and before the final check; it is not part of a build. |
| `hollow_defs.sh` | The definitions the targets reach that depend on `sorry` in any way. They are candidates: each is read to decide whether it is hollow or only refers to an unproved theorem for a proof it needs. For a lead that wants to check the definitions of its group. |

## The global build

The global build never compiles the tree the groups work in. `build.py` builds a copy, `local/buildtree/`, and brings the compiled files back, so nothing is frozen while it runs, a failed build leaves the groups' compiled files untouched, and a build can be stopped at any moment without harm. The copy shares `lean/.lake/packages` through a link and holds its own build output.

The groups and the build talk through records in `local/builds/`, the way claims are files in `coord/claims/`:

| Record | Written by | Meaning |
|---|---|---|
| `inflight/<id>.json` | `land.sh`, `land_set.sh`, when they write the files | The group is still checking the landing. A build started now takes the previous version of its files, from `backup/<id>/`. |
| `requests/<id>.json` | the same scripts, when the checks have passed | The landing waits for a build. Its kind is `interface` when it changes what other modules see (a statement, a definition, an instance or attribute, a removed import, a deleted module, any set), otherwise `proof`. |
| `done/<id>.json` | `build.py` after a green build, or `landing.py revert` | Verified, with the commit; or reverted, with the reason. Kept for a week. |
| `last.json` | `build.py` | The last build: result, commit, failing modules, and the landings that may have caused them. |

One build:

1. **Snapshot**, holding `local/tree.lock` for a few seconds: commit the tree, copy the sources into the copy, replace the files of in-flight landings by their previous version, and note which requests the snapshot contains.
2. **Build** the copy with `lake build`.
3. **Start over** when an `interface` request arrives while the running build contains none: that landing is the one most likely to break other modules, and the groups should learn it soon. A build that contains an interface landing is never stopped; what arrives during it waits for the next build. So a build is stopped at most once.
4. **Green**: publish. The changed compiled files are copied into `lean/.lake/build`, each written completely before it replaces the old one; `local/PUBLISHING` exists meanwhile, and single-file compiles wait for it. The requests of the snapshot move to `done/`.
   **Red**: nothing is published. `build.py` prints the failing modules and, for each, the landings of the snapshot it depends on, interface landings first. The maintainer makes the build green and runs `build.py --retry`. `landing.py revert` puts a landing's files back, unless one of them was changed again since.

The first build in a new copy may compile the whole library once.
