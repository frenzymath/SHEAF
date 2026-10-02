# SHEAF

**SHEAF** (Scalable Hierarchical Engine for Autonomous Formalization) is a fully automated formalization framework for Lean 4, based on pruning a dependency graph of statements.

Its first result is **<https://github.com/frenzymath/MiyaokaMori-CharZero>**.

## Why SHEAF

Agent systems such as Claude Code and Codex can now formalize any mathematical content, given enough time. But in a real formalization two problems come up again and again.

- **Progress cannot be seen.** The number of `sorry`s is not a measure of it: splitting one proof into five steps raises the number and is progress, and a file without `sorry` may rest on a wrong definition. SHEAF works on a DAG of statements with locked targets. What remains to be done is the list of the modules that the targets still need and that are not proved, and a human can read it at any time.
- **Agents do not choose the cheapest route.** Left alone, an agent formalizes what the paper cites, in the generality in which it is cited. SHEAF proves from the targets downwards and takes only what each proof uses, so what turns out not to be needed is never proved.

## Getting started

Clone this repository and start an agent in the root of the clone: Claude Code, Codex or any other. Start it inside tmux, because it watches over the project for the whole run and must keep running after you close your terminal. Then talk to it; it reads [`AGENTS.md`](AGENTS.md) and guides you from there. Each project it creates lives in a directory of its own here, which is a git repository that you can publish under your own account.

> The scripts in [`template/tools/`](template/tools/) are vibe-coded. Let your agents change them as your project needs.

## Pipeline

All stages work on one object, a DAG of statements.

![The three stages on a small DAG](docs/pipeline.gif)

White: a node with a natural-language proof only. Light green: its statement is written in Lean, the proof is `sorry`. Green: proved. Grey: pruned. Dark: in Mathlib.

1. **Natural-language DAG.** Every definition and result of the paper is split, and each piece is looked up in Mathlib; what Mathlib lacks is split further, until every branch reaches Mathlib. Each node is a statement with a self-contained natural-language proof, and records separately what it needs to be stated and what its proof uses.
2. **Statements.** The statements of all nodes are formalized from Mathlib upwards, with real definitions and `sorry` proofs, in one library that compiles from the start, and the target statements are locked.
3. **Proving and pruning.** The proofs are filled in from the targets downwards, and what they do not use is never proved. The project is accepted when [Lean comparator](https://github.com/leanprover/comparator) accepts the library against the locked target statements, with no axiom beyond `propext`, `Classical.choice` and `Quot.sound`, and every locked statement means exactly what the paper's statement means.

## Features, and what we observed

The sections below describe the features of SHEAF. Each ends with what we observed in its first application, the formalization of *Constructing Rational Curves via Jets on Projective Varieties with Non-Nef Canonical Bundle* ([arXiv:2609.28465](https://arxiv.org/abs/2609.28465)).

### Pruning the DAG

Before any Lean is written, the human proof is split into a DAG. This shows at every moment how far the formalization is, keeps the model from inventing a proof that is wrong, and keeps it from misjudging how much of the work is done. The formalization then goes from the top down, which saves time and tokens. A natural-language proof is often not the easiest route to a formal one: a step may cite a general theorem where a special case suffices, or an easier route may exist. Agents prove from the targets downwards and take only what each step uses. After a proof lands, its unused imports are removed, and the work queue is computed from the imports, so a node no longer reached from a target is never worked on.

**Observed.** We compared the finished formalization with the initial DAG. The DAG is a reliable plan: of the 1,766 nodes of the formalization that carry mathematics, the DAG lacks only 25, which is 1.4%, and all of them are standard facts, none from the paper itself. Of the nodes added during the formalization, 48% split an existing proof further, 29% are Lean technicalities, and 19% come from a change of route. Of the 1,706 nodes of that DAG that are not in Mathlib, the formalization uses 639. The other 1,067, which is 62.5%, were never needed. Pruning grows with the distance from the targets: of the nodes within two steps of a target 13% were pruned, of those seven or more steps away 83%. Most of it comes from a few changes of route, each of which removed a whole theory: Raynaud–Gruson flattening, derived categories and perfect complexes, spectral sequences, Cohen–Macaulay modules. Of the nodes that are used, 27% were split further while they were proved, into three more nodes on average, so the number of `sorry`s rose while the work advanced. (These numbers differ from those in the paper. In the DAG examined for the paper, a branch could end either in Mathlib or in the code already written for the earlier Danus paper, so it did not go all the way down to Mathlib. Afterwards we split the DAG completely, down to Mathlib, and that gave the numbers here.)

### Many agents, one library

The agents share one Lean library, which saves machine resources: many agents work at once, and the library is built in one place only. Definitions can still be corrected while the work goes on. A single maintainer builds a copy of the library again and again and publishes only verified green builds. Workers compile single files against the last green build in seconds. A file enters the library only through a landing step that reverts on failure and refuses a change that would break another module or repeat what the library has; a changed statement or definition lands together with the modules adapted to it, and makes the build start over so that it is verified first. Work is coordinated through files: atomic claims, landing records, a queue, and logs. The process is written as contracts the agents read.

**Observed.** [Prove2Me](https://arxiv.org/abs/2608.28433) separates the statement of a theorem from its proofs. Every statement is a standalone object that cannot be edited once it is submitted, and proofs are submitted separately. A theorem can therefore be proved without compiling what depends on it. Its cost is that a statement found to be wrong cannot be corrected in place: the correction is a new theorem, and what was built on the old one does not carry over to it, which is expensive when the chain of dependencies is long. SHEAF takes over these advantages and tries to remove this cost. It works in one ordinary Lean library, where a statement or a definition can be changed at any time together with the modules that use it, and the landing step and the global build keep the library sound while it changes. We ran it on two servers at the same time, with hundreds of agents at work, and everything worked.

### Definitions may change

A definition or intermediate statement is often found inadequate only when it is used. Any worker may change one after checking; a statement believed false enters a repair queue; of two definitions of one notion only the better is kept.

**Observed.** Until the targets were first proved, 2,566 definitions were written, and 80 of them were revised after they had been in use. Of these 80, 71 were revised in the first 40% of the work, measured by the share of the final declarations that were proved; after 60%, no statement or type of a definition changed any more. So the proofs near the targets find most of the defects of the definitions, and proving from the top down does not leave the definitions uncertain late in the project.
