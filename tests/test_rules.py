from __future__ import annotations

import math
import random

import pytest

from pong.rules import (
    BALL_RADIUS,
    COURT_HALF_HEIGHT,
    COURT_HALF_WIDTH,
    FIXED_DT,
    OUT_MARGIN,
    PADDLE_LIMIT,
    PADDLE_X,
    SERVE_SPEED,
    Ball,
    CpuPaddle,
    PongMatch,
    paddle_from_tilt,
    paddle_from_touch_x,
    sensors_available,
)


def launched_match() -> PongMatch:
    match = PongMatch(rng=random.Random(7))
    match.serve_now()
    assert match.state == "playing"
    return match


def test_paddle_position_is_clamped() -> None:
    match = PongMatch()
    match.set_paddle(0, 99.0)
    match.set_paddle(1, -99.0)

    assert match.paddles[0] == pytest.approx(PADDLE_LIMIT)
    assert match.paddles[1] == pytest.approx(-PADDLE_LIMIT)


def test_touch_x_maps_to_each_players_screen() -> None:
    assert paddle_from_touch_x(0.0, -1) == pytest.approx(PADDLE_LIMIT)
    assert paddle_from_touch_x(1.0, -1) == pytest.approx(-PADDLE_LIMIT)
    assert paddle_from_touch_x(0.0, 1) == pytest.approx(-PADDLE_LIMIT)
    assert paddle_from_touch_x(1.0, 1) == pytest.approx(PADDLE_LIMIT)
    assert paddle_from_touch_x(0.5, 1) == pytest.approx(0.0)


def test_tilt_maps_to_each_players_screen() -> None:
    assert paddle_from_tilt(0.0, -1) == pytest.approx(0.0)
    assert paddle_from_tilt(30.0, -1) == pytest.approx(-PADDLE_LIMIT)
    assert paddle_from_tilt(-30.0, -1) == pytest.approx(PADDLE_LIMIT)
    assert paddle_from_tilt(30.0, 1) == pytest.approx(PADDLE_LIMIT)
    assert paddle_from_tilt(-30.0, 1) == pytest.approx(-PADDLE_LIMIT)
    assert paddle_from_tilt(2.0, 1) == pytest.approx(0.0)


def test_sensor_detection_accepts_motion_data() -> None:
    assert sensors_available((0.0, 0.0, 1.0), (0.0, 0.0, 0.0), (0.0, 0.0, 0.0))
    assert sensors_available((0.0, 0.0, 0.0), (0.0, 0.0, 9.81), (0.0, 0.0, 0.0))
    assert not sensors_available(
        (0.0, 0.0, 0.0),
        (0.0, 0.0, 0.0),
        (0.0, 0.0, 0.0),
    )


def test_serve_waits_then_launches() -> None:
    match = PongMatch(rng=random.Random(2))
    for _ in range(15):
        assert match.advance(0.1) == []
    assert match.state == "serve"

    events = match.advance(0.1)
    assert [event.kind for event in events] == ["serve"]
    assert match.state == "playing"
    assert match.ball.speed == pytest.approx(SERVE_SPEED)


def test_paddle_returns_the_ball() -> None:
    match = launched_match()
    match.ball = Ball(x=-(PADDLE_X - 0.10), y=0.0, vx=-6.0, vy=0.0)

    events = match.advance(FIXED_DT)

    assert match.ball.vx > 0.0
    assert match.ball.x > -PADDLE_X
    assert match.rally == 1
    assert [event.kind for event in events] == ["paddle"]
    assert events[0].player == 0


def test_paddle_edge_sends_ball_at_an_angle() -> None:
    match = launched_match()
    match.ball = Ball(x=-(PADDLE_X - 0.10), y=0.70, vx=-6.0, vy=0.0)
    match.set_paddle(0, 0.0)

    match.advance(FIXED_DT)

    assert match.ball.vx > 0.0
    assert match.ball.vy > 0.0
    assert math.hypot(match.ball.vx, match.ball.vy) >= SERVE_SPEED


def test_top_wall_bounces_without_leaving_the_court() -> None:
    match = launched_match()
    match.ball = Ball(x=0.0, y=COURT_HALF_HEIGHT - BALL_RADIUS, vx=1.0, vy=5.0)

    events = match.advance(FIXED_DT)

    assert match.ball.vy < 0.0
    assert match.ball.y <= COURT_HALF_HEIGHT - BALL_RADIUS
    assert "wall" in [event.kind for event in events]


def test_point_goes_to_the_other_player_and_serve_changes_side() -> None:
    match = launched_match()
    match.ball = Ball(x=-(COURT_HALF_WIDTH + OUT_MARGIN + 0.1), y=0.0, vx=-1.0)

    events = match.advance(FIXED_DT)

    assert match.scores == [0, 1]
    assert match.state == "serve"
    assert match.serve_dir == -1
    assert match.timer == pytest.approx(1.1)
    assert [event.kind for event in events] == ["score"]


def test_match_ends_at_seven_and_restarts() -> None:
    match = launched_match()
    match.scores = [6, 2]
    match.ball = Ball(x=COURT_HALF_WIDTH + OUT_MARGIN + 0.1, y=0.0, vx=1.0)

    events = match.advance(FIXED_DT)

    assert match.scores == [7, 2]
    assert match.winner == 0
    assert match.state == "game_over"
    assert [event.kind for event in events] == ["score", "win"]

    match.restart()
    assert match.scores == [0, 0]
    assert match.winner is None
    assert match.state == "serve"
    assert match.paddles == [0.0, 0.0]


def test_cpu_moves_towards_an_incoming_ball() -> None:
    match = launched_match()
    match.ball = Ball(x=1.2, y=2.2, vx=5.0, vy=0.0)
    cpu = CpuPaddle(1)

    for _ in range(60):
        cpu.update(match, 1.0 / 60.0)

    assert cpu.y > 1.5
    assert cpu.y <= PADDLE_LIMIT
    assert match.paddles[1] == pytest.approx(cpu.y)


def test_cpu_waits_near_the_center_during_serve() -> None:
    match = PongMatch()
    cpu = CpuPaddle(0)
    cpu.sync(PADDLE_LIMIT)

    for _ in range(60):
        cpu.update(match, 1.0 / 60.0)

    assert abs(cpu.y) < 0.15


def test_long_cpu_rally_stays_finite() -> None:
    match = PongMatch(rng=random.Random(11))
    cpus = [CpuPaddle(0), CpuPaddle(1)]

    for _ in range(60 * 45):
        for cpu in cpus:
            cpu.update(match, 1.0 / 60.0)
        match.advance(1.0 / 60.0)
        if match.state == "game_over":
            match.restart()

        assert math.isfinite(match.ball.x)
        assert math.isfinite(match.ball.y)
        assert math.isfinite(match.ball.vx)
        assert math.isfinite(match.ball.vy)
        assert -PADDLE_LIMIT <= match.paddles[0] <= PADDLE_LIMIT
        assert -PADDLE_LIMIT <= match.paddles[1] <= PADDLE_LIMIT
        assert abs(match.ball.y) <= COURT_HALF_HEIGHT
        assert match.scores[0] <= 7
        assert match.scores[1] <= 7
