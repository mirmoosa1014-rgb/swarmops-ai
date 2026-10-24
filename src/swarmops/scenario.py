"""Versioned, bounded scenarios with exogenous schedules generated up front."""
from dataclasses import asdict, dataclass
import json
import random
from .planning import Cell, astar


@dataclass(frozen=True)
class OrderSpec:
    id: str
    release: int
    pickup: Cell
    delivery: Cell


@dataclass(frozen=True)
class ClosureSpec:
    cell: Cell
    requested: int
    duration: int


@dataclass(frozen=True)
class Scenario:
    width: int
    height: int
    walls: tuple[Cell, ...]
    parking: tuple[Cell, ...]
    orders: tuple[OrderSpec, ...]
    closures: tuple[ClosureSpec, ...] = ()
    pauses: tuple[tuple[int, int, int], ...] = ()  # robot index, start, duration
    seed: int = 0
    horizon: int = 300
    service_ticks: int = 2
    planning_horizon: int = 12
    version: int = 1

    @property
    def free(self):
        return {(x, y) for y in range(self.height) for x in range(self.width)} - set(self.walls)

    def validate(self):
        for value, lo, hi in ((self.width, 3, 40), (self.height, 3, 40),
                              (self.horizon, 1, 10000), (self.service_ticks, 1, 100),
                              (self.planning_horizon, 1, 40)):
            if type(value) is not int or not lo <= value <= hi:
                raise ValueError("Scenario integer outside supported bounds")
        if self.version != 1 or type(self.seed) is not int:
            raise ValueError("Unsupported version or seed")
        cells = (*self.walls, *self.parking, *(o.pickup for o in self.orders),
                 *(o.delivery for o in self.orders), *(c.cell for c in self.closures))
        if any(len(c) != 2 or any(type(n) is not int for n in c)
               or not (0 <= c[0] < self.width and 0 <= c[1] < self.height) for c in cells):
            raise ValueError("Invalid grid coordinate")
        if not 1 <= len(self.parking) <= 12 or len(set(self.parking)) != len(self.parking):
            raise ValueError("Need 1–12 distinct robot parking cells")
        if len(self.orders) > 5000 or len(self.closures) > 100 or len(self.pauses) > 100:
            raise ValueError("Schedule too large")
        if len({o.id for o in self.orders}) != len(self.orders):
            raise ValueError("Duplicate order IDs")
        free = self.free
        if any(p not in free for p in self.parking):
            raise ValueError("Parking is blocked")
        for o in self.orders:
            if (not isinstance(o.id, str) or not 1 <= len(o.id) <= 80
                    or type(o.release) is not int or not 0 <= o.release < self.horizon
                    or o.pickup not in free or o.delivery not in free):
                raise ValueError("Invalid order")
        for c in self.closures:
            if (c.cell not in free or type(c.requested) is not int or not 0 <= c.requested < self.horizon
                    or type(c.duration) is not int or not 1 <= c.duration <= self.horizon):
                raise ValueError("Invalid closure")
        for robot, start, duration in self.pauses:
            if (any(type(n) is not int for n in (robot, start, duration))
                    or not 0 <= robot < len(self.parking) or not 0 <= start < self.horizon
                    or not 1 <= duration <= self.horizon):
                raise ValueError("Invalid pause")
        return self

    def to_json(self):
        return json.dumps(asdict(self), sort_keys=True, indent=2)

    @classmethod
    def from_json(cls, text):
        if len(text.encode()) > 2_000_000:
            raise ValueError("Scenario exceeds 2 MB")
        try:
            data = json.loads(text)
            for key in ("walls", "parking", "pauses"):
                data[key] = tuple(tuple(c) for c in data.get(key, []))
            data["orders"] = tuple(OrderSpec(**{**o, "pickup": tuple(o["pickup"]),
                                                "delivery": tuple(o["delivery"])}) for o in data["orders"])
            data["closures"] = tuple(ClosureSpec(**{**c, "cell": tuple(c["cell"])})
                                     for c in data.get("closures", []))
            return cls(**data).validate()
        except (TypeError, KeyError, IndexError, AttributeError, json.JSONDecodeError) as exc:
            raise ValueError("Malformed scenario") from exc


def preset(seed=7, robots=4, order_count=24, horizon=300, layout="small"):
    if layout not in ("small", "medium", "bottleneck"):
        raise ValueError("Unknown preset")
    rng = random.Random(seed)
    width, height = (21, 15) if layout == "medium" else (13, 9)
    walls = (tuple((width // 2, y) for y in range(height) if y != height // 2)
             if layout == "bottleneck" else
             tuple((x, y) for x in range(3, width - 2, 3) for y in range(2, height - 2)))
    stations = [(1, 1), (width - 2, 1), (1, height - 2), (width - 2, height - 2),
                (4, 1), (width - 5, height - 2)]
    orders = tuple(OrderSpec(f"job-{i:04d}", min(i * 4, horizon - 1),
                            *rng.sample(stations, 2)) for i in range(order_count))
    parking = tuple((x, height - 1) for x in range(width) if (x, height - 1) not in walls)[:robots]
    if len(parking) != robots:
        raise ValueError("Too many robots")
    return Scenario(width, height, walls, parking, orders,
                    (ClosureSpec((5, 1), 35, 20),), ((0, 65, 5),), seed, horizon).validate()
