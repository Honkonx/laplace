# Se separa lo confirmado de lo supuesto: nunca se mezclan con el mismo peso

> Creada 2026-10-19. Adaptada de `never-assume-state-uncertainty.md` (kairos) y `no-asumir-solo-por-documentacion.md`
> (PAGINA1). Complementa `no-asumir-preguntar-si-ambiguo.md` y `investigacion-documentada.md`.

Una conclusión, un estado del sistema o un "probablemente es la causa" se presenta como hecho solo si hay:
1. evidencia directa (salida de un comando ejecutado, una consulta a la BD real, una línea de código que lo demuestra
   sin ambigüedad), **o**
2. la palabra explícita del usuario sobre el estado real de su sistema.

En cualquier otro caso se rotula: **confirmado**, **inferido** o **sin evidencia**. Un informe de auditoría
estática dice "esto es una auditoría de código sin ejecución real: los siguientes son sospechosos, no confirmaciones".

Ejemplos de este repo (2026-10-09/19): la hipótesis "el menú ofrece ligas sin cobertura" se rotuló inferida (no había
trazas de las 10 pruebas del usuario) hasta medir 101/946 partidos cubiertos; "el bug de la fecha en BSD" resultó ya
corregido en HEAD al releer el archivo; "el límite de la API es de 100 por día" era incompleto: había un límite de
10 por minuto y un acceso por temporada que solo se vio al leer los `errors` de la respuesta real.

La documentación da contexto; **el código da la verdad**. Antes de citar un archivo o una cifra, se lee o se mide de
nuevo en esta ronda.
