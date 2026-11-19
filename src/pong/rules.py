"""Reglas puras de Pong: física, puntaje y CPU.

Este módulo no importa Panda3D para poder testearse sin abrir una ventana.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass

COURT_HALF_WIDTH = 5.2
COURT_HALF_HEIGHT = 3.0
PADDLE_X = 4.55
PADDLE_HALF_WIDTH = 0.14
PADDLE_HALF_Y = 0.52
PADDLE_LIMIT = COURT_HALF_HEIGHT - PADDLE_HALF_Y - 0.06
BALL_RADIUS = 0.20

WIN_SCORE = 7
OUT_MARGIN = 0.55
SERVE_SPEED = 6.2
MAX_SPEED = 11.5
SPEED_GAIN = 1.035
MAX_BOUNCE_ANGLE = math.radians(52.0)
TILT_DEADZONE = 2.5
TILT_RANGE = 30.0

FIXED_DT = 1.0 / 120.0
START_DELAY = 1.6
POINT_DELAY = 1.1


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def reflect(value: float, low: float, high: float) -> float:
    """Fold a value into [low, high] as if it bounced off both walls."""
    span = high - low
    if span <= 0.0:
        return low
    folded = (value - low) % (2.0 * span)
    if folded > span:
        folded = 2.0 * span - folded
    return low + folded


def paddle_from_screen(screen: float, side: int) -> float:
    """Map screen-left/right (-1..1) to their world Y for one camera side."""
    if side not in (-1, 1):
        raise ValueError("side must be -1 or 1")
    return clamp(side * clamp(screen, -1.0, 1.0) * PADDLE_LIMIT, -PADDLE_LIMIT, PADDLE_LIMIT)


def paddle_from_touch_x(x: float, side: int) -> float:
    """Touch fallback: normalized X (0 left, 1 right) to screen position."""
    return paddle_from_screen((clamp(x, 0.0, 1.0) - 0.5) * 2.0, side)


def paddle_from_tilt(gamma: float, side: int) -> float:
    """Tilt fallback: phone roll in degrees to screen position."""
    magnitude = abs(gamma)
    if magnitude <= TILT_DEADZONE:
        screen = 0.0
    else:
        screen = math.copysign(
            (magnitude - TILT_DEADZONE) / (TILT_RANGE - TILT_DEADZONE),
            gamma,
        )
    return paddle_from_screen(screen, side)


def sensors_available(
    orientation: tuple[float, float, float],
    accel: tuple[float, float, float],
    gyro: tuple[float, float, float],
) -> bool:
    """Infer whether the phone is publishing motion data at all."""
    if any(abs(value) > 0.5 for value in orientation):
        return True
    if any(abs(value) > 0.15 for value in gyro):
        return True
    return math.sqrt(sum(value * value for value in accel)) > 1.0


@dataclass(frozen=True, slots=True)
class PongEvent:
    """Something worth showing a small visual effect for."""

    kind: str
    player: int | None = None
    x: float = 0.0
    y: float = 0.0


@dataclass
class Ball:
    x: float = 0.0
    y: float = 0.0
    vx: float = 0.0
    vy: float = 0.0

    @property
    def speed(self) -> float:
        return math.hypot(self.vx, self.vy)


class PongMatch:
    """State machine for one first-to-seven match."""

    def __init__(
        self,
        *,
        rng: random.Random | None = None,
        win_score: int = WIN_SCORE,
    ) -> None:
        self.rng = rng if rng is not None else random.Random()
        self.win_score = max(1, win_score)
        self.scores = [0, 0]
        self.paddles = [0.0, 0.0]
        self.ball = Ball()
        self.state = "serve"
        self.timer = START_DELAY
        self.serve_dir = self.rng.choice((-1, 1))
        self.winner: int | None = None
        self.last_scorer: int | None = None
        self.rally = 0
        self.longest_rally = 0
        self.accumulator = 0.0
        self.elapsed = 0.0

    # -- input --------------------------------------------------------------

    def set_paddle(self, player: int, y: float) -> None:
        if player not in (0, 1):
            raise ValueError("player must be 0 or 1")
        self.paddles[player] = clamp(y, -PADDLE_LIMIT, PADDLE_LIMIT)

    # -- lifecycle ----------------------------------------------------------

    def restart(self) -> None:
        self.scores = [0, 0]
        self.paddles = [0.0, 0.0]
        self.ball = Ball()
        self.state = "serve"
        self.timer = START_DELAY
        self.serve_dir = self.rng.choice((-1, 1))
        self.winner = None
        self.last_scorer = None
        self.rally = 0
        self.longest_rally = 0
        self.accumulator = 0.0
        self.elapsed = 0.0

    def serve_now(self) -> None:
        if self.state == "serve":
            self._launch()

    def advance(self, dt: float) -> list[PongEvent]:
        """Advance the match, using a fixed internal step for the ball."""
        dt = clamp(dt, 0.0, 0.1)
        self.elapsed += dt

        if self.state == "serve":
            self.timer = max(0.0, self.timer - dt)
            if self.timer == 0.0:
                self._launch()
                return [PongEvent("serve")]
            return []

        if self.state != "playing":
            return []

        events: list[PongEvent] = []
        self.accumulator += dt
        steps = 0
        while self.accumulator >= FIXED_DT and steps < 64:
            events.extend(self._fixed_step())
            self.accumulator -= FIXED_DT
            steps += 1
            if self.state != "playing":
                self.accumulator = 0.0
                break
        return events

    # -- physics ------------------------------------------------------------

    def _launch(self) -> None:
        angle = self.rng.uniform(-math.radians(10.0), math.radians(10.0))
        self.ball = Ball(
            x=0.0,
            y=self.rng.uniform(-0.45, 0.45),
            vx=self.serve_dir * SERVE_SPEED * math.cos(angle),
            vy=SERVE_SPEED * math.sin(angle),
        )
        self.timer = 0.0
        self.state = "playing"
        self.rally = 0

    def _fixed_step(self) -> list[PongEvent]:
        events: list[PongEvent] = []
        ball = self.ball
        ball.x += ball.vx * FIXED_DT
        ball.y += ball.vy * FIXED_DT

        wall = COURT_HALF_HEIGHT - BALL_RADIUS
        if ball.y > wall:
            ball.y = wall
            ball.vy = -abs(ball.vy)
            events.append(PongEvent("wall", x=ball.x, y=ball.y))
        elif ball.y < -wall:
            ball.y = -wall
            ball.vy = abs(ball.vy)
            events.append(PongEvent("wall", x=ball.x, y=ball.y))

        for player in (0, 1):
            side = -1.0 if player == 0 else 1.0
            paddle_x = side * PADDLE_X
            incoming = ball.vx * side > 0.0
            if not incoming:
                continue
            near_x = abs(ball.x - paddle_x) <= PADDLE_HALF_WIDTH + BALL_RADIUS
            near_y = (
                abs(ball.y - self.paddles[player])
                <= PADDLE_HALF_Y + BALL_RADIUS
            )
            if near_x and near_y:
                events.append(self._bounce(player, side))
                break

        if ball.x < -(COURT_HALF_WIDTH + OUT_MARGIN):
            events.extend(self._award_point(1))
        elif ball.x > COURT_HALF_WIDTH + OUT_MARGIN:
            events.extend(self._award_point(0))
        return events

    def _bounce(self, player: int, side: float) -> PongEvent:
        ball = self.ball
        paddle_y = self.paddles[player]
        contact = PADDLE_HALF_Y + BALL_RADIUS
        offset = clamp((ball.y - paddle_y) / contact, -1.0, 1.0)
        angle = offset * MAX_BOUNCE_ANGLE

        speed = min(MAX_SPEED, max(SERVE_SPEED, ball.speed) * SPEED_GAIN)
        out = -side
        ball.vx = out * speed * math.cos(angle)
        ball.vy = speed * math.sin(angle)
        ball.x = side * PADDLE_X + out * (PADDLE_HALF_WIDTH + BALL_RADIUS + 0.004)

        self.rally += 1
        self.longest_rally = max(self.longest_rally, self.rally)
        return PongEvent("paddle", player=player, x=ball.x, y=ball.y)

    def _award_point(self, player: int) -> list[PongEvent]:
        self.scores[player] += 1
        self.last_scorer = player
        events = [PongEvent("score", player=player, x=self.ball.x, y=self.ball.y)]
        self.ball = Ball()
        self.rally = 0

        if self.scores[player] >= self.win_score:
            self.winner = player
            self.state = "game_over"
            self.timer = 0.0
            events.append(PongEvent("win", player=player))
            return events

        self.state = "serve"
        self.timer = POINT_DELAY
        # El saque va hacia quien acaba de recibir el punto.
        self.serve_dir = 1 if player == 0 else -1
        return events


class CpuPaddle:
    """A beatable defender that predicts the ball with a little error."""

    def __init__(
        self,
        player: int,
        *,
        speed: float = 3.0,
        error: float = 0.65,
        track_after: float = 0.8,
    ) -> None:
        if player not in (0, 1):
            raise ValueError("player must be 0 or 1")
        self.player = player
        self.speed = speed
        self.error = error
        self.track_after = track_after
        self.y = 0.0
        self._phase = 1.3 if player == 0 else 2.7

    def update(self, match: PongMatch, dt: float) -> None:
        target = 0.0
        ball = match.ball
        side = -1.0 if self.player == 0 else 1.0

        approach = ball.x * side
        if match.state == "playing" and ball.vx * side > 0.0 and approach > self.track_after:
            travel = (side * PADDLE_X - ball.x) / ball.vx
            predicted = ball.y + ball.vy * travel
            wall = COURT_HALF_HEIGHT - BALL_RADIUS
            predicted = reflect(predicted, -wall, wall)
            wobble = self.error * math.sin(match.elapsed * 2.1 + self._phase)
            target = predicted + wobble

        target = clamp(target, -PADDLE_LIMIT, PADDLE_LIMIT)
        delta = clamp(target - self.y, -self.speed * dt, self.speed * dt)
        self.y = clamp(self.y + delta, -PADDLE_LIMIT, PADDLE_LIMIT)
        match.set_paddle(self.player, self.y)

    def sync(self, y: float) -> None:
        self.y = clamp(y, -PADDLE_LIMIT, PADDLE_LIMIT)
