# Stage 2: formalizing the statements

**Produces:** a compiling Lean library with a definition or statement for every node that is not in Mathlib, every proof `sorry`, and the target statements locked in `lean/Challenge.lean`.

## 1. Who does what

An item of this stage is a node that a target reaches, that stage 1 is finished with (`stages/1-dag.md` §2), that is not in Mathlib, that has no Lean declaration yet, and whose statement dependencies all have one or are in Mathlib. A node that fails the last condition is not open, however near a target it is.

- `tools/tasks.py` opens a task for every open node, in the order of §2. A node opens the moment the last node its statement uses lands, while stage 1 goes on elsewhere; the task lists those nodes with their declarations.
- A **worker** writes the module of its node: the definition, or the statement with `sorry` as its proof (§3).
- `tools/accept.py` lands it, and the node counts as stated once the module it records is in the library.

## 2. Order

The order is set by the dependencies: a node is stated after the nodes its statement needs, so this stage climbs from Mathlib upward whatever order stage 1 and stage 3 keep. Stating from the targets downward is an error: a statement written before the definitions it uses exist cannot compile, and a queue ordered that way stops every worker. Every node that is not in Mathlib is formalized, whether the targets need it for their statements or for their proofs. Within what is open, the nodes nearest to Mathlib come first, counted in dependency steps down to a Mathlib leaf. `SETUP.md` decides one exception:

- **The human asked for an early review of the target statements.** Then only the nodes needed to state the targets are open in this stage, and no module in stage 3. When they are stated, the main agent has `Challenge.lean` written and the targets reviewed (§4), and asks the human to confirm them (`coord/HUMAN.md`). When the human has, it creates `coord/targets-confirmed`, and the rest opens.
- **Otherwise** the targets are reviewed when their statements compile, and nothing waits for it.

## 3. Statements

1. One definition per notion. Use Mathlib's definition whenever it exists.
2. No hollow definitions (`AGENTS.md` §5).
3. A statement is true, and exactly as strong as the proofs that use it need. Check its edge cases, and write out the hypotheses the source assumes throughout.
4. One module per node. Directories follow Mathlib's topics; what is specific to the paper goes under `Paper/`, the targets under `Targets/`.
5. Every module, definition and statement has a docstring with its source. The docstring of a statement carries the proof of its node.
6. Record in the node its module, its declaration and its Lean statement.
7. The module imports the modules of the node's statement dependencies, and of those proof dependencies that are stated. An import of a module that is in the library but not compiled yet fails in a single-file compile until it is compiled; that is not an error (`roles/worker.md` §2). A module is never edited only to add an import: the worker who proves it imports what its proof uses. Stage 3 finds its items through the DAG, so a stated node does not need to be imported to be proved.

## 4. The targets

When target statements are in the library, the code writes `lean/TargetsCheck.lean` and opens the tasks for the rest (`tools/tasks.py`):

- `lean/Challenge.lean`: the target statements verbatim, with `sorry` proofs, importing only the modules that define what the statements use;
- `lean/TargetsCheck.lean`: imports the target modules and nothing else. What it reaches is what the targets need.

`Challenge.lean` must say what the paper says (`AGENTS.md` §4). A worker that did not write the target statement reviews it, in a task the code opens when the statement is in the library and again whenever the statement or a definition it uses changes, and writes `coord/targets-review/<target>.md`, whose last line is `Verdict: locked` or `Verdict: defect`:

- the statement in the paper, word for word, with its place, and the Lean statement;
- every hypothesis and every part of the conclusion of the one, matched with its counterpart in the other;
- every definition the Lean statement uses, down to Mathlib, matched with the definition in the paper, with each difference and why it changes nothing.

Anything added, dropped, weakened or defined differently is a defect: the code opens a task to fix the statement or the definition, and the fixed version is reviewed again. A target is locked once the review of its present version finds no defect; when every target is locked, the code opens the task that writes `Challenge.lean`. No human is needed for this; the human is asked only if `SETUP.md` asks for an early review (§2).

When a definition that a target statement uses changes later, that target is reviewed again.

## 5. Finished when

In a green build:

- every node that is not in Mathlib has a compiling declaration, recorded in the node;
- the target statements in the library have the same elaborated types as in `Challenge.lean`;
- every target is reviewed and locked.
