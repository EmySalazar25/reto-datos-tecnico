@AGENTS.md

## Solo para Claude Code

`AGENTS.md` es la única fuente del estándar; este archivo solo lo importa. Claude Code no carga
`.agents/skills/` como skills: cuando `AGENTS.md` te mande a una skill, lee su receta antes de
actuar, en `.agents/skills/<nombre>/SKILL.md`.
