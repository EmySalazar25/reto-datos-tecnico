"""Fuentes declaradas en el YAML de dbt.

El YAML de dbt es la única fuente de verdad: la ingesta solo acepta archivos de tablas
declaradas ahí y usa sus columnas y su llave primaria. No existe una lista paralela.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass(frozen=True)
class SourceTable:
    schema: str
    name: str
    columns: tuple
    primary_key: tuple
    yaml_path: str = field(default="", compare=False)

    @property
    def fqn(self) -> str:
        return f"{self.schema}.{self.name}"


def _meta(node: dict) -> dict:
    config = node.get("config") or {}
    return {**(node.get("meta") or {}), **(config.get("meta") or {})}


def load_declared_sources(dbt_dir: Path) -> dict:
    """Devuelve {nombre_de_tabla: SourceTable}. El nombre de tabla debe ser único entre fuentes."""
    tables: dict = {}
    for yml in sorted((dbt_dir / "models").rglob("*.yml")):
        doc = yaml.safe_load(yml.read_text(encoding="utf-8")) or {}
        for src in doc.get("sources") or []:
            schema = src.get("schema") or src["name"]
            for t in src.get("tables") or []:
                if t["name"] in tables:
                    raise ValueError(f"tabla fuente duplicada: {t['name']} ({yml})")
                pk = _meta(t).get("primary_key")
                if not pk:
                    raise ValueError(f"{schema}.{t['name']} no declara meta.primary_key ({yml})")
                tables[t["name"]] = SourceTable(
                    schema=schema,
                    name=t["name"],
                    columns=tuple(c["name"] for c in t.get("columns") or []),
                    primary_key=tuple(pk),
                    yaml_path=str(yml.relative_to(dbt_dir.parent)),
                )
    return tables
