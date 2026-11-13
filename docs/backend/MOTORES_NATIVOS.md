# Rust, Go y Python en Laplace

Decisión de diseño (2026-11-12): se usan los tres, cada uno en lo suyo.

| Lenguaje | Papel | Dónde |
|---|---|---|
| **Rust** | Cálculo caliente: el Monte Carlo del simulador de temporadas (el mejor rendimiento) | `modelo/rust/lsim` |
| **Go** | Microservicios y conexión: el servicio local del simulador (`simd`) y el núcleo `lsim` como respaldo del cálculo | `modelo/go/simd`, `modelo/go/lsim` |
| **Python** | Lógica: datos, entrenamiento, evaluación, API, bots, agente; es la referencia y el último respaldo | `backend/` |

## Cadena de cálculo
`Rust → Go → Python`, la primera que esté disponible. Con filtros (funciones de Python) siempre Python. La respuesta declara el motor que **de verdad** corrió (`motor`: `rust`, `go` o `python`), no el pedido.

```
backend (Python) → [simd (Go): cupo y plazo] → núcleo Rust ─┐
                 └→ núcleo Rust directo ────────────────────┤ si falla →  núcleo Go → Python
```

## Medido (20 equipos, 190 pendientes, 20.000 simulaciones, `python backend/scripts/medir_motores.py`)
| Motor | Mediana | Frente a Python |
|---|---:|---:|
| Python | 4,43 s | 1× |
| Go | 0,28 s | 15,6× |
| Rust | 0,14 s | 30,7× |

Las diferencias de probabilidad de posición frente a Python fueron ≤ 0,0084 con un error Monte Carlo esperado de 0,025: son estadísticamente equivalentes (no idénticos bit a bit: cada uno usa su generador aleatorio). Rust reparte las simulaciones en 16 bloques fijos, así que la misma semilla da el mismo resultado en cualquier máquina.

## Servicio local `simd` (Go)
- Escucha solo en `127.0.0.1:9200` (se niega a otra interfaz); `GET /health`, `POST /v1/simular` con el mismo JSON del núcleo.
- Tope de 2 simulaciones a la vez (la tercera recibe 503 con `Retry-After`) y plazo de 20 s que **mata el proceso del cálculo** (un hilo de Python no se puede detener). Una desconexión de quien llamó también lo cancela.
- `laplace.py` lo enciende solo si existen `simd` y el núcleo de Rust, y pasa `LAPLACE_SIMD_URL` al backend; si está apagado, el backend usa el binario directamente.

## Cómo se compila
```
python backend/scripts/construir_rust.py --probar   # cargo test + build --release → modelo/rust/bin/lsim
python backend/scripts/construir_go.py --probar     # go test + build → modelo/go/bin/lsim y simd
```
Rust: https://rustup.rs (el script también busca `~/.cargo/bin`). Los binarios no se versionan ni se publican.

## Variables
`LAPLACE_MOTOR_SIM=python` apaga todos los núcleos nativos; `LAPLACE_RUST_LSIM`, `LAPLACE_GO_LSIM` (rutas); `LAPLACE_SIMD_URL` (solo loopback), `LAPLACE_PUERTO_SIMULADOR` (9200), y para el servicio `LAPLACE_SIMD_MAX` y `LAPLACE_SIMD_PLAZO`.

## Qué NO se movió a Rust ni a Go
El entrenamiento y la inferencia del 1X2 siguen en Python (0,6 ms por pronóstico: no hay cuello). Pasar algo a otro lenguaje exige medir antes la equivalencia y la ganancia (`evidencia-historica-antes-de-promover.md`).
