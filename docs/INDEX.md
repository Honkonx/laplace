# Documentación de Laplace

## Guías
| Documento | Para qué |
|---|---|
| [../guia.md](../guia.md) | **Empieza aquí:** clonar, instalar, configurar, iniciar, usar y actualizar |
| [../requisitos.md](../requisitos.md) | Qué necesitas: equipo, programas, puertos, cuentas y claves |
| [instalacion.md](instalacion.md) | Instalar, encender, apagar y revisar Laplace en Windows, Linux, macOS y WSL |
| [configuracion.md](configuracion.md) | El archivo `.env`: qué clave habilita qué |
| [motor-de-pronostico.md](motor-de-pronostico.md) | Cómo se calcula un pronóstico, niveles de evidencia y cómo se mide |
| [telegram-y-agente.md](telegram-y-agente.md) | Comandos del bot y del agente |
| [web-pwa-y-android.md](web-pwa-y-android.md) | Compilar y configurar la web, la PWA y la app Android |
| [seguridad-y-datos.md](seguridad-y-datos.md) | Secretos, licencias de datos de terceros y límites del producto |

## Referencia técnica
| Carpeta | Qué hay |
|---|---|
| [arquitectura/](arquitectura/INDEX.md) | Visión general (procesos, carpetas, datos, autenticación), estado del bot y el agente, mapa del proyecto, laboratorio de pronósticos y contrato app ↔ backend |
| [backend/](backend/INDEX.md) | Proveedores de IA, laboratorio en operación y las referencias **generadas del código**: API, base de datos, scripts y trabajos programados |
| [agente/](agente/INDEX.md) | Runtime, control plane, herramientas, memoria, Telegram y flujo deportivo del agente |
| [app/](app/INDEX.md) | La app Android |
| [web/](web/INDEX.md) | La web y la PWA |
| [deploy/](deploy/INDEX.md) | La instalación portable |

Las referencias de `backend/referencia/` se generan con `python backend/scripts/generar_referencia_docs.py` y una prueba falla si quedan desactualizadas. Para contribuir: [../CONTRIBUTING.md](../CONTRIBUTING.md). Seguridad: [../SECURITY.md](../SECURITY.md). Licencia: [../LICENSE](../LICENSE).
