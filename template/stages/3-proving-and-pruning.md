# Stage 3: proving and pruning

**Produces:** the library accepted by the completion criterion of `GOAL.md`.

## 1. Who does what

An item of this stage is a module that contains `sorry`, that a target reaches, through the DAG or through the imports of `lean/TargetsCheck.lean`, and whose node's proof dependencies all have a Lean declaration or are in Mathlib, at whatever depth below the target. A module whose proof would use a node that is not stated yet waits until stage 2 has stated that node: a prover must see what it can use before choosing a route. This stage goes from the targets downward.

- `tools/tasks.py` opens a task for every such module, in this order: the repairs in `coord/repairs.txt`, the statements marked `STATEMENT-DISPUTED`, then the rest, nearest to a target first. A module opens the moment the last node its proof uses is stated. The task lists those nodes with their declarations.
- A **worker** proves its module (§2), and records in its node the proof dependencies the Lean proof uses.
- `tools/accept.py` lands it. If `sorry` is left, the task stays open for the next worker. A node that a recorded proof no longer uses is no longer reached from a target, and its task is withdrawn: that is the pruning.

## 2. Pruning

- The proof in the DAG is a plan. An item may be proved by any route, and the shortest is the best: a special case, a Mathlib lemma, a simpler argument.
- A `sorry` that a new route leaves behind has a source and meets `AGENTS.md` §5. An idea without a source that would leave `sorry`s goes into the report, not into the library.
- Once a proof compiles, remove the imports it does not use. A module that no target reaches any more has no task and is never proved; its node records why.
- A lemma the proof needs that another module could use becomes a node, under the rules of stage 1, with a module of its own that the proof imports, and is never `private`: a result with a name or a place in the literature, and also a general lemma about Mathlib's objects or about Lean that Mathlib lacks.

## 3. Changing a definition or a statement

Any worker may change a definition or an intermediate statement that turns out to be wrong or hard to use.

1. Change in a module that is not your item only what the adaptation requires, and name it in the record of step 3. Another worker may hold that module: deliver complete files built on the version in the library, and say in your report which modules of others you adapted.
2. List the modules that depend on it, and check for each that what it states does not become weaker, stronger or different.
3. Write `coord/changes/<name>.md`: the reason, the old and the new version, the effect on each user, and the status.
4. Deliver the change with all adapted modules together: they land as one set. Close the record when the set is in the library.

A target statement keeps its elaborated type, and a target whose statement uses the changed definition is reviewed again (`stages/2-statements.md` §4).

Of two definitions of one notion, keep the better one and make the other name an `abbrev` of it.

A statement believed false is marked `STATEMENT-DISPUTED: <reason>` and its task comes before the others. Whoever takes it looks for a counterexample, finds the correct statement, and changes it by the steps above.

## 4. Slow compiles

A file that exceeds the time limit is slow because of the definitions it uses, not because of the length of its proofs. Do not split the file or the proof to get under the limit. Find the definition that is expensive to unfold or to elaborate, and change it (§3): that repairs every module using it at once.

## 5. Finished when

No task of this stage is open, the library compiles, and both parts of the completion criterion of `GOAL.md` hold:

- Lean comparator, run on the commit of that build, accepts the library against `lean/Challenge.lean`;
- the review of every target in `coord/targets-review/` holds for the definitions as they are now.
