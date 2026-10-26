# Estándar ejecutable de ingeniería de datos

Un workspace agéntico que lleva una tabla replicada hasta un producto de datos certificado,
siguiendo siempre el mismo estándar: ingesta → staging → transformación → testing →
observabilidad → gobernanza → performance → certificación.

> Estado: en construcción. Este README crece junto con la implementación.

## Requisitos

- Python 3.9 o superior
- Git y `make`

No se necesitan credenciales ni servicios externos: todo corre en local con dbt sobre DuckDB.

## Cómo correrlo

```bash
make setup     # crea .venv e instala dependencias fijadas
make all       # ingiere las entregas y corre dbt build
make test      # pytest de las herramientas
```

## Estructura

| Ruta | Contenido |
|---|---|
| `data/replica/` | Entregas de la réplica CDC, una carpeta por entrega (`carga_1`, `carga_2`, …) |
| `docs/reto/` | Documentación del negocio y del sistema origen que acompaña al reto |
| `dbt/` | Proyecto dbt: landing → staging → silver → gold → mart |
| `src/dp/` | CLI `dp`: las herramientas deterministas que usa el agente |
| `standard/` | Política del estándar como código |
| `tests/` | Pruebas de las herramientas |
