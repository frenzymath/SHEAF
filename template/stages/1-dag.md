# Stage 1: the natural-language DAG

**Produces:** `dag/nodes/`, a DAG of definitions and statements with complete natural-language proofs, from the targets down to results in Mathlib. No Lean is written.

## 1. Nodes

A node is one definition or one statement, in one JSON file, in any layout. It records:

- an id, never reused;
- whether it is a definition, a statement or a target;
- the statement in words and where it comes from;
- the nodes needed to state it (statement dependencies);
- for a statement that is not in Mathlib, a complete proof in steps, each step naming the nodes it uses (proof dependencies) or marked elementary;
- whether the proof follows a document, with the document and the place, or was written by an agent;
- the Mathlib searches made, with tool, query, results and date, and the Mathlib match if there is one;
- a history of every replaced value and removed dependency, with date and reason.

Nodes are never deleted. Two nodes that state the same thing are merged: one is marked as merged into the other, and its users point to the other.

## 2. Who does what

An item of this stage is a node that is not split yet.

- The **maintainer** keeps the queue: the nodes that are neither Mathlib leaves nor split, nearest to a target first. If `SETUP.md` asks for an early review of the target statements, the nodes needed to state the targets come before all others. It starts with the targets. There is no Lean to build in this stage; in each cycle the maintainer brings the queue up to date, checks the new nodes against §6, and commits.
- A **lead** claims nodes and gives each to a worker.
- A **worker** splits its node by one level (§3) and writes the nodes directly into `dag/nodes/`. It changes no node that is not its own; what it finds wrong in another node goes into its report.
- The lead reviews the node: the proof follows its source, every step names what it uses, every new node was searched in Mathlib, and no new node repeats an existing one.

## 3. Splitting

1. For a target, start from the statement and proof in the paper.
2. Write the proof of the node in steps (§4), and name for every step the definitions and results it uses.
3. For each of these, look for an existing node with the same statement, the same place in the literature or the same Mathlib match, and point to it. If there is none, create a node.
4. Search Mathlib for every new node. If Mathlib has it for the same kind of object, or has a generalization that specializes in one line, record the match: the node is a leaf. Otherwise record the search, and the node joins the queue.

The stage goes on until every branch ends in a Mathlib leaf. The graph stays acyclic.

## 4. Proofs and the literature

- Download every document a proof relies on into `literature/` and list it in `literature/LIST.md`: the paper, what it cites for a step, and the references for the textbook results the DAG splits.
- A proof follows its source exactly and cites the document and the place. It is not written from memory.
- A reference is not a proof: the steps go into the node. Where the source omits a step or calls it obvious or standard, write the step out.
- A proof written by a human is preferred to one written by an agent. When you cannot obtain a document, add it to the wanted documents in `literature/LIST.md`, so that the human is asked for it. Until it arrives, write the proof yourself and mark the node as written by an agent. When it arrives, rewrite the proof from it and remove the mark.

## 5. After this stage

The DAG keeps changing while statements and proofs are formalized. Nodes are added and revised under the same rules. A node is updated from Lean twice: when its statement is formalized, with the module, the declaration and the Lean statement; when its proof is done, with the proof dependencies the Lean proof uses.

## 6. Finished when

- every target has a node, and every branch of statement and proof dependencies ends in a Mathlib leaf;
- every other statement has a complete proof, and every step of it names the nodes it uses or is marked elementary;
- the graph is acyclic, and no node points to a missing or merged node.
