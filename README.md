# Pong 3D

Duelo de Pong **en 3D y a pantalla dividida** para la consola Toxinator.
Cada jugador ve la cancha desde su propio lado, con el rival al fondo, y mueve
su paleta **inclinando el celular**.

## Controles

- **Jugador 1:** celular en el **slot 0**. Mitad izquierda de la pantalla.
- **Jugador 2:** celular en el **slot 1**. Mitad derecha de la pantalla.
- **Incliná el celular a izquierda/derecha** para mover tu paleta en tu vista.
- **A:** saca antes de que termine la cuenta y arranca una nueva partida al
  final.
- **B:** reservado por la plataforma para volver.
- Gana el primero en llegar a **7**.

Antes de jugar:

1. Abrí la PWA del celular y tocá **Activar sensores**.
2. Tocá **Calibrar** con el celular en la pose neutra (vertical y cómoda).
3. Movete a izquierda/derecha inclinando el celular.

La orientación que llega al juego es relativa a esa pose neutra.

## Los sensores necesitan HTTPS

El modo HTTP por defecto de Toxinator **no entrega movimiento**. Si corrés el
juego sin `--https`, la paleta no responde al inclinar y el HUD lo avisa con
`SIN SENSORES` o `TÁCTIL · --https`. En ese caso queda el touch como respaldo,
pero la gracia del juego es el tilt.

```bash
cd /home/ska/Projects/toxinator
uv run toxinator play pong --https
```

La primera vez hay que aceptar el certificado autofirmado en el celular. Si usás
un certificado propio:

```bash
uv run toxinator play pong --https --cert mi-cert.pem --key mi-clave.pem
```

En iPhone/iPad, el permiso de movimiento puede requerir tocar la pantalla o el
botón de calibración de la PWA después de abrir la sesión.

## Modos

- **Dos celulares:** duelo 1v1 real, una paleta por lado.
- **Un celular:** el otro lado lo juega la CPU.
- **Sin celulares o `--demo`:** modo demostración. La CPU juega ambos lados y
  la pantalla dividida sigue mostrando las dos perspectivas.

## Instalar y ejecutar

Este repo vive en el directorio de juegos externos, así que la consola lo
descubre directamente. Si lo clonás en otro lado:

```bash
cd /home/ska/Projects/toxinator
uv run toxinator install /ruta/a/pong
```

Ejecutar:

```bash
cd /home/ska/Projects/toxinator
uv run toxinator play pong --https
```

Demo sintética (P1 usa sensores simulados):

```bash
uv run toxinator play pong --demo
```

Captura headless:

```bash
uv run toxinator play pong --demo --offscreen \
  --screenshot /tmp/pong.png --screenshot-after 3 --seconds 5
```

Reiniciá el launcher si estaba abierto para que tome los cambios.

## Cómo está hecho

```text
pong/
├── src/pong/
│   ├── __init__.py       # create_game(manifest)
│   ├── manifest.toml
│   ├── rules.py          # física, puntaje, tilt y CPU sin Panda3D
│   ├── game.py           # dos cámaras, escena 3D, HUD y controles
│   └── assets/fonts/     # Archivo Black + IBM Plex Mono (OFL)
├── tests/test_rules.py
└── pyproject.toml
```

- La cancha es 3D: el jugador mira desde atrás de su paleta, el rival está al
  fondo y la pelota viene en profundidad.
- Dos `Camera` de Panda3D con dos `DisplayRegion` verticales; la cámara 3D por
  defecto se desactiva mientras dura el juego y se restaura en `stop`.
- El HUD se duplica por mitad: marcador propio, marcador del rival, estado
  (`TILT`, `TÁCTIL`, `CPU`) e instrucción.
- La lógica de juego sigue en `rules.py` y no importa Panda3D.
- El touch solo se usa si el celular no publica datos de movimiento; cuando hay
  sensores, el tilt tiene prioridad y el touch se ignora.

## Tests y calidad

```bash
cd /home/ska/Projects/toxinator-games/pong
/home/ska/Projects/toxinator/.venv/bin/pytest -q
/home/ska/Projects/toxinator/.venv/bin/ruff check src tests
/home/ska/Projects/toxinator/.venv/bin/mypy src/pong
```

## Reglas de la plataforma

- Solo se importa `toxinator.api` del runtime.
- La escena cuelga de `ctx.scene` y el HUD de `ctx.ui`.
- El input sale de `ctx.input_state`; se leen los slots 0 y 1.
- `stop()` elimina las cámaras, los `DisplayRegion`, el HUD y las fuentes.
- `requires_api = "0.1"`.
