---
name: compiling
description: Choose how the project compiles what workers deliver, from the machine's CPU and memory and the number of workers, and set the submit command to match.
---

# Compiling

Read this when you set up the project, and again when the number of workers or the machine changes. It decides how a delivery's Lean files are checked and how they enter the library. The choice is recorded in `coord/STATE.md` and carried out by the submit command (`submit_cmd` in `coord/dispatch.json`). `tools/README.md` names a submit command for each layout. They are sketches, written quickly: change them, or write your own, to fit the project and the machine, as long as §4 holds.

## 1. What decides

Only the machine's resources against the number of workers. Measure on this project, not from experience elsewhere:

- a full build of the library, `lake build` in a fresh copy: its peak memory and the cores it keeps busy;
- a single-file compile of a typical module against the built library: its peak memory and time.

Then compare what each layout below needs with what the machine has, for the number of workers you intend to run.

## 2. Two kinds of change

A change to a file either changes only proofs, or changes what other modules see: a statement, a definition, an instance or attribute, a removed import, a deleted module. A proof change affects no other file, and a single-file compile against the built library checks it. A statement change can break every module that depends on it, and only a build of those modules checks it. Every layout below follows from handling the two kinds separately.

## 3. The layouts

**Resources far beyond the workers: one worktree per worker.** There is one main repository. Every worker has its own worktree of it and runs `lake build` there while it works. A finished delivery goes to the main repository as a pull request, and the managing agent below builds it into the main repository. Statement changes need no special path here, since every batch is built with everything that depends on it.

**Resources far below the workers: one frozen repository.** There is a single Lean repository, and a statement is frozen once it is in. Workers add new files and new declarations, and change only the proofs of declarations that exist. A proof change is checked by a single-file compile against the repository's compiled files. New statements are checked by compiling the new files together, in the order of their imports; since nothing that exists changes, no other module needs a rebuild. A statement found wrong is not changed: it is replaced by a new declaration, and its users move to the new one, which is expensive when a long chain depends on it.

**Resources in between: a frozen main repository and isolation repositories.**

- The main repository is the authority. Its statements change only through the isolation path below. Workers that change proofs compile single files against its compiled files, and their proof changes enter it directly.
- An isolation repository, a separate copy, is where every statement change goes. Each change comes with the modules adapted to it as a pull request, and the managing agent below builds it into the isolation repository.
- With more resources, give the managing agent several isolation worktrees, so that independent statement changes are built at the same time.
- At fixed intervals the managing agent merges the isolation repository into the main repository. Proof changes and statement changes touch different parts of the library, so conflicts should be rare; the managing agent resolves those that occur. It builds the merged main repository, and then copies it with its compiled files to every copy the workers compile against.

**The managing agent.** In the first and the third layout, one managing agent builds the pull requests into its repository, and it takes them in batches: it merges a batch together and builds once, with everything that depends on what the batch changes. Building once for every pull request would keep the repository building without end. The managing agent decides what goes into each batch: it may take only the pull requests that belong together and leave the others for a later batch. When the batch passes, it enters the repository; when it fails, the managing agent finds the pull requests that break it, sends them back to their workers, and builds the rest again.

## 4. In every layout

- Nothing enters the library without having been compiled where it is going: a proof change by a single-file compile, a statement change by a build of what depends on it.
- A worker never compiles against a statement change before that change has been verified with its dependents.
- When the measurements or the number of workers change, choose again; record the new choice in `coord/STATE.md`, change the submit command, and lower `slots` if compiles start to wait for memory.
