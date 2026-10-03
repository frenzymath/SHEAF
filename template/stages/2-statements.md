# Stage 2: formalizing the statements

**Produces:** a compiling Lean library with a definition or statement for every node that is not in Mathlib, every proof `sorry`, and the target statements locked in `lean/Challenge.lean`.

## 1. Who does what

An item of this stage is a node that stage 1 is finished with (`stages/1-dag.md` §2), that is not in Mathlib, that has no Lean declaration yet, and whose statement dependencies all have one or are in Mathlib. A node that fails the last condition is not open, however near a target it is.

- The **maintainer** keeps the queue: the open nodes, in the order of §2. It builds the library and verifies the landings as in every stage (`roles/maintainer.md`).
- A **lead** claims nodes and gives each to a worker.
- A **worker** writes the module of its node: the definition, or the statement with `sorry` as its proof (§3).
- The lead reviews and lands it (`roles/lead.md`).

## 2. Order

The order is set by the dependencies: a node is stated after the nodes its statement needs, so this stage climbs from Mathlib upward whatever order stage 1 and stage 3 keep. Stating from the targets downward is an error: a statement written before the definitions it uses exist cannot compile, and a queue ordered that way stops every worker. Every node that is not in Mathlib is formalized, whether the targets need it for their statements or for their proofs. Within what is open, the nodes needed to state the targets come first, so that `Challenge.lean` can be written and stage 3 can begin; then the open nodes nearest to a target. Beyond that, `SETUP.md` decides:

- **The human asked for an early review of the target statements.** Formalize first only the targets and the nodes needed to state them, write `Challenge.lean`, review the targets (§4), and ask the human to confirm them (`coord/HUMAN.md`). Formalize the rest when they have.
- **Otherwise** the targets are reviewed when their statements compile, and nothing waits for it.

## 3. Statements

1. One definition per notion. Use Mathlib's definition whenever it exists.
2. No hollow definitions (`AGENTS.md` §5).
3. A statement is true, and exactly as strong as the proofs that use it need. Check its edge cases, and write out the hypotheses the source assumes throughout.
4. One module per node. Directories follow Mathlib's topics; what is specific to the paper goes under `Paper/`, the targets under `Targets/`.
5. Every module, definition and statement has a docstring with its source. The docstring of a statement carries the proof of its node.
6. Record in the node its module, its declaration and its Lean statement.

## 4. The targets

When the target statements compile, the maintainer writes two files:

- `lean/Challenge.lean`: the target statements verbatim, with `sorry` proofs, importing only the modules that define what the statements use;
- `lean/TargetsCheck.lean`: imports the target modules and nothing else. What it reaches is what the targets need.

`Challenge.lean` must say what the paper says (`AGENTS.md` §4). An agent that did not write the target statement reviews it and writes into `coord/targets-review.md`:

- the statement in the paper, word for word, with its place, and the Lean statement;
- every hypothesis and every part of the conclusion of the one, matched with its counterpart in the other;
- every definition the Lean statement uses, down to Mathlib, matched with the definition in the paper, with each difference and why it changes nothing.

Anything added, dropped, weakened or defined differently is a defect: the statement or the definition is fixed. A target is locked once its review finds no defect. No human is needed for this; the human is asked only if `SETUP.md` asks for an early review (§2).

When a definition that a target statement uses changes later, that target is reviewed again.

## 5. Finished when

In a green build:

- every node that is not in Mathlib has a compiling declaration, recorded in the node;
- the target statements in the library have the same elaborated types as in `Challenge.lean`;
- every target is reviewed and locked.
