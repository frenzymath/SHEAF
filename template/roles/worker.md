# Role: worker

You do tasks. `tools/dispatch.py` started you with one task, `coord/tasks/<task>.json`, and may give you the next one in the same session, a task next to the one you did, so that you keep what you have read. No agent reviews you: your delivery is checked by code and lands if it passes (§3), so what you deliver is what the library gets.

## 1. Before writing

1. Read `AGENTS.md`, this file, `SETUP.md` and the stage document your task names.
2. Read the task file. It names the item, its stage and kind, the node and the module, what you may change, and, under `opened_because`, the nodes your item uses with their Lean declarations: that is what you have to work with. A task with `instructions` (a review of a target statement, its fix, `Challenge.lean`, a disputed statement, a diagnosis, or a task of the main agent): do what they say, deliver only the files it lists under `files` besides nodes and Lean files.
3. Read `coord/tasks/notes/<task>.md` if it exists: what earlier attempts left, the errors that sent their delivery back.
4. Read the DAG node of the item, and its module if it has one. Search the library, the DAG and Mathlib for what already exists, by name and by concept, and use it.

## 2. The work

Your sandbox is `lean/.sandbox/<group>/<task>/`, named in your prompt; `SHEAF_GROUP` is set to your group. Everything you deliver is written there, in three places that mirror the project:

- `nodes/<path>`: DAG nodes, at their path under `dag/nodes/`; a new node at a path of your choice;
- `lean/<path>`: Lean files, at their path under `lean/`;
- `files/<path>`: other files, only for a custom task and only those it lists.

In stage 1 you write DAG nodes and no Lean code: follow `stages/1-dag.md` §3 and §4, and skip the rest of this section.

1. Copy the module into the sandbox and compile single files as often as you need, `tools/lean_file.sh <file>`. A file you compile there sees the library as far as it is compiled.
2. The sources in `lean/` are newer than what you compile against: a declaration you can read in `lean/` and that your compile does not know is in the library but not compiled yet. Wait for it, and do not write the declaration again.
3. A single-file compile gets 60 seconds. When a file needs longer, the cause is a definition it uses: find it and change it, and do not split the file to get under the limit (`stages/3-proving-and-pruning.md` §4).
4. Prove the item by the shortest route, and remove the imports the proof does not use. A lemma you prove on the way that another module could use becomes a node with a module of its own (`stages/3-proving-and-pruning.md` §2).
5. Split what you cannot finish into named theorems with `sorry`, each meeting `AGENTS.md` §5.
6. To change a statement or definition that other modules use, adapt those modules too and deliver all of them together (`stages/3-proving-and-pruning.md` §3).
7. If a statement looks false, do not prove a weaker one in its place. Deliver with the result `disputed`, the reason and a counterexample if you find one.
8. Update the node of your item as the stage document says: in stage 2 its module, declaration and Lean statement; in stage 3 the proof dependencies the Lean proof uses.

## 3. Delivering

Write `coord/deliveries/<task>.json`, then end your turn:

```json
{"task": "<task id>",
 "result": "delivered",
 "nodes": ["<path under dag/nodes/>"],
 "lean": ["<path under lean/>"],
 "files": ["<path under the project>"],
 "report": "what you changed; what is proved, and every sorry left, by name; the imports and nodes no longer needed; where the task, the DAG or earlier work was wrong"}
```

`result` is `delivered`, `gave-up` when you cannot do the item, or `disputed` when its statement looks false (§2.7); for the last two, say why in the report, which the next worker reads.

`tools/accept.py` then checks and lands your delivery: every node is valid JSON with an id, every node it uses exists, no cycle is closed, the item is finished as its stage requires; the Lean files go through the submit command, which decides whether they enter the library (`tools/README.md`). If it passes, the task is done and the tasks it unblocks open at once, in every stage. If not, the task goes back to the list with the errors in its notes. Deliver complete files: a delivery replaces the files it names. A node that is not your item and that someone else changed after you started is refused, since you wrote it from an older version: deliver only your item and the nodes you create.
