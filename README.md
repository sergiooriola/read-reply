# read-reply

Lee en voz alta la última respuesta del agente de programación del panel activo de Herdr. Pulsas F9 y la oyes con Álvaro, la voz natural de Edge en español de España; vuelves a pulsar F9 y se calla. Nunca lee nada por su cuenta.

Funciona con Claude Code y Codex dentro de [Herdr](https://herdr.dev), en WSL sobre Windows.

## Requisitos

- Windows con WSL 2, y Herdr 0.9.5 o posterior dentro de WSL.
- Microsoft Edge en Windows, que viene con el sistema.
- En WSL: [uv](https://docs.astral.sh/uv/) y [pandoc](https://pandoc.org).
- Internet para la voz de Álvaro. Si Álvaro falla, la lectura sigue con una voz local de Windows, como Pablo; sin conexión no está probado.

## Instalación

```bash
uv tool install ~/dev/read-reply
```

El comando `read-reply` queda en `~/.local/bin`. Después, el atajo en `~/.config/herdr/config.toml`:

```toml
[[keys.command]]
key = "f9"
type = "shell"
command = "read-reply"
description = "Leer en voz alta la última respuesta del agente (otra vez: parar)"
```

y `herdr server reload-config` para cargarlo. Para instalar una versión nueva del código: `uv tool install --reinstall ~/dev/read-reply`.

## Uso

- **F9** lee la última respuesta terminada del agente del panel activo. Si el agente está trabajando, lee la anterior.
- **F9 otra vez**, mientras lee, la corta.
- Los errores, como un panel sin agente, salen como notificación de Herdr, que llega a Windows si Herdr tiene `[ui.toast] delivery = "system"`.
- `read-reply --pane w1:p2 --print` escribe el texto tal como lo leería, sin leerlo. Sirve para revisar cómo queda una respuesta.

## Cómo funciona

1. Herdr pasa a sus atajos el panel activo en `HERDR_ACTIVE_PANE_ID`, y `herdr agent get` dice qué agente hay en él y cuál es su sesión (`herdr.py`).
2. La respuesta sale de la transcripción de esa sesión, que se lee desde el final porque alguna pasa de 600 MB (`transcripts.py`):
   - Claude Code: el último mensaje que cerró un turno, en `~/.claude/projects/` (o bajo `CLAUDE_CONFIG_DIR`).
   - Codex: el último mensaje de su última tarea terminada, en `~/.codex/sessions/` (o bajo `CODEX_HOME`).
3. pandoc convierte el Markdown en párrafos para el oído: sin marcas, con los bloques de código anunciados en vez de deletreados, las tablas fila a fila y los enlaces por su texto (`speech_text.py`).
4. Edge, sin ventana, los lee con la Web Speech API estándar, que en Edge incluye las voces naturales de Microsoft. Un servidor HTTP efímero en `127.0.0.1` le pasa a la página el texto y la orden de parar. La página se cierra al acabar, y Edge con ella. Si una voz online falla, repite el fragmento con una local y sigue con ella (`player.py`, `player.html`).
5. Una segunda pulsación encuentra ocupado el bloqueo de la lectura en curso y le pide que pare (`cli.py`).

Deja dos cosas fuera del repositorio: un perfil propio de Edge en `%LOCALAPPDATA%\read-reply\edge-profile`, de unos 16 MB y aparte del tuyo, y el bloqueo en `$XDG_RUNTIME_DIR/read-reply/`.

### Por qué así

- **La voz de Edge:** es la voz masculina en español de España más realista que se puede usar gratis y sin cuenta. Azure Speech da las mismas voces con API oficial, pero su plan gratuito (500.000 caracteres al mes) se queda corto. `edge-tts` usa el servicio interno de Edge, y Microsoft lo rompió a propósito en octubre de 2026.
- **pandoc:** un analizador de Markdown de verdad, en vez de expresiones regulares.
- **Solo la biblioteca estándar de Python:** no hay dependencias que instalar ni que vigilar.

## Límites

- Antigravity (`agy`) no está soportado: guarda sus conversaciones en bloques binarios de SQLite.
- Las rutas y el código dentro de una frase se leen tal cual.
- Depende de que Edge siga ofreciendo sus voces online a las páginas web.

## Desarrollo

```bash
uv sync
git config core.hooksPath .githooks   # una vez por copia del repositorio
scripts/check                         # formato, lint, tipos y pruebas
```

No hay CI, para no gastar minutos de GitHub Actions, que están desactivadas en el repositorio. En su lugar, el hook `pre-push` lanza `scripts/check` antes de cada push y lo rechaza si falla o si hay cambios sin commit. Las pruebas necesitan pandoc.

`uv` solo instala versiones publicadas hace al menos dos semanas (`exclude-newer` en `pyproject.toml`): una versión maliciosa suele detectarse y retirarse en días.

### Probar que suena

Las pruebas no llegan a Edge, que solo corre en Windows. Para comprobar que una lectura se oye, mide el nivel de la salida de audio de Windows mientras lee:

```bash
powershell.exe -ExecutionPolicy Bypass -File "$(wslpath -w scripts/audio-meter.ps1)" -Seconds 20 &
uv run read-reply --pane <panel>
```

En silencio, el pico ronda 0,001. Mientras Álvaro habla, sube por encima de 0,1.
