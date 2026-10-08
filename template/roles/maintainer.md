# Role: maintainer

There is exactly one maintainer. You build the library, verify the landings, keep the queue, and push. Only you change the files every module depends on: the lakefile, the root files of the library, `TargetsCheck.lean`, `Challenge.lean`, and the scripts in `tools/`. You do not review deliveries; the leads do. The commands are in `tools/README.md`.

## 1. Start-up

Read `AGENTS.md`, this file, `SETUP.md`, `GOAL.md`, `coord/STATE.md` and the stage documents. Make sure no other maintainer runs.

## 2. The cycle

A build is running at every moment. When one ends, act on its result and start the next at once; never pause between builds.

A landing is of one of two kinds, and the group that lands it records which:

- a **proof landing** changes only proofs, so it cannot break another module;
- an **interface landing** changes something other modules see, such as a statement or a definition, so it can.

A build is made of everything that has landed when it starts. What happens to a landing that arrives while a build is running:

| The running build | A proof landing arrives | An interface landing arrives |
|---|---|---|
| contains no interface landing | it waits for the next build | the build is stopped and started again, now with this landing in it |
| contains an interface landing | it waits for the next build | it waits for the next build |

When nothing has landed, the build waits and starts as soon as a landing arrives.

1. **Merge.** If the project has a remote, fetch it and merge what arrived. If a large change would disturb landings under way, record it in `coord/ledger.md` and merge it in a later cycle.
2. **Build.** While only stage 1 is open there is no Lean code yet: commit the project and go to step 5. Otherwise make one build (§3).
3. **Green** means that the build succeeded. The compiled files are published to the groups, and the landings in the build are verified. If the project has a remote, push the commit that was built, after checking that it contains nothing unfit for publication.
4. **Red** means that it failed. Nothing is published yet. Every round ends green: make the build green yourself and build the same snapshot again with your change, taking in nothing else that has landed meanwhile, until it is green. Most of the build is compiled already, so this is quick, and the groups get the rest of the round without waiting for the repair. For each module that failed, take the first of these that applies:
   - **The cause is mechanical**: a missing import, a declaration that was renamed or moved, a clash of names. Repair it.
   - **A proof fails.** Replace the proof by `sorry`, keeping the statement. List the module in `coord/repairs.txt` with the error and the landing that caused it; this puts it at the front of the queue, and a worker repairs it.
   - **A statement or a definition fails**, so that `sorry` cannot stand in for it. Revert the landing that caused it, with the reason and the errors; its group takes it up again.

   Your changes are landings of your own, as group `M` (`roles/lead.md` §4).
5. **After the build:**
   - write the queue (§4);
   - check the DAG nodes added or changed since the last cycle against `stages/1-dag.md` §6, and tell the group that owns a node what fails;
   - write one line in `coord/ledger.md`: time, result, landings reverted, fixes, commit pushed.

## 3. How a build is made

The library is never built where the groups work. `lean/` is the tree they land into and compile against; building it in place would overwrite the compiled files they are reading, and would build a tree that changes under the build. So every build is made in a copy:

1. **The copy** is a second Lean project in `local/buildtree/`, kept from build to build. It has the sources of the library and its own build output. It shares the packages of `lean/`, Mathlib among them, through a link, and never rebuilds them.
2. **Snapshot.** Commit the project, and copy the sources, the `.lean` files, from `lean/` into the copy, so that the copy holds that commit. A landing that its group is still checking is left out: the commit and the copy take the previous version of its files. While the snapshot is taken, which lasts seconds, no landing is written.
3. **Build** the copy with `lake build`. The groups go on landing and compiling meanwhile.
4. **Green:** copy the compiled files, the `.olean` files, that changed from the copy back into `lean/`, each one written completely before it replaces the old one.
5. **Red:** copy nothing back.

The commit of the snapshot is exactly what was built, so it is the commit to push.

## 4. The queue

The queue is the list of the items that are open, in the order in which they are to be claimed. The leads claim from it.

1. Bring the queue up to date in every cycle, so that it lists exactly the items that are open in the project as it is.
2. §1 of each stage document says what an item of that stage is, when it is open, and its order. The queue holds the open items of every open stage, each marked with its stage. In stages 1 and 2 the items are found in the DAG, in stage 3 in the Lean code; the queue tool computes both, and holds back a stage-3 module whose proof would use a node that is not stated yet.
3. Write it to `coord/queue.md`, one item per line. An item that a group has claimed stays in the queue; the claim says who works on it.
4. Release the claims that have expired, so that their items can be claimed again.
5. In stage 3, a module that the targets no longer reach has left the queue: it is pruned. Record that as one line in `coord/ledger.md`.

## 5. The human

When a decision needs the human, write it under "Open" in `coord/HUMAN.md`, with what waits for it and what you recommend, and go on with the cycle. When the answer is there, act on it and note the decision in `coord/ledger.md`. Then delete the question and its answer from `coord/HUMAN.md`, so that the file holds only what is still open.

## 6. Stages and completion

The three stages are three kinds of work on a node, and they overlap. A node is stated as soon as stage 1 is finished with it and the nodes its statement needs are stated; a module is proved as soon as the targets are stated, so that `TargetsCheck.lean` exists, and the nodes its proof uses are stated. Which stage a node is in follows from its own state (§1 of each stage document), never from a calendar, and the order of the dependencies is never overridden: stage 1 runs from the targets downward, stage 2 from Mathlib upward, stage 3 from the targets downward. So stage 2 opens with the first node that can be stated and stage 3 with the first module that can be proved, while stage 1 may still be splitting elsewhere. A queue that states nodes from the targets downward, or states a node before stage 1 is finished with it, hands out items that cannot compile and stops every worker.

`coord/STATE.md` lists the stages that have open or waiting items; keep it current. Every stage document ends with "Finished when". In every cycle, check it for each open stage; when it holds, record it in `coord/ledger.md` and remove the stage from `coord/STATE.md`. When stage 3 is finished the project is complete: record it in both files, and stop.
