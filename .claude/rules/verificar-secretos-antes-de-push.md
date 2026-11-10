# Verificar que no haya tokens/API keys reales antes de cualquier commit que se vaya a pushear

> Creada 2026-09-10, orden explícita del usuario tras un hallazgo real: un token real de GitHub
> (`ghp_...`) quedó hardcodeado en `infra/scripts/sync_kairosapp.sh` desde el primer commit de
> este repo (`3b17ad3`) — nunca se había pusheado a ningún remoto hasta esa ronda, así que el
> daño real fue evitado, pero solo porque el repo no tenía remote todavía, no porque hubiera un
> chequeo real. Purgado del historial con `git-filter-repo` antes del primer push. El usuario
> pidió agregar esta regla explícitamente: "añade como regla que siempre se debe verificar que
> no haya token o api de github en un commi push".

## Regla

Antes de cualquier `git push` (no solo el primero) — y en particular antes de crear un repo
remoto nuevo o de pushear a uno por primera vez — escanear los archivos que se van a subir en
busca de credenciales reales en texto plano, no solo confiar en `.gitignore`:

```bash
# Patrones reales de tokens/keys más comunes — correr contra los archivos STAGED, no el repo
# completo (sería lento en repos grandes; lo que importa es lo que se está por commitear/pushear)
git diff --cached | grep -nE "ghp_[A-Za-z0-9]{36}|gho_[A-Za-z0-9]{36}|github_pat_[A-Za-z0-9_]{22,}|sk-[A-Za-z0-9]{20,}|AIzaSy[A-Za-z0-9_-]{33}|xox[baprs]-[A-Za-z0-9-]{10,}"
```

Si algo matchea, **no es automáticamente un falso positivo por estar en un script/doc "viejo"** —
confirmar si es un secreto real (probarlo, o simplemente tratarlo como real si hay duda) antes de
pushear. Un secreto real encontrado en un archivo que TODAVÍA no se pusheó nunca (como este caso)
es la situación de menor costo para arreglar — se puede limpiar del historial completo sin romper
ningún clone/colaborador externo, porque no existen todavía. Una vez que algo se pusheó al menos
una vez a un remoto real, limpiar el historial es mucho más caro (invalida cualquier clone
existente) — motivo de más para chequear ANTES del primer push, no después.

## Cómo aplicarla en la práctica

- Antes de crear un repo remoto nuevo y hacer el primer push de un repo que ya tiene historial
  local (como pasó acá — el repo llevaba commits desde semanas antes de tener un remote): correr
  el grep de arriba contra `git log -p --all` (todo el historial, no solo lo staged) al menos
  una vez, porque ahí es donde puede estar escondido un secreto viejo que nadie miró de nuevo.
- Si se encuentra un secreto real en historial que nunca se pusheó: usar `git-filter-repo`
  (`pip install git-filter-repo`) con `--replace-text` apuntando solo al secreto exacto (no
  borrar el archivo completo del historial si tiene contenido real más allá del secreto) —
  siempre hacer un `git bundle create <ruta>.bundle --all` de respaldo antes de correrlo (una
  reescritura de historial es una operación destructiva real, ver `.claude/rules/global-rules.md`
  sobre operaciones irreversibles).
- Si el secreto YA se pusheó alguna vez (a cualquier remoto, aunque sea privado): limpiar el
  historial no alcanza — el valor real debe rotarse/revocarse en el servicio que lo emitió (esto
  el usuario lo hace directo, nunca asumir que reescribir el historial local "arregla" un
  secreto que ya viajó a un servidor externo).
- Esta regla no reemplaza `.claude/rules/secrets-never-revealed.md` (esa es sobre nunca REVELAR
  un secreto ya guardado desde una UI/endpoint) — son complementarias: esta es sobre nunca dejar
  que un secreto real llegue a un commit pusheado en primer lugar.
