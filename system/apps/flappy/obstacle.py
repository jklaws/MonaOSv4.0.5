import random
# v2.0.2 port: badgeware injects builtins (SpriteSheet, screen, rect, badge, ...).
import badgeware  # noqa: F401

sprites = SpriteSheet("assets/obstacles.png", 2, 1)


def _scale_blit(img, x, y, w, h):
    # Port of old badgeware screen.scale_blit(img, x, y, w, h).
    # v2.0.2: screen.blit(src, dest_rect) scales src into the rect.
    # Old API used negative w/h to flip; v2.0.2 blit has no direct flip, so we
    # draw un-flipped using abs() dims (vertical spikes won't mirror yet).
    dx, dy = x, y
    if w < 0:
        dx = x + w
        w = -w
    if h < 0:
        dy = y + h
        h = -h
    if w < 1:
        w = 1
    if h < 1:
        h = 1
    screen.blit(img, rect(int(dx), int(dy), int(w), int(h)))


class Obstacle:
    # the list of active obstacles
    obstacles = []
    next_spawn_time = None

    def spawn():
        # create a new obstacle and reset the obstacle spawn timer
        Obstacle.obstacles.append(Obstacle())
        Obstacle.next_spawn_time = badge.ticks + 1500

        # clean up any obstacles that are now off screen and can be removed
        Obstacle.obstacles = [o for o in Obstacle.obstacles if o.x > -24]

    def __init__(self):
        # position the new obstacle off the right hand side of the screen and
        # randomise the height of the gap
        self.x = screen.width
        self.gap_height = 60
        self.gap_y = random.randint(15, screen.height - self.gap_height - 15)

        # when mona passes an obstacle we flag it so the score is only increased once
        self.passed = False

    def update(self):
        # moves the obstacle to the left by one pixel each frame
        self.x -= 1

    def bounds(self):
        # be a little generous with obstacle bounding boxes for collisions
        return (
            (self.x, 0, 24, self.gap_y - 2),
            (self.x, self.gap_y + self.gap_height + 2,
                24, 120 - (self.gap_y + self.gap_height + 2))
        )

    def draw(self):
        # draw the top half off the obstacle
        _scale_blit(sprites.sprite(0, 0), self.x,
                    self.gap_y - 72, 24, 24)
        _scale_blit(sprites.sprite(0, 0), self.x,
                    self.gap_y - 48, 24, 24)
        _scale_blit(sprites.sprite(1, 0), self.x,
                    self.gap_y - 24, 24, 24)  # spikes, yikes!

        # draw the bottom half off the obstacle
        _scale_blit(sprites.sprite(1, 0), self.x, self.gap_y +
                    self.gap_height, 24, -24)  # spikes, yikes!
        _scale_blit(sprites.sprite(0, 0), self.x,
                    self.gap_y + self.gap_height + 24, 24, -24)
        _scale_blit(sprites.sprite(0, 0), self.x,
                    self.gap_y + self.gap_height + 48, 24, -24)
