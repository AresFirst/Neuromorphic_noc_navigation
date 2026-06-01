from __future__ import annotations


def reconstruct_path_from_parent(
    parent_trace: dict[int, int | None],
    start: int,
    target: int,
) -> list[int]:
    if start == target:
        return [start]
    if target not in parent_trace and target != start:
        raise ValueError(f"target {target} is not present in the parent trace")

    path = [target]
    visited = {target}
    current = target

    while current != start:
        if current not in parent_trace:
            raise ValueError(f"node {current} is not present in the parent trace")
        current = parent_trace[current]
        if current is None:
            raise ValueError(f"Unable to reconstruct a path from {target} back to start {start}")
        if current in visited:
            raise ValueError("Cycle detected while reconstructing path from parent trace")
        visited.add(current)
        path.append(current)

    path.reverse()
    return path
