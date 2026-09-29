# Stage 3: proving and pruning

**Produces:** the library accepted by the completion criterion of `GOAL.md`.

## 1. Who does what

An item of this stage is a module that a target reaches and that contains `sorry`.

- The **maintainer** keeps the queue. It is computed from the imports in the Lean code, not from the DAG: the modules that `lean/TargetsCheck.lean` reaches and that contain `sorry`, in this order: the repairs in `coord/repairs.txt`, the statements marked `STATEMENT-DISPUTED`, then the rest, nearest to a target first. Proving from the top shows which nodes below are needed.
- A **lead** claims modules and gives each to a worker.
- A **worker** proves its module (§2).
- The lead reviews and lands it.

## 2. Pruning

- The proof in the DAG is a plan. An item may be proved by any route, and the shortest is the best: a special case, a Mathlib lemma, a simpler argument.
- A `sorry` that a new route leaves behind has a source and meets `AGENTS.md` §5. An idea without a source that would leave `sorry`s goes into the report, not into the library.
- Once a proof compiles, remove the imports it does not use. A module that no target reaches any more leaves the queue and is never proved; its node records why.
- A result the proof needs and the DAG lacks becomes a node, under the rules of stage 1.

## 3. Changing a definition or a statement

Any worker may change a definition or an intermediate statement that turns out to be wrong or hard to use.

1. The lead claims the module and the modules that must be adapted. A module that another group has claimed stays with that group: change in it only what the adaptation requires, and name it and its group in the record of step 3.
2. List the modules that depend on it, and check for each that what it states does not become weaker, stronger or different.
3. Write `coord/changes/<name>.md`: the reason, the old and the new version, the effect on each user, and the status.
4. Land the change with all adapted modules as one set. Close the record when the global build has verified the set.

A target statement keeps its elaborated type, and a target whose statement uses the changed definition is reviewed again (`stages/2-statements.md` §4).

Of two definitions of one notion, keep the better one and make the other name an `abbrev` of it.

A statement believed false is marked `STATEMENT-DISPUTED: <reason>` and goes to the front of the queue. Whoever takes it looks for a counterexample, finds the correct statement, and changes it by the steps above.

## 4. Slow compiles

A file that exceeds the time limit is slow because of the definitions it uses, not because of the length of its proofs. Do not split the file or the proof to get under the limit. Find the definition that is expensive to unfold or to elaborate, and change it (§3): that repairs every module using it at once.

## 5. Finished when

The queue is empty in a green build, and both parts of the completion criterion of `GOAL.md` hold:

- the maintainer has run Lean comparator on the commit of that build, and it accepts the library against `lean/Challenge.lean`;
- the review of every target in `coord/targets-review.md` holds for the definitions as they are now.
