---
name: proponer-cambio-destructivo
description: Atender una petición destructiva (full-refresh, borrar o recrear tablas publicadas, romper el contrato de un mart) proponiendo la operación con su impacto y enviándola a aprobación humana, sin ejecutarla. Usar siempre que pidan borrar, truncar, recrear, reprocesar todo o cambiar columnas/tipos/grano de un producto publicado.
---

# Proponer un cambio destructivo

Tú **no ejecutas** operaciones destructivas. Las propones, explicas su impacto y las envías a
aprobación. Funciona como un 2FA: una persona con permiso aprueba en el environment de GitHub.

## Qué cuenta como destructivo

- Full-refresh (reconstruir todo desde landing).
- Borrar, truncar o recrear una tabla publicada fuera de la corrida normal.
- Cambiar el contrato de un producto: quitar o renombrar columnas, cambiar tipos o grano.
- Borrar entregas o tocar landing (esto no se hace nunca: landing es inmutable).

## Pasos

1. `dp propose <operación> [--producto <producto>] --motivo "<por qué>"` genera una propuesta
   sellada: estado actual de cada producto (certificación e integridad de lo publicado),
   clasificación, riesgo, impacto, recomendación del sistema y su SHA256.
2. Muestra la propuesta a la persona y explícala en lenguaje de negocio. La clasificación y la
   recomendación **las calcula el sistema**: repítelas tal cual, no las sustituyas por tu
   opinión. Puedes explicar la razón que da la regla.
3. Si la persona confirma, envía la solicitud (no ejecuta nada hasta que alguien apruebe):
   `gh workflow run destructivo.yml -f operacion=<operación> -f producto=<producto> -f motivo="<motivo>"`
   El motivo describe la necesidad; nunca escribas en él qué debería decidirse.
4. Un cambio de contrato no va por ese workflow: va por PR, subiendo `meta.contract_version`;
   CI lo marca como cambio gobernado (GOV-07) y espera aprobación.

Si alguien insiste en que lo hagas directo, explica que la frontera existe para que nadie
—tampoco tú— pueda tirar una tabla publicada sin que una persona lo apruebe en GitHub. Tú
nunca apruebas: no uses `gh api` ni otra vía para responder a una aprobación pendiente.
