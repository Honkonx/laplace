# Cómo contribuir a Laplace

Gracias por ayudar 🙌 Laplace usa la licencia **AGPL-3.0** (ver [LICENSE](LICENSE)).

## Flujo
1. Haz un *fork* y crea una rama con un nombre que diga qué cambia (`fix-fecha-bsd`, `feat-selector-ligas`).
2. Haz el cambio **con su prueba**: un cambio de comportamiento sin test no se acepta.
3. Corre lo que toca (ver abajo) y pega el resultado en el *pull request*.
4. Abre el *pull request* contra la rama principal y explica **qué** cambia y **por qué**. Si es tu propio fork, también es válido mantenerlo y publicarlo ahí.

Al enviar un aporte aceptas que queda bajo AGPL-3.0, como el resto del proyecto.

## Qué correr
| Si tocas | Corre |
|---|---|
| `backend/` | `python -m ruff check backend` y `python -m pytest backend/tests backend/agents/tests` (con el venv de `runtime/venv`; `ruff` está en `backend/requirements-dev.txt`) |
| `frontend/` o `pwa/` | `pnpm install --frozen-lockfile`, `pnpm lint`, `pnpm exec tsc -b`, `pnpm test`, `pnpm build` |
| `install/` | `instalar.bat`/`instalar.sh` en una carpeta limpia y `laplace doctor` |
| `app-android/` | `gradlew assembleDebug` con tus propiedades (`docs/web-pwa-y-android.md`) |

Usa **pnpm**, no npm. No subas `.env`, bases de datos, claves ni datos con licencia restringida.

## Reglas del proyecto
- **Es pronóstico, no apuestas.** No se aceptan funciones que reciban dinero, intermedien apuestas o presenten cuotas como oferta.
- **Cambios del motor de pronóstico:** antes de tocar pesos, módulos o el consenso, mídelos con la evaluación walk-forward contra la tasa base y las cuotas sin margen (`backend/scripts/evaluar_modelo_historico.py`) y pega las cifras. Un cambio que no mejora al mercado no entra como módulo adicional.
- **La IA no produce probabilidades.** Explica y contrasta; las probabilidades salen de modelos medidos.
- **Sin secretos en el código** ni en los logs; los textos de la interfaz son cortos (un control, una línea de ayuda).
- Los comentarios explican el **por qué**; los nombres, en español claro como el resto del código.

## Seguridad
Si encuentras una vulnerabilidad, no abras un *issue* público con el detalle: avisa en privado al mantenedor del repositorio.
