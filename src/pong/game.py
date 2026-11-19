"""Pong 3D a pantalla dividida para Toxinator."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

from direct.gui.DirectGui import DGG, DirectFrame
from direct.gui.OnscreenText import OnscreenText
from panda3d.core import (
    AmbientLight,
    Camera,
    DirectionalLight,
    NodePath,
    TextNode,
    Vec4,
)
from toxinator.api import GameContext, GameManifest

from .rules import (
    BALL_RADIUS,
    COURT_HALF_HEIGHT,
    PADDLE_HALF_Y,
    PADDLE_X,
    CpuPaddle,
    PongEvent,
    PongMatch,
    clamp,
    paddle_from_tilt,
    paddle_from_touch_x,
    sensors_available,
)

NAVY_2 = Vec4(0.067, 0.106, 0.165, 1.0)
NAVY_3 = Vec4(0.020, 0.035, 0.062, 1.0)
BONE = Vec4(0.965, 0.937, 0.878, 1.0)
MUTED = Vec4(0.455, 0.514, 0.604, 1.0)
GOLD = Vec4(0.925, 0.729, 0.267, 1.0)
CRIMSON = Vec4(0.776, 0.220, 0.310, 1.0)
JADE = Vec4(0.267, 0.639, 0.557, 1.0)
WHITE = Vec4(1.0, 1.0, 1.0, 1.0)
BACKGROUND = Vec4(0.025, 0.040, 0.070, 1.0)

BALL_Z = 0.85
PADDLE_Z = 1.00
PADDLE_HEIGHT = 1.60
PADDLE_THICKNESS = 0.10
TRAIL_LENGTH = 12
TRAIL_SAMPLES = 18
CAMERA_X = 11.4
CAMERA_Z = 4.0
CAMERA_FOV = 60.0
SMOOTH_TIME = 0.09


def mix(a: Vec4, b: Vec4, amount: float) -> Vec4:
    t = clamp(amount, 0.0, 1.0)
    return Vec4(
        a[0] + (b[0] - a[0]) * t,
        a[1] + (b[1] - a[1]) * t,
        a[2] + (b[2] - a[2]) * t,
        a[3] + (b[3] - a[3]) * t,
    )


class Pong:
    """Duelo 3D: cada jugador ve la cancha desde su propio lado."""

    PLAYER_COLORS = (CRIMSON, JADE)

    def __init__(self, manifest: GameManifest) -> None:
        self.manifest = manifest
        self.ctx: GameContext | None = None
        self.base: Any = None
        self.root: NodePath | None = None
        self.ui_root: NodePath | None = None

        self.match = PongMatch()
        self.cpu = [CpuPaddle(0), CpuPaddle(1)]
        self._sensor_seen = [False, False]
        self._touch_seen = [False, False]
        self._human_active = [False, False]
        self._paddle_smooth = [0.0, 0.0]
        self._a_held = False

        self._font_display: Any = None
        self._font_mono: Any = None
        self._hud: dict[str, OnscreenText] = {}
        self._half_x = 0.888

        self._paddle_pivots: list[NodePath] = []
        self._paddle_bodies: list[NodePath] = []
        self._paddle_glows: list[list[NodePath]] = []
        self._paddle_flash = [0.0, 0.0]
        self._score_flash = [0.0, 0.0]
        self._goal_nodes: list[list[NodePath]] = []
        self._goal_colors: list[Vec4] = []
        self._goal_flash = [0.0, 0.0]

        self._ball_core: NodePath | None = None
        self._ball_glow: NodePath | None = None
        self._ball_shadow: NodePath | None = None
        self._trail: list[NodePath] = []
        self._trail_history: list[tuple[float, float]] = []

        self._message = ""
        self._message_timer = 0.0
        self._message_color = BONE

        self._regions: list[Any] = []
        self._cameras: list[NodePath] = []
        self._default_region: Any = None
        self._default_active = True
        self._divider: DirectFrame | None = None
        self._divider_glow: DirectFrame | None = None

    # -- lifecycle ----------------------------------------------------------

    def start(self, ctx: GameContext) -> None:
        self.ctx = ctx
        self.base = ctx.base
        self.match = PongMatch()
        self.cpu = [CpuPaddle(0), CpuPaddle(1)]
        self._sensor_seen = [False, False]
        self._touch_seen = [False, False]
        self._human_active = [False, False]
        self._paddle_smooth = [0.0, 0.0]
        self._a_held = False
        self._paddle_flash = [0.0, 0.0]
        self._score_flash = [0.0, 0.0]
        self._goal_flash = [0.0, 0.0]
        self._trail_history = []
        self._message = "DUELO 3D"
        self._message_timer = 1.4
        self._message_color = BONE

        self.root = ctx.scene.attach_new_node("pong-3d-arena")
        self.ui_root = ctx.ui.attach_new_node("pong-3d-ui")
        self._load_fonts()
        self._build_lights()
        self._build_arena()
        self._build_ball()
        self._build_hud()
        self._setup_split_screen()
        self._update_hud(None)

    def update(self, dt: float) -> None:
        if self.ctx is None:
            return
        dt = clamp(dt, 0.0, 0.1)
        state = self.ctx.input_state

        self._update_paddles(state, dt)

        a_down = self._a_down(state)
        a_edge = a_down and not self._a_held
        self._a_held = a_down

        events = self.match.advance(dt)
        for event in events:
            self._on_event(event)

        if a_edge:
            if self.match.state == "game_over":
                self._restart()
            elif self.match.state == "serve":
                self.match.serve_now()

        self._update_effects(dt)
        self._update_scene()
        self._update_hud(state)

    def stop(self) -> None:
        self._teardown_split_screen()
        self._hud.clear()
        if self._divider is not None:
            self._divider.destroy()
            self._divider = None
        if self._divider_glow is not None:
            self._divider_glow.destroy()
            self._divider_glow = None
        if self.ui_root is not None:
            self.ui_root.remove_node()
            self.ui_root = None
        if self.root is not None:
            self.root.remove_node()
            self.root = None
        self._paddle_pivots.clear()
        self._paddle_bodies.clear()
        self._paddle_glows.clear()
        self._goal_nodes.clear()
        self._trail.clear()
        self._trail_history.clear()
        self._ball_core = None
        self._ball_glow = None
        self._ball_shadow = None
        self._font_display = None
        self._font_mono = None
        self.ctx = None
        self.base = None

    # -- input --------------------------------------------------------------

    def _a_down(self, state: Any) -> bool:
        for slot in (0, 1):
            frame = state.frame(slot)
            if frame is not None and frame.button("A"):
                return True
        return False

    def _update_paddles(self, state: Any, dt: float) -> None:
        for player in (0, 1):
            side = -1 if player == 0 else 1
            frame = state.frame(player)
            if frame is None:
                self._sensor_seen[player] = False
                self._touch_seen[player] = False
                self._human_active[player] = False
                self.cpu[player].update(self.match, dt)
                continue

            if sensors_available(frame.orientation, frame.accel, frame.gyro):
                self._sensor_seen[player] = True

            target: float | None = None
            if self._sensor_seen[player]:
                target = paddle_from_tilt(frame.orientation[2], side)
            elif frame.touch:
                touch = min(frame.touch, key=lambda entry: entry.id)
                self._touch_seen[player] = True
                target = paddle_from_touch_x(touch.x, side)
            elif frame.pointer is not None:
                self._touch_seen[player] = True
                target = paddle_from_touch_x(frame.pointer[0], side)

            if target is not None:
                if not self._human_active[player]:
                    self._paddle_smooth[player] = self.match.paddles[player]
                    self._human_active[player] = True
                blend = 1.0 - math.exp(-dt / SMOOTH_TIME)
                self._paddle_smooth[player] += (
                    target - self._paddle_smooth[player]
                ) * blend
                self.match.set_paddle(player, self._paddle_smooth[player])
                self.cpu[player].sync(self.match.paddles[player])
            elif self._touch_seen[player]:
                self.cpu[player].sync(self.match.paddles[player])
            else:
                self.cpu[player].update(self.match, dt)

    def _restart(self) -> None:
        self.match.restart()
        for cpu in self.cpu:
            cpu.sync(0.0)
        self._paddle_smooth = [0.0, 0.0]
        self._message = "NUEVA PARTIDA"
        self._message_timer = 1.4
        self._message_color = BONE
        self._paddle_flash = [0.0, 0.0]
        self._score_flash = [0.0, 0.0]
        self._goal_flash = [0.0, 0.0]
        self._trail_history.clear()

    # -- split screen -------------------------------------------------------

    def _setup_split_screen(self) -> None:
        if self.base is None or self.base.win is None:
            return
        win = self.base.win
        self._default_region = self.base.camNode.get_display_region(0)
        if self._default_region is not None:
            self._default_active = self._default_region.is_active()
            self._default_region.set_active(False)

        region_aspect = (win.get_x_size() * 0.5) / max(1, win.get_y_size())
        for player in (0, 1):
            side = -1.0 if player == 0 else 1.0
            camera = Camera(f"pong-camera-{player}")
            camera.set_scene(self.base.render)
            camera_node = self.base.render.attach_new_node(camera)
            camera_node.set_pos(side * CAMERA_X, 0.0, CAMERA_Z)
            camera_node.look_at(0.0, 0.0, 0.60)
            lens = camera.get_lens()
            lens.set_fov(CAMERA_FOV)
            lens.set_aspect_ratio(region_aspect)
            lens.set_near_far(0.08, 80.0)

            x0, x1 = (0.0, 0.5) if player == 0 else (0.5, 1.0)
            region = win.make_display_region(x0, x1, 0.0, 1.0)
            region.set_camera(camera_node)
            region.set_clear_color(BACKGROUND)
            region.set_clear_color_active(True)
            region.set_clear_depth(1.0)
            self._regions.append(region)
            self._cameras.append(camera_node)

    def _teardown_split_screen(self) -> None:
        if self.base is not None and self.base.win is not None:
            for region in self._regions:
                self.base.win.remove_display_region(region)
        self._regions.clear()
        for camera in self._cameras:
            camera.remove_node()
        self._cameras.clear()
        if self._default_region is not None:
            self._default_region.set_active(self._default_active)
        self._default_region = None

    # -- scene --------------------------------------------------------------

    def _load_fonts(self) -> None:
        folder = Path(__file__).resolve().parent / "assets" / "fonts"
        self._font_display = self._load_font(folder / "ArchivoBlack-Regular.ttf")
        self._font_mono = self._load_font(folder / "IBMPlexMono-Regular.ttf")

    def _load_font(self, path: Path) -> Any:
        if not path.is_file() or self.base is None:
            return None
        try:
            return self.base.loader.loadFont(str(path))
        except Exception:  # noqa: BLE001 - a font must never stop the game
            return None

    def _box(
        self,
        parent: NodePath,
        center: tuple[float, float, float],
        size: tuple[float, float, float],
        color: Vec4,
    ) -> NodePath:
        assert self.base is not None
        model = self.base.loader.loadModel("models/box")
        model.set_texture_off(1)
        model.set_scale(*size)
        model.set_pos(
            center[0] - size[0] / 2.0,
            center[1] - size[1] / 2.0,
            center[2] - size[2] / 2.0,
        )
        model.set_color(color)
        model.reparent_to(parent)
        return model

    def _sphere(
        self,
        parent: NodePath,
        scale: tuple[float, float, float],
        color: Vec4,
        *,
        transparency: bool = False,
    ) -> NodePath:
        assert self.base is not None
        model = self.base.loader.loadModel("models/misc/sphere")
        model.set_texture_off(1)
        model.set_light_off(1)
        if transparency:
            model.set_transparency(True)
            model.set_depth_write(False)
        model.set_scale(*scale)
        model.set_color(color)
        model.reparent_to(parent)
        return model

    def _build_lights(self) -> None:
        assert self.ctx is not None
        ambient = AmbientLight("pong-ambient")
        ambient.set_color(Vec4(0.50, 0.54, 0.64, 1.0))
        self.ctx.scene.set_light(self.ctx.scene.attach_new_node(ambient))

        key = DirectionalLight("pong-key")
        key.set_color(Vec4(1.0, 0.94, 0.84, 1.0))
        key_node = self.ctx.scene.attach_new_node(key)
        key_node.set_hpr(28.0, -58.0, 0.0)
        self.ctx.scene.set_light(key_node)

        fill = DirectionalLight("pong-fill")
        fill.set_color(Vec4(0.16, 0.26, 0.40, 1.0))
        fill_node = self.ctx.scene.attach_new_node(fill)
        fill_node.set_hpr(-148.0, -24.0, 0.0)
        self.ctx.scene.set_light(fill_node)

    def _build_arena(self) -> None:
        assert self.root is not None
        root = self.root

        self._box(root, (0.0, 0.0, -0.25), (13.2, 7.2, 0.42), NAVY_3)
        self._box(root, (0.0, 0.0, -0.03), (11.5, 6.25, 0.12), NAVY_2)

        wall_inner = COURT_HALF_HEIGHT
        wall_y = wall_inner + 0.06
        for sign in (-1.0, 1.0):
            self._box(
                root,
                (0.0, sign * wall_y, 0.70),
                (11.4, 0.12, 1.40),
                NAVY_2,
            )
            self._box(
                root,
                (0.0, sign * wall_y, 1.42),
                (11.4, 0.10, 0.020),
                mix(GOLD, MUTED, 0.38),
            )

        for sign in (-1.0, 1.0):
            self._box(
                root,
                (0.0, sign * (wall_inner - 0.005), 1.00),
                (11.4, 0.010, 0.035),
                mix(GOLD, MUTED, 0.55),
            )

        for index in range(11):
            self._box(
                root,
                (0.0, -2.5 + index * 0.5, 0.05),
                (0.055, 0.27, 0.025),
                mix(GOLD, BONE, 0.45),
            )

        for sign in (-1.0, 1.0):
            self._box(
                root,
                (0.0, sign * 1.52, 0.045),
                (11.0, 0.035, 0.02),
                MUTED,
            )
            self._box(
                root,
                (sign * 5.52, 0.0, 0.05),
                (0.045, 5.9, 0.025),
                mix(GOLD, BONE, 0.35),
            )
            self._box(
                root,
                (sign * 2.60, 0.0, 0.045),
                (0.035, 5.8, 0.02),
                MUTED,
            )

        for player, color in enumerate(self.PLAYER_COLORS):
            side = -1.0 if player == 0 else 1.0
            goal_x = side * 5.68
            nodes: list[NodePath] = []
            for wall_side in (-1.0, 1.0):
                nodes.append(
                    self._box(
                        root,
                        (goal_x, wall_side * 3.0, 1.16),
                        (0.16, 0.16, 2.32),
                        color,
                    )
                )
            nodes.append(
                self._box(
                    root,
                    (goal_x, 0.0, 0.065),
                    (0.11, 6.0, 0.03),
                    mix(color, BONE, 0.42),
                )
            )
            self._goal_nodes.append(nodes)
            self._goal_colors.append(color)

        for player, color in enumerate(self.PLAYER_COLORS):
            side = -1.0 if player == 0 else 1.0
            pivot = root.attach_new_node(f"paddle-{player}")
            pivot.set_pos(side * PADDLE_X, 0.0, 0.0)

            glow = self._box(
                pivot,
                (0.0, 0.0, PADDLE_Z),
                (0.26, PADDLE_HALF_Y * 2.0 + 0.24, PADDLE_HEIGHT + 0.22),
                Vec4(color[0], color[1], color[2], 0.07),
            )
            glow.set_transparency(True)
            glow.set_light_off(1)
            glow.set_depth_write(False)

            floor_glow = self._box(
                pivot,
                (0.0, 0.0, 0.065),
                (0.78, PADDLE_HALF_Y * 2.0 + 0.55, 0.02),
                Vec4(color[0], color[1], color[2], 0.13),
            )
            floor_glow.set_transparency(True)
            floor_glow.set_light_off(1)

            body = self._box(
                pivot,
                (0.0, 0.0, PADDLE_Z),
                (PADDLE_THICKNESS, PADDLE_HALF_Y * 2.0, PADDLE_HEIGHT),
                color,
            )
            body.set_light_off(1)

            self._paddle_pivots.append(pivot)
            self._paddle_bodies.append(body)
            self._paddle_glows.append([glow, floor_glow])

        self._update_paddle_nodes()

    def _build_ball(self) -> None:
        assert self.root is not None
        root = self.root

        self._ball_shadow = self._sphere(
            root,
            (BALL_RADIUS * 1.15, BALL_RADIUS * 1.15, 0.008),
            Vec4(0.005, 0.010, 0.020, 0.30),
            transparency=True,
        )
        self._ball_shadow.set_pos(0.0, 0.0, 0.072)

        self._ball_glow = self._sphere(
            root,
            (BALL_RADIUS * 2.7, BALL_RADIUS * 2.7, BALL_RADIUS * 2.7),
            Vec4(GOLD[0], GOLD[1], GOLD[2], 0.18),
            transparency=True,
        )
        self._ball_glow.set_pos(0.0, 0.0, BALL_Z)

        self._ball_core = self._sphere(
            root,
            (BALL_RADIUS, BALL_RADIUS, BALL_RADIUS),
            BONE,
        )
        self._ball_core.set_pos(0.0, 0.0, BALL_Z)

        for index in range(TRAIL_LENGTH):
            amount = index / max(1, TRAIL_LENGTH - 1)
            radius = BALL_RADIUS * (1.0 - 0.72 * amount)
            color = mix(BONE, GOLD, amount)
            node = self._sphere(
                root,
                (radius, radius, radius),
                Vec4(color[0], color[1], color[2], 0.30 * (1.0 - 0.82 * amount)),
                transparency=True,
            )
            node.hide()
            self._trail.append(node)

    def _update_paddle_nodes(self) -> None:
        for player, pivot in enumerate(self._paddle_pivots):
            side = -1.0 if player == 0 else 1.0
            pivot.set_pos(side * PADDLE_X, self.match.paddles[player], 0.0)

    # -- frame visuals ------------------------------------------------------

    def _on_event(self, event: PongEvent) -> None:
        if event.kind == "paddle" and event.player is not None:
            self._paddle_flash[event.player] = 0.22
        elif event.kind == "score" and event.player is not None:
            self._score_flash[event.player] = 0.55
            self._paddle_flash[event.player] = 0.28
            self._goal_flash[1 - event.player] = 0.55
            self._message = f"PUNTO P{event.player + 1}"
            self._message_timer = 1.35
            self._message_color = self.PLAYER_COLORS[event.player]
        elif event.kind == "win" and event.player is not None:
            self._message = f"GANA P{event.player + 1}"
            self._message_timer = 0.0
            self._message_color = GOLD

    def _update_effects(self, dt: float) -> None:
        for index in (0, 1):
            self._paddle_flash[index] = max(0.0, self._paddle_flash[index] - dt)
            self._score_flash[index] = max(0.0, self._score_flash[index] - dt)
            self._goal_flash[index] = max(0.0, self._goal_flash[index] - dt)
        if self._message_timer > 0.0:
            self._message_timer = max(0.0, self._message_timer - dt)
            if self._message_timer == 0.0 and self.match.state != "game_over":
                self._message = ""

    def _update_scene(self) -> None:
        self._update_paddle_nodes()
        self._update_paddle_colors()
        self._update_goal_colors()

        match = self.match
        ball = match.ball
        playing = match.state == "playing"
        serving = match.state == "serve"

        if playing:
            if not self._trail_history or self._distance(
                self._trail_history[-1], (ball.x, ball.y)
            ) > 0.035:
                self._trail_history.append((ball.x, ball.y))
                if len(self._trail_history) > TRAIL_SAMPLES:
                    self._trail_history.pop(0)
        else:
            self._trail_history.clear()

        show_ball = playing or serving
        if self._ball_core is not None:
            if show_ball:
                pulse = 1.0
                if serving:
                    pulse += 0.10 * math.sin(match.elapsed * 7.0)
                self._ball_core.set_pos(ball.x, ball.y, BALL_Z)
                self._ball_core.set_scale(BALL_RADIUS * pulse)
                self._ball_core.show()
            else:
                self._ball_core.hide()

        if self._ball_glow is not None:
            if show_ball:
                glow_pulse = 1.0 + 0.14 * math.sin(match.elapsed * 4.2)
                self._ball_glow.set_pos(ball.x, ball.y, BALL_Z)
                self._ball_glow.set_scale(BALL_RADIUS * 2.7 * glow_pulse)
                self._ball_glow.show()
            else:
                self._ball_glow.hide()

        if self._ball_shadow is not None:
            if show_ball:
                self._ball_shadow.set_pos(ball.x, ball.y, 0.072)
                self._ball_shadow.show()
            else:
                self._ball_shadow.hide()

        for index, node in enumerate(self._trail):
            sample = index + 1
            if playing and len(self._trail_history) > sample:
                x, y = self._trail_history[-sample - 1]
                node.set_pos(x, y, BALL_Z)
                node.show()
            else:
                node.hide()

    def _update_paddle_colors(self) -> None:
        for player, color in enumerate(self.PLAYER_COLORS):
            body = self._paddle_bodies[player]
            flash = clamp(self._paddle_flash[player] / 0.22, 0.0, 1.0)
            body.set_color(mix(color, BONE, 0.45 * flash))
            glow, floor_glow = self._paddle_glows[player]
            glow.set_color(Vec4(color[0], color[1], color[2], 0.06 + 0.15 * flash))
            floor_glow.set_color(
                Vec4(color[0], color[1], color[2], 0.12 + 0.22 * flash)
            )

    def _update_goal_colors(self) -> None:
        for player, color in enumerate(self._goal_colors):
            flash = clamp(self._goal_flash[player] / 0.55, 0.0, 1.0)
            target = mix(color, WHITE, 0.65 * flash)
            for node in self._goal_nodes[player]:
                node.set_color(target)

    @staticmethod
    def _distance(a: tuple[float, float], b: tuple[float, float]) -> float:
        return math.hypot(a[0] - b[0], a[1] - b[1])

    # -- HUD ----------------------------------------------------------------

    def _text(
        self,
        key: str,
        *,
        position: tuple[float, float],
        scale: float,
        color: Vec4,
        font: Any = None,
        align: int = TextNode.ACenter,
    ) -> OnscreenText:
        assert self.ui_root is not None
        text = OnscreenText(
            text="",
            parent=self.ui_root,
            pos=position,
            scale=scale,
            fg=color,
            shadow=Vec4(0.0, 0.0, 0.0, 0.78),
            align=align,
            mayChange=True,
            font=font,
        )
        self._hud[key] = text
        return text

    def _build_hud(self) -> None:
        assert self.ui_root is not None
        aspect = 1.777
        if self.base is not None:
            try:
                aspect = float(self.base.getAspectRatio())
            except Exception:  # noqa: BLE001 - headless fallback
                aspect = 1.777
        self._half_x = aspect / 2.0

        self._divider_glow = DirectFrame(
            parent=self.ui_root,
            frameColor=(GOLD[0], GOLD[1], GOLD[2], 0.12),
            frameSize=(-0.016, 0.016, -1.0, 1.0),
            relief=DGG.FLAT,
        )
        self._divider = DirectFrame(
            parent=self.ui_root,
            frameColor=(GOLD[0], GOLD[1], GOLD[2], 0.55),
            frameSize=(-0.0025, 0.0025, -1.0, 1.0),
            relief=DGG.FLAT,
        )

        for player, color in enumerate(self.PLAYER_COLORS):
            x = -self._half_x if player == 0 else self._half_x
            opponent = self.PLAYER_COLORS[1 - player]
            self._text(
                f"own{player}",
                position=(x, 0.935),
                scale=0.072,
                color=color,
                font=self._font_display,
            )
            self._text(
                f"rival{player}",
                position=(x, 0.868),
                scale=0.028,
                color=mix(opponent, MUTED, 0.25),
                font=self._font_mono,
            )
            self._text(
                f"status{player}",
                position=(x, 0.792),
                scale=0.027,
                color=mix(color, BONE, 0.35),
                font=self._font_mono,
            )
            self._text(
                f"prompt{player}",
                position=(x, 0.738),
                scale=0.025,
                color=BONE,
                font=self._font_mono,
            )
            self._text(
                f"message{player}",
                position=(x, 0.500),
                scale=0.054,
                color=GOLD,
                font=self._font_display,
            )

    def _update_hud(self, state: Any) -> None:
        if not self._hud or self.ctx is None:
            return

        match = self.match
        for player in (0, 1):
            color = self.PLAYER_COLORS[player]
            opponent = self.PLAYER_COLORS[1 - player]
            own = self._hud[f"own{player}"]
            flash = clamp(self._score_flash[player] / 0.55, 0.0, 1.0)
            own.setText(f"P{player + 1}  {match.scores[player]}")
            own.setFg(mix(color, WHITE, flash))
            own.setScale(0.072 * (1.0 + 0.30 * flash))

            self._hud[f"rival{player}"].setText(
                f"RIVAL  {match.scores[1 - player]}"
            )
            self._hud[f"rival{player}"].setFg(mix(opponent, MUTED, 0.25))

            frame = None if state is None else state.frame(player)
            if frame is None:
                status = "CPU"
                prompt = "CPU EN ESTE LADO"
            elif self._sensor_seen[player]:
                status = "TILT"
                prompt = "INCLINÁ IZQUIERDA / DERECHA"
            elif self._touch_seen[player]:
                status = "TÁCTIL · --https"
                prompt = "ACTIVÁ SENSORES EN LA PWA"
            else:
                status = "SIN SENSORES"
                prompt = "ACTIVÁ SENSORES  +  --https"

            self._hud[f"status{player}"].setText(f"P{player + 1} · {status}")

            if match.state == "game_over":
                prompt = "A / NUEVA PARTIDA"
            elif match.state == "serve":
                prompt = f"SAQUE EN {match.timer:.1f}s  ·  A / SACAR"
            self._hud[f"prompt{player}"].setText(prompt)

            if match.state == "game_over" and match.winner is not None:
                self._hud[f"message{player}"].setText(f"GANA P{match.winner + 1}")
                self._hud[f"message{player}"].setFg(GOLD)
            else:
                self._hud[f"message{player}"].setText(self._message)
                self._hud[f"message{player}"].setFg(self._message_color)
