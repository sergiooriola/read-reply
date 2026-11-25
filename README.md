# read-reply

Lee en voz alta la última respuesta del agente de programación del panel activo de Herdr. Pulsas F9 y la oyes con Álvaro, la voz natural de Edge en español de España; vuelves a pulsar F9 y se calla. Si solo te interesa una parte, la seleccionas con el ratón y pulsas Mayús+F9. Mientras lee, una ventana pequeña sobre el terminal permite pausarla, saltar a otra frase, cambiar la velocidad y pararla. Nunca lee nada por su cuenta.

Funciona con Claude Code, Codex y Antigravity (`agy`) dentro de [Herdr](https://herdr.dev), en WSL sobre Windows.

## Requisitos

- Windows con WSL 2, y Herdr 0.9.5 o posterior dentro de WSL.
- En Herdr, la integración de cada agente que uses, que le dice qué conversación hay en cada panel: `herdr integration install claude`, `codex` o `antigravity-cli`. `herdr integration status` dice cuáles tienes.
- Microsoft Edge en Windows, que viene con el sistema.
- En WSL: [uv](https://docs.astral.sh/uv/).
- Internet para la voz de Álvaro. Si Álvaro falla, la lectura sigue con una voz local de Windows, como Pablo; sin conexión no está probado.

## Instalación

```bash
git clone https://github.com/sergiooriola/read-reply ~/dev/read-reply
~/dev/read-reply/scripts/install
```

`scripts/install` lo instala con `uv tool install` y las versiones exactas de `uv.lock`, que `uv tool install` por sí solo no lee. El comando `read-reply` queda en `~/.local/bin`. Después, los atajos en `~/.config/herdr/config.toml`:

```toml
[[keys.command]]
key = "f9"
type = "shell"
command = "read-reply"
description = "Leer en voz alta la última respuesta del agente (otra vez: parar)"

[[keys.command]]
key = "shift+f9"
type = "shell"
command = "read-reply --clipboard"
description = "Leer en voz alta lo seleccionado o copiado (otra vez: parar)"
```

y `herdr server reload-config` para cargarlo. Los errores salen como notificaciones de Herdr, que de serie están desactivadas: activa `[ui.toast] delivery = "herdr"` para verlas dentro de Herdr, o `"system"` para verlas como notificaciones de Windows. Para instalar una versión nueva del código, `scripts/install` otra vez.

## Uso

- **F9** lee la última respuesta terminada del agente del panel activo. Si el agente está trabajando, lee la anterior.
- **Mayús+F9** lee solo lo que hayas seleccionado con el ratón en el terminal. Herdr lo copia al soltar el botón, y Mayús+F9 lee lo copiado, así que también sirve para un texto copiado en cualquier otro programa de Windows. Herdr copia a través de Windows Terminal, que lo permite de serie; si en tu perfil está desactivado `compatibility.allowOSC52`, leería la copia anterior: copia tú el texto antes de pulsar.
- **F9 o Mayús+F9 otra vez**, mientras lee, la corta.
- **La ventana**, arriba en el centro del terminal y por encima de las demás mientras lee, no se queda con el foco: sigues escribiendo donde estabas. Con un clic en ella:
  - **Pausa y continuar** (o espacio). Al continuar, vuelve al principio de la frase.
  - **⏮ y ⏭** (o ← y →) van a la frase anterior y a la siguiente.
  - **El deslizador** de abajo muestra por dónde va. Arrástralo, o haz clic en él, para saltar a la frase de ese punto.
  - **− y +** (o las teclas − y +) cambian la velocidad, de 0,5× a 2×. Se recuerda para la próxima vez.
  - **Parar** (o Esc, o cerrar la ventana).

  ![La ventana de lectura: frase anterior, pausa, frase siguiente, velocidad y parar, con el deslizador debajo](docs/controller.png)
- Los errores, como un panel sin agente, salen como notificación de Herdr, que llega a Windows si Herdr tiene `[ui.toast] delivery = "system"`.
- `read-reply --pane w1:p2 --print` escribe el texto tal como lo leería, sin leerlo. Sirve para revisar cómo queda una respuesta. `read-reply --clipboard --print` hace lo mismo con lo copiado.

## Cómo funciona

1. Herdr pasa a sus atajos el panel activo en `HERDR_ACTIVE_PANE_ID`, y `herdr agent get` dice qué agente hay en él y cuál es su sesión (`herdr.py`).
2. La respuesta sale de la transcripción de esa sesión, que se lee desde el final porque alguna pasa de 600 MB (`transcripts.py`):
   - Claude Code: el último mensaje que cerró un turno, en `~/.claude/projects/` (o bajo `CLAUDE_CONFIG_DIR`).
   - Codex: el último mensaje de su última tarea terminada, en `~/.codex/sessions/` (o bajo `CODEX_HOME`).
   - Antigravity: la última respuesta del modelo que no llama a herramientas, en `~/.gemini/antigravity-cli/brain/<conversación>/.system_generated/logs/transcript_full.jsonl`.
3. [markdown-it-py](https://github.com/executablebooks/markdown-it-py) lee el Markdown como GitHub, y la respuesta se convierte en párrafos para el oído: sin marcas, con los bloques de código anunciados en vez de deletreados, las tablas fila a fila, los enlaces por su texto y sin las notas al pie (`speech_text.py`).
4. Edge los lee con la Web Speech API estándar, que en Edge incluye las voces naturales de Microsoft, en una ventana de aplicación (`--app`) con los controles. Un servidor HTTP efímero en `127.0.0.1` le pasa a la página el texto y la orden de parar. La página se cierra al acabar, y Edge con ella (`player.py`, `player.html`).
5. La página lee fragmento a fragmento (`reading.mjs`). Para pausar, cambiar la velocidad o saltar, corta el fragmento y vuelve a pedirlo desde el principio de una frase o desde la palabra en curso, que Edge le dice con eventos `boundary`. Si Álvaro falla, lo intenta otra vez con él y, si vuelve a fallar, sigue con una voz local.
6. Mientras se prepara el texto, un script de PowerShell busca la ventana de Windows Terminal. Cuando se abre la de lectura, que reconoce por su perfil de Edge, la coloca arriba en el centro del terminal, por encima de las demás, y devuelve el foco a la ventana que lo tenía (`desktop.py`, `desktop.ps1`).
7. Una segunda pulsación encuentra ocupado el bloqueo de la lectura en curso y le pide que pare (`cli.py`).

Con Mayús+F9, el texto no sale de la transcripción sino del portapapeles de Windows, que lee `Get-Clipboard` en PowerShell (`windows.py`). Lo copiado del terminal es la respuesta ya dibujada, sin el Markdown, pero se parece lo bastante: las listas conservan sus guiones y números, y las líneas cortadas al ancho de la ventana se vuelven a unir. Así que pasa por el mismo analizador, preparado antes (`screen_chunks` en `speech_text.py`):

- Se quita la sangría común a todas las líneas, para que una selección que empieza en una sublista siga siendo una lista. El resto se conserva: distingue el segundo párrafo de un paso del paso siguiente, y un número que la ventana dejó al principio de una línea («2026.») de un paso numerado.
- Las marcas que los agentes ponen delante de cada mensaje (● en Claude Code, • en Codex, que también lo usa en las viñetas) se convierten en guiones.
- Una línea que empieza como un paso («2.») empieza un elemento nuevo si tiene menos sangría que la anterior. Con la misma sangría, es un número que cortó la ventana («octubre de / 2026.») y sigue la frase.
- El analizador no reconoce ni HTML ni código: un `<panel>` o una línea con ```` ``` ```` se leen como texto.

Deja tres cosas fuera del repositorio: un perfil propio de Edge en `%LOCALAPPDATA%\read-reply\edge-profile`, de unos 45 MB y aparte del tuyo; la velocidad elegida, en `~/.local/state/read-reply/rate` (o bajo `XDG_STATE_HOME`), y el bloqueo, en `$XDG_RUNTIME_DIR/read-reply/`.

### Por qué así

- **La voz de Edge:** es la voz masculina en español de España más realista que se puede usar gratis y sin cuenta. Azure Speech da las mismas voces con API oficial, pero su plan gratuito (500.000 caracteres al mes) se queda corto. `edge-tts` usa el servicio interno de Edge, y Microsoft lo rompió a propósito en octubre de 2026.
- **La ventana, de Edge:** es la misma página que lee, así que no hace falta ninguna dependencia nueva. Un panel emergente de Herdr taparía el del agente y se quedaría con el teclado.
- **Pausar cortando:** `speechSynthesis.pause()` no hace nada con Álvaro: sigue hablando (medido en #7). Cortar y retomar sí funciona, a cambio de menos de un segundo de silencio antes de seguir.
- **markdown-it-py:** un analizador de Markdown de verdad, en vez de expresiones regulares. Su plugin `gfm` (de [mdit-py-plugins](https://github.com/executablebooks/mdit-py-plugins), del mismo equipo) entiende el Markdown de GitHub, que es el que escriben los agentes. Se instala con el paquete y `scripts/install` toma su versión de `uv.lock`: antes era pandoc, un programa aparte cuya versión dependía de cada máquina.
- **El portapapeles, y no la selección de Herdr:** Herdr solo pasa la selección a las acciones de sus plugins, no a un atajo `shell`. Además, con `copy_on_select`, que viene activado, la copia al portapapeles y la borra en cuanto sueltas el ratón (comprobado en el código de Herdr 0.9.5). Para leerla directamente habría que desactivar `copy_on_select` y copiar con Ctrl+C, que sin una selección visible interrumpe al agente. El portapapeles sirve tal como seleccionas hoy.
- **Antigravity, por su transcripción en JSONL:** `agy` guarda cada conversación en una base de datos SQLite, con los pasos en bloques binarios (protobuf) de un formato privado. Al lado escribe la misma conversación en JSONL, un paso por línea. Ninguno de los dos está documentado, pero el JSONL se lee con la biblioteca estándar. De sus dos copias se lee `transcript_full.jsonl`, porque `transcript.jsonl` corta los mensajes largos hacia los 4.000 caracteres.
- **Ninguna dependencia más:** el resto es la biblioteca estándar de Python.

## Límites

- La transcripción de Antigravity no está documentada: una versión nueva de `agy` puede cambiarla sin avisar, y entonces F9 diría que no encuentra la conversación o que no hay respuesta.
- Las rutas y el código dentro de una frase se leen tal cual.
- En lo copiado del terminal no se distingue el código: se lee entero, en vez de anunciarse. Las tablas llegan dibujadas con líneas, no fila a fila. Si la selección empieza a mitad de un elemento, sus subelementos pueden leerse seguidos, en un solo fragmento, sin perder palabras.
- Al continuar tras una pausa o cambiar la velocidad, Álvaro tarda hasta un segundo en volver a hablar, y se nota el corte: es una voz online.
- Depende de que Edge siga ofreciendo sus voces online a las páginas web.
- La ventana se coloca sobre Windows Terminal. Con otro terminal, se abre sobre la ventana que tengas delante.

## Desarrollo

```bash
uv sync
git config core.hooksPath .githooks   # una vez por copia del repositorio
scripts/check                         # formato, lint, tipos y pruebas
```

Las pruebas de la página (`tests/js`) corren en Node.js 24 o posterior, sin dependencias.

La CI (GitHub Actions, `.github/workflows/ci.yml`) lanza `scripts/check` en cada PR y en cada push a `main`; en un repositorio público no gasta minutos. El hook `pre-push` lo lanza también antes de cada push, para enterarte antes de subir, y rechaza el push si falla o si hay cambios sin commit.

`uv` solo instala versiones publicadas hace al menos dos semanas (`exclude-newer` en `pyproject.toml`): una versión maliciosa suele detectarse y retirarse en días. Dependabot propone una vez al mes las versiones nuevas de las dependencias y de las acciones de la CI, con la misma espera (`.github/dependabot.yml`).

### Probar que suena

Las pruebas no llegan a Edge, que solo corre en Windows. Para comprobar que una lectura se oye, mide el nivel de la salida de audio de Windows mientras lee:

```bash
powershell.exe -ExecutionPolicy Bypass -File "$(wslpath -w scripts/audio-meter.ps1)" -Seconds 20 &
uv run read-reply --pane <panel>
```

En silencio, el pico ronda 0,001. Mientras Álvaro habla, sube por encima de 0,1.

## Licencia

[MIT](LICENSE).
