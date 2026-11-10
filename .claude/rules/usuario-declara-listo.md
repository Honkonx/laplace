# "Listo" lo dice el usuario, no la IA: se reportan hechos observables

> Creada 2026-10-19. Adaptada de `usuario-declara-listo.md` (PAGINA1). Refuerza `empirical-verification-before-fix.md`
> y `subagentes-maximo-tres-y-yo-verifico.md`.

La IA no afirma que algo está "perfecto", "terminado" o "funciona correctamente". Reporta el estado observable y
**nombra el peldaño** alcanzado:

*escrito* → *compila / arranca* → *tests en verde* → *verificado contra datos o APIs reales* → *en uso real sin problemas*.

| En vez de | Decir |
|---|---|
| "quedó perfecto" | "1.147 tests pasan; con 4 días de calendario real la cobertura histórica subió de 13,5 % a 15,6 %" |
| "ya funciona" | "el diagnóstico en vivo devolvió pick y etiqueta para 10 de 11 partidos; el 11º cayó en 'sin pronóstico' con su motivo" |
| "sin errores" | "pytest y py_compile no reportan errores; no probé el flujo de Telegram de punta a punta (falta el token)" |

Siempre se dice **lo que NO se probó**, con el motivo. Un porcentaje sin decir contra qué se mide no dice nada. Si una
verificación falla se muestra su salida; si un paso se saltó, se dice. Lo que afirma un subagente es una afirmación,
no un hecho, hasta que se contrasta (ver `subagentes-maximo-tres-y-yo-verifico.md`).
