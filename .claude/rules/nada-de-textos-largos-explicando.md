# Nada de textos largos explicando en la pantalla

> Creada 2026-10-19. Adaptada de `nada-de-textos-largos-explicando.md` (PAGINA1). Aplica a `frontend/`, `pwa/`,
> `app-android/` y a los mensajes de los bots de Telegram.

**Si la pantalla necesita un párrafo para explicarse, está mal diseñada.** Se arregla la pantalla, no se agrega el
párrafo. Un texto de ayuda solo sirve si dice algo que el control no puede decir solo.

| Qué | Dónde |
|---|---|
| Para qué sirve el control | en su etiqueta |
| Qué pasa si se aprieta | en el propio botón ("Analizar este partido", no "Enviar") |
| Por qué está deshabilitado | en una frase corta (`title` / `contentDescription`) |
| Un dato extra | debajo, **en una línea** |
| El porqué de una decisión | en el comentario del código |
| La explicación larga | en `docs/` |

**Tope: una línea de ayuda por control, y corta.** Si no entra en una línea, lo que hay que cambiar es el control.

Vale también para los mensajes de Telegram: el mensaje de "sin pronóstico propio" tiene un máximo de 3 motivos, una
línea de referencia y una de qué lo habilitaría. Y para los mensajes de error: uno que no se lee de un vistazo no avisa.

No dice escribir menos en el código: los comentarios que explican **por qué** siguen siendo obligatorios.
