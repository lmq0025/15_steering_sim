from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SignalLink:
    source: str
    source_port: str
    target: str
    target_port: str
    modulated_element: str
    level: int
    parent_supercomponent: str


@dataclass(frozen=True, slots=True)
class SignalGraph:
    links: tuple[SignalLink, ...]
    topological_order: tuple[str, ...]
    cyclic_nodes: tuple[str, ...]

    @classmethod
    def build(cls, rows: list[dict[str, str]]) -> "SignalGraph":
        links = tuple(
            SignalLink(row["source"], row["source_port"], row["target"], row["target_port"],
                       row["modulated_element"], int(row["level"]), row["parent_supercomponent"])
            for row in rows
        )
        adjacency: dict[str, set[str]] = defaultdict(set)
        indegree: dict[str, int] = {}
        for link in links:
            indegree.setdefault(link.source, 0)
            indegree.setdefault(link.target, 0)
            if link.target not in adjacency[link.source]:
                adjacency[link.source].add(link.target)
                indegree[link.target] += 1
        queue = deque(sorted(node for node, degree in indegree.items() if degree == 0))
        order: list[str] = []
        while queue:
            node = queue.popleft()
            order.append(node)
            for target in sorted(adjacency[node]):
                indegree[target] -= 1
                if indegree[target] == 0:
                    queue.append(target)
        cyclic = tuple(sorted(node for node, degree in indegree.items() if degree))
        return cls(links, tuple(order), cyclic)

    def modulation_targets(self) -> set[str]:
        return {link.modulated_element for link in self.links if link.modulated_element}

    def cycles_are_explicit_static_sc1(self) -> bool:
        """The frozen IR contains feedback-shaped SC_1 signal wiring.

        With spooldyn=1 these are algebraic mappings, not hidden ODE states.
        They are accepted only when every cyclic node belongs to one of the
        explicitly named SC_1 parents carried by the link metadata.
        """
        parents = {link.parent_supercomponent for link in self.links if link.parent_supercomponent}
        return all(any(node.startswith(parent + ".") for parent in parents) for node in self.cyclic_nodes)
