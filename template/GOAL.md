# GOAL

Formalize the following results of <paper> with no `sorry`.

| Label in the paper | Statement in one line | Lean declaration | Module |
|---|---|---|---|

Out of scope: <…>.

Completion criterion, both parts:

1. [Lean comparator](https://github.com/leanprover/comparator) accepts the library against `lean/Challenge.lean`: every target is proved with exactly the statement written there, with no axiom beyond `propext`, `Classical.choice`, `Quot.sound`.
2. Every statement in `lean/Challenge.lean`, read with the definitions it uses, means exactly what the statement in the paper means, as the review in `coord/targets-review.md` shows.
