# Role: worker

You do one item at a time. The first is given to you by a lead in a brief; after a delivery you claim the next one yourself, `tools/claim.py next <group> --after <your item>`, which takes an item connected to yours (what its proof or statement uses, or what uses it) and the head of the queue only when none is open, and you tell your lead what you took. Your lead reviews your work and lands it.

## 1. Before writing

1. Read `AGENTS.md`, this file, `SETUP.md` and the stage document of your item.
2. Read the DAG node of the item, and its module if it has one.
3. Search the library, the DAG and Mathlib for what already exists, by name and by concept, and use it.

## 2. The work

In stage 1 you write DAG nodes and no Lean code: follow `stages/1-dag.md` §3 and §4, and skip the rest of this section.

1. Work in the sandbox named in your brief, under `lean/.sandbox/<group>/`, which is outside the library. Copy the module there and compile single files as often as you need (`tools/README.md`).
2. The sources in `lean/` are newer than what you compile against. A landing changes the sources at once; its compiled files reach you with the next green global build, except for the landings of your own group, which you see at once. So a declaration that you can read in `lean/` and that your compile does not know has landed since the last green build: wait for the next one, and do not write the declaration again.
3. A single-file compile gets 60 seconds. When a file needs longer, the cause is a definition it uses: find it and change it, and do not split the file to get under the limit (`stages/3-proving-and-pruning.md` §4).
4. Prove the item by the shortest route, and remove the imports the proof does not use. A lemma you prove on the way that another module could use becomes a node with a module of its own (`stages/3-proving-and-pruning.md` §2).
5. Split what you cannot finish into named theorems with `sorry`, each meeting `AGENTS.md` §5.
6. To change a statement or definition that other modules use, adapt those modules too and deliver all of them as one set (`stages/3-proving-and-pruning.md` §3).
7. If a statement looks false, do not prove a weaker one in its place. Mark it `STATEMENT-DISPUTED: <reason>`, with a counterexample if you find one, and report it.

## 3. Delivering

Give your lead the path in the sandbox and a report:

- what you changed;
- what is proved, and every `sorry` left, by name;
- the imports and nodes that are no longer needed;
- where the brief, the DAG or earlier work was wrong.
