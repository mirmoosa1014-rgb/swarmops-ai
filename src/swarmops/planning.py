"""Bounded grid search. Prioritized reservation planning is incomplete."""
from heapq import heappop, heappush

Cell = tuple[int, int]


def neighbors(cell: Cell):
    x, y = cell
    return ((x, y - 1), (x - 1, y), (x + 1, y), (x, y + 1))


def distance(a: Cell, b: Cell) -> int:
    return abs(a[0] - b[0]) + abs(a[1] - b[1])


def astar(start: Cell, goal: Cell, free: set[Cell]) -> list[Cell] | None:
    if start not in free or goal not in free:
        return None
    heap = [(distance(start, goal), 0, start)]
    costs = {start: 0}
    parent = {}
    while heap:
        _, cost, cell = heappop(heap)
        if cost != costs[cell]:
            continue
        if cell == goal:
            path = [cell]
            while path[-1] != start:
                path.append(parent[path[-1]])
            return path[::-1]
        for nxt in neighbors(cell):
            new = cost + 1
            if nxt in free and new < costs.get(nxt, float("inf")):
                costs[nxt] = new
                parent[nxt] = cell
                heappush(heap, (new + distance(nxt, goal), new, nxt))
    return None


def space_time(start: Cell, goal: Cell, free: set[Cell], vertices: set,
               edges: set, horizon: int, max_expansions: int = 20000) -> list[Cell] | None:
    """Return a horizon-length safe prefix; reaching the goal is not guaranteed.

    Vertex/edge times are relative to the current tick. A goal is accepted only
    if it can remain occupied through the horizon. Otherwise take the best safe
    frontier, preferring less distance and then fewer movements.
    """
    if start not in free or goal not in free:
        return None
    queue = [(0, 0, 0, start)]
    parent = {(start, 0): None}
    costs = {(start, 0): (0, 0)}
    frontier = []
    expansions = 0
    while queue and expansions < max_expansions:
        time, total_distance, movements, cell = heappop(queue)
        if costs[(cell, time)] != (total_distance, movements):
            continue
        expansions += 1
        if cell == goal and all((cell, t) not in vertices for t in range(time + 1, horizon + 1)):
            end = (cell, time)
            break
        if time == horizon:
            frontier.append((distance(cell, goal), total_distance, movements, cell, time))
            continue
        for nxt in (*neighbors(cell), cell):
            key = (nxt, time + 1)
            if (nxt not in free or (nxt, time + 1) in vertices
                    or (nxt, cell, time + 1) in edges):
                continue
            cost = (total_distance + distance(nxt, goal), movements + int(nxt != cell))
            if key in costs and costs[key] <= cost:
                continue
            parent[key] = (cell, time)
            costs[key] = cost
            heappush(queue, (time + 1, *cost, nxt))
    else:
        if not frontier:
            return None
        *_, cell, time = min(frontier)
        end = (cell, time)
    path = []
    while end is not None:
        path.append(end[0])
        end = parent[end]
    path.reverse()
    return path + [path[-1]] * (horizon + 1 - len(path))
