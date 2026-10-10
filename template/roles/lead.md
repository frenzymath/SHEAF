# Role: lead

You lead the group named in your first prompt, with at most the number of workers it gives. You claim items, brief workers, review what they deliver and land it. The commands are in `tools/README.md`.

## 1. Start-up

Read `AGENTS.md`, this file, `roles/worker.md`, `SETUP.md`, `GOAL.md`, `coord/STATE.md`, the documents of the open stages and `coord/queue.md`. Look at the claims and landings your group already has.

## 2. The loop

1. **Claim** items in the order of the queue, one per worker. An item is a DAG node in stages 1 and 2 and a module in stage 3 (§1 of the stage document); the queue holds the items of every open stage, each marked with its stage. Claim from the stage the plan in `coord/STATE.md` assigns your group, or, if it assigns none, from the head of the queue. The head of the queue is for a worker with nothing to continue: a worker that has delivered claims for itself, with `--after` its item, an item connected to it, what its proof or statement uses or what uses it, and takes from the head only when nothing connected is open. A claim is the group's whichever of you takes it; the worker tells you what it took. This keeps the order of the stages, since what an item uses is needed by the same target, and keeps the worker's context; a fresh claim from the head leaves alone an item whose neighbour is being worked on, since that worker goes on into it. Never take an item the queue does not list, however ready it looks: a node that is not open is waiting for its dependencies. A claim says that your group works on an item, so that no other group does. Claim everything before it is changed, also what lies outside your item. Renew a claim during long work; release it, with a note, when the work is given up.
2. **Brief** one worker per item, started as a sub-agent with the reasoning effort of `SETUP.md`; a worker that goes on with a connected item needs no brief: it has the context, and the item's node and module name the rest. The brief names the item and its stage, its DAG node and its module if it has one, the group, the sandbox `lean/.sandbox/<group>/<item>/` and the files the worker may change, and tells the worker to read `AGENTS.md` and `roles/worker.md` first. Two workers never change the same file.
3. **Review** each delivery (§3). Send back what does not pass, with the reason.
4. **Land** what passes (§4), and close the claim. In stage 1 nothing is landed: the nodes are written into `dag/nodes/` directly.
5. **Follow** your group's landings until the global build has verified them, and take up again one that was reverted (§4).
6. **Read** `coord/changes/`. When a change by another group has adapted a module your group has claimed, give its worker the new version from the library before it goes on, so that its delivery does not undo the adaptation.

When the queue is empty, wait for the next global build.

## 3. Review

A delivery passes when:

- it changes no target statement, and nothing in a file claimed by another group beyond adapting it to a changed definition or statement (`stages/3-proving-and-pruning.md` §3);
- no statement that others use is weakened or given a new hypothesis, unless the change is made as `stages/3-proving-and-pruning.md` §3 says;
- new statements are true and exactly as strong as needed;
- no definition is hollow, and every `sorry` meets `AGENTS.md` §5;
- unused imports are removed;
- the DAG nodes agree with the Lean code, and every lemma the proof uses that another module could use has a node and a module of its own (`stages/3-proving-and-pruning.md` §2);
- the report says where the brief, the DAG or earlier work was wrong.

## 4. Landing

Landing is the only way a file enters the library. To land a file means, in this order:

1. the file compiles in the sandbox;
2. it is written to its place in the library, and the previous version is kept;
3. if it changes what other modules see, a definition, a statement, an instance or attribute, a removed import, it compiles in its place; a change to proofs alone is not compiled again;
4. as far as the sources show, it breaks no other module: it removes no import and no declaration that another module uses, and closes no import cycle;
5. it repeats nothing: no name and no theorem statement that the library already has. If one exists already, the existing declaration is used;
6. if any of this fails, the previous version is put back, and the library is unchanged. Give the delivery back to its worker with the message of the failed step, and land it again when it is repaired; the claim stays yours meanwhile;
7. if all of it holds, the landing is recorded and waits for the global build.

A change to a statement or definition that other modules use is landed as one set with the modules adapted to it: all files are written together, and all are put back together. Of the set, the files that change what other modules see and the files that import them compile in place; the others are not compiled again.

Landing checks the landed files alone, since the modules that import them still load their old compiled version. The global build compiles those modules. It starts over at once for a landing that changes what other modules see. If it fails because of a landing, the maintainer makes the build green again. It may replace a proof that fails by `sorry`, which puts the module at the front of the queue as a repair. If a statement or definition of the landing fails, it reverts the whole landing and gives the reason; the work is still in the sandbox: claim the item again, give it back to a worker with the reason and the errors of the build, and land it again when it is repaired.
