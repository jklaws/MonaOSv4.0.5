import math
import badgeware  # noqa: F401

screen.antialias = X2

mona = image.load("assets/mona.png")
large_font = pixel_font.load("/system/assets/fonts/ignore.ppf")
small_font = pixel_font.load("/system/assets/fonts/ark.ppf")

tile_colors = [
  None,
  color.rgb(3, 58, 22),
  color.rgb(25, 108, 46),
  color.rgb(46, 160, 67),
  color.rgb(46, 160, 67),
  color.rgb(86, 211, 100),
  color.rgb(3, 58, 22),
  color.rgb(25, 108, 46),
  color.rgb(46, 160, 67),
  color.rgb(25, 108, 46),
]

def draw_status(complete):
  screen.blit(mona, vec2(0, 72))
  screen.font = small_font
  screen.pen = color.rgb(255, 255, 255)
  screen.text("mona's quest", 65, 0)

  screen.font = large_font
  screen.text(f"{len(complete)}/9", 5, 8)
  screen.font = small_font
  screen.pen = color.rgb(140, 160, 180)
  screen.text("found", 7, 30)


def draw_tiles(complete):
  # define tile shape and set position of tile grid
  tile = shape.squircle(0, 0, 1, 6)
  pos = (70, 31)
  screen.font = large_font

  for y in range(0, 3):
    for x in range(0, 3):
      # animate the inactive tile borders
      pulse = (math.sin(badge.ticks / 250 + (x + y)) / 2) + 0.5
      pulse = 0.8 + (pulse / 2)

      # tile label
      index = x + (y * 3) + 1
      label = str(index)

      # determine centre point of tile
      xo, yo = x * 34, y * 34

      # calculate label position in tile
      label_pos = (xo + pos[0] - 6, yo + pos[1] - 15)

      if index in complete:
        screen.pen = tile_colors[index]
        tile.transform = mat3().translate(*pos).translate(xo, yo).scale(16)
        screen.shape(tile)
        screen.pen = color.rgb(255, 255, 255, int(150 * pulse))
        screen.text(label, int(label_pos[0]), int(label_pos[1]))
      else:
        border_brush = color.rgb(int(50 * pulse), int(60 * pulse), int(70 * pulse))
        tile.transform = mat3().translate(*pos).translate(xo, yo).scale(16)
        screen.pen = border_brush
        screen.shape(tile)
        screen.pen = color.rgb(21, 27, 35)
        tile.transform = mat3().translate(*pos).translate(xo, yo).scale(14)
        screen.shape(tile)
        screen.pen = border_brush
        screen.text(label, int(label_pos[0]), int(label_pos[1]))
