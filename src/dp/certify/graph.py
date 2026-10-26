"""Lectura del manifest de dbt: productos, linaje y tests que protegen a cada producto.

No hay grafo propio: `parent_map`, `child_map` y `depends_on` del manifest son el grafo.
"""

from __future__ import annotations

from dataclasses import dataclass, field

PASS_STATUSES = {"pass", "success"}
FAIL_STATUSES = {"fail", "error", "runtime error"}


@dataclass
class TestNode:
    unique_id: str
    name: str
    kind: str  # technical | engineering | business | unit
    rule: str | None
    severity: str
    depends_on: list
    attached_node: str | None
    generic_name: str | None
    kwargs: dict = field(default_factory=dict)


@dataclass
class Product:
    unique_id: str
    name: str
    node: dict
    meta: dict
    group: str | None
    owner: str | None
    closure: set  # nodos upstream (modelos y fuentes), sin el producto


def _tags(node: dict) -> set:
    return set(node.get("tags") or []) | set((node.get("config") or {}).get("tags") or [])


def classify(node: dict) -> str:
    if node.get("resource_type") == "unit_test":
        return "unit"
    tags = _tags(node)
    if "business" in tags:
        return "business"
    if "engineering" in tags:
        return "engineering"
    return "technical"


class Graph:
    def __init__(self, manifest: dict):
        self.manifest = manifest
        self.nodes = manifest.get("nodes", {})
        self.sources = manifest.get("sources", {})
        self.parent_map = manifest.get("parent_map", {})
        self.child_map = manifest.get("child_map", {})
        self.groups = {g["name"]: g for g in manifest.get("groups", {}).values()}
        self.exposures = manifest.get("exposures", {})
        self.tests = self._load_tests()

    def _load_tests(self) -> list:
        tests = []
        all_nodes = list(self.nodes.values()) + list(self.manifest.get("unit_tests", {}).values())
        for n in all_nodes:
            if n.get("resource_type") not in ("test", "unit_test"):
                continue
            cfg = n.get("config") or {}
            meta = {**(n.get("meta") or {}), **(cfg.get("meta") or {})}
            tm = n.get("test_metadata") or {}
            tests.append(
                TestNode(
                    unique_id=n["unique_id"],
                    name=n["name"],
                    kind=classify(n),
                    rule=meta.get("rule"),
                    severity=str(cfg.get("severity") or "ERROR").lower(),
                    depends_on=list((n.get("depends_on") or {}).get("nodes") or []),
                    attached_node=n.get("attached_node"),
                    generic_name=tm.get("name"),
                    kwargs=tm.get("kwargs") or {},
                )
            )
        return tests

    def upstream(self, unique_id: str) -> set:
        seen, stack = set(), list(self.parent_map.get(unique_id, []))
        while stack:
            uid = stack.pop()
            if uid in seen:
                continue
            seen.add(uid)
            stack.extend(self.parent_map.get(uid, []))
        return {u for u in seen if u.startswith(("model.", "source.", "seed.", "snapshot."))}

    def products(self) -> list:
        products = []
        for uid, n in sorted(self.nodes.items()):
            if n.get("resource_type") != "model" or n.get("access") != "public":
                continue
            group = n.get("group")
            owner = None
            if group and group in self.groups:
                o = self.groups[group].get("owner") or {}
                owner = o.get("name") or o.get("email")
            products.append(
                Product(
                    unique_id=uid,
                    name=n["name"],
                    node=n,
                    meta=n.get("meta") or {},
                    group=group,
                    owner=owner,
                    closure=self.upstream(uid),
                )
            )
        return products

    def tests_for(self, product: Product) -> list:
        """Tests que protegen al producto: todo lo que prueban está en su linaje.

        Un test de negocio cuenta solo si su regla es una regla declarada del producto.
        """
        scope = product.closure | {product.unique_id}
        rules = {r.get("id") for r in product.meta.get("business_rules") or []}
        selected = []
        for t in self.tests:
            deps = set(t.depends_on)
            if not deps or not deps <= scope:
                continue
            if t.kind == "business" and t.rule not in rules:
                continue
            if t.kind == "unit" and t.rule and t.rule not in rules:
                continue
            selected.append(t)
        return selected

    def exposures_for(self, product: Product) -> list:
        return sorted(
            uid for uid, e in self.exposures.items() if product.unique_id in ((e.get("depends_on") or {}).get("nodes") or [])
        )
