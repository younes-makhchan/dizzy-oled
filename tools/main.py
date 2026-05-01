from pathlib import Path
from collections import deque

import numpy as np
from PIL import Image, ImageOps
import imageio.v2 as imageio


# =========================
# SETTINGS
# =========================

SOURCE_IMAGE = "frame2.png"

OLED_W = 128
OLED_H = 64

FPS = 12
VIDEO_LOOPS = 3

# For preview video:
# False = smoother preview
# True  = hard black/white 1-bit style
BINARY_VIDEO = False

OUT_DIR = Path("blink_output")
OUT_DIR.mkdir(exist_ok=True)

FRAMES_DIR = OUT_DIR / "frames_png"
FRAMES_BW_DIR = OUT_DIR / "frames_bw_for_oled"

FRAMES_DIR.mkdir(exist_ok=True)
FRAMES_BW_DIR.mkdir(exist_ok=True)


try:
    RESAMPLE_LANCZOS = Image.Resampling.LANCZOS
    RESAMPLE_NEAREST = Image.Resampling.NEAREST
except AttributeError:
    RESAMPLE_LANCZOS = Image.LANCZOS
    RESAMPLE_NEAREST = Image.NEAREST


# =========================
# LOAD AND FIT IMAGE
# =========================

src = Image.open(SOURCE_IMAGE).convert("L")

base_gray = ImageOps.fit(
    src,
    (OLED_W, OLED_H),
    method=RESAMPLE_LANCZOS,
    centering=(0.5, 0.5),
)

base_gray.save(OUT_DIR / "debug_base_128x64.png")

# Detection mask.
# White objects become True.
mask = np.array(base_gray) > 40


# =========================
# CONNECTED COMPONENT DETECTION
# =========================

def find_components(binary_mask):
    h, w = binary_mask.shape
    visited = np.zeros_like(binary_mask, dtype=bool)

    components = []

    for y in range(h):
        for x in range(w):
            if not binary_mask[y, x] or visited[y, x]:
                continue

            q = deque()
            q.append((x, y))
            visited[y, x] = True

            pixels = []

            while q:
                px, py = q.popleft()
                pixels.append((px, py))

                for nx, ny in (
                    (px + 1, py),
                    (px - 1, py),
                    (px, py + 1),
                    (px, py - 1),
                ):
                    if nx < 0 or ny < 0 or nx >= w or ny >= h:
                        continue

                    if visited[ny, nx]:
                        continue

                    if not binary_mask[ny, nx]:
                        continue

                    visited[ny, nx] = True
                    q.append((nx, ny))

            xs = [p[0] for p in pixels]
            ys = [p[1] for p in pixels]

            x1 = min(xs)
            y1 = min(ys)
            x2 = max(xs) + 1
            y2 = max(ys) + 1

            components.append({
                "box": (x1, y1, x2, y2),
                "area": len(pixels),
                "center": ((x1 + x2) / 2, (y1 + y2) / 2),
            })

    return components


components = find_components(mask)

# Remove tiny noise
components = [c for c in components if c["area"] > 10]

if len(components) < 2:
    raise RuntimeError(
        "Could not find the eyes. Make sure frame1.png has white eyes on a black background."
    )

# Two biggest white components are the eyes
components_sorted = sorted(components, key=lambda c: c["area"], reverse=True)

eye_components = components_sorted[:2]
fixed_components = components_sorted[2:]

# Sort eyes left-to-right
eye_components = sorted(eye_components, key=lambda c: c["center"][0])

print("Detected eyes:")
for i, eye in enumerate(eye_components):
    print(f"Eye {i + 1}: box={eye['box']}, area={eye['area']}")

print("Detected fixed parts:")
for part in fixed_components:
    print(f"Fixed: box={part['box']}, area={part['area']}")


# =========================
# SPRITE HELPERS
# =========================

def make_white_sprite_from_box(img_gray, box, padding=2):
    x1, y1, x2, y2 = box

    x1 = max(0, x1 - padding)
    y1 = max(0, y1 - padding)
    x2 = min(OLED_W, x2 + padding)
    y2 = min(OLED_H, y2 + padding)

    crop = img_gray.crop((x1, y1, x2, y2)).convert("L")

    # White pixels become opacity.
    # Black stays transparent.
    rgba = Image.new("RGBA", crop.size, (255, 255, 255, 0))
    rgba.putalpha(crop)

    cx = (x1 + x2) / 2
    cy = (y1 + y2) / 2

    return {
        "sprite": rgba,
        "box": (x1, y1, x2, y2),
        "center": (cx, cy),
    }


eye_sprites = [
    make_white_sprite_from_box(base_gray, eye["box"], padding=2)
    for eye in eye_components
]

fixed_sprites = [
    make_white_sprite_from_box(base_gray, part["box"], padding=1)
    for part in fixed_components
]


def paste_centered(canvas, sprite, cx, cy):
    x = int(round(cx - sprite.width / 2))
    y = int(round(cy - sprite.height / 2))
    canvas.alpha_composite(sprite, (x, y))


def make_blink_frame(height_factor):
    """
    height_factor:
      1.0 = eyes fully open
      0.5 = half blink
      0.08 = nearly closed
    """

    canvas = Image.new("RGBA", (OLED_W, OLED_H), (0, 0, 0, 255))

    for eye in eye_sprites:
        sprite = eye["sprite"]
        cx, cy = eye["center"]

        new_w = sprite.width
        new_h = max(2, int(round(sprite.height * height_factor)))

        squeezed = sprite.resize(
            (new_w, new_h),
            RESAMPLE_LANCZOS,
        )

        paste_centered(canvas, squeezed, cx, cy)

    # Paste nose / mouth / other fixed parts without blinking
    for part in fixed_sprites:
        paste_centered(canvas, part["sprite"], part["center"][0], part["center"][1])

    frame = canvas.convert("L")

    if BINARY_VIDEO:
        frame = frame.point(lambda p: 255 if p > 127 else 0).convert("L")

    return frame


# =========================
# BLINK ANIMATION SEQUENCE
# =========================

# This sequence gives:
# open hold -> close quickly -> open again -> hold
blink_sequence = (
    [1.00] * 14 +
    [0.75, 0.50, 0.28, 0.10, 0.28, 0.50, 0.75] +
    [1.00] * 12
)

video_frames = []

for i, factor in enumerate(blink_sequence):
    frame = make_blink_frame(factor)

    # Save normal preview PNG
    frame.save(FRAMES_DIR / f"frame_{i:03d}.png")

    # Save OLED-ready hard black/white PNG
    bw = frame.point(lambda p: 255 if p > 127 else 0).convert("1")
    bw.save(FRAMES_BW_DIR / f"frame_{i:03d}.png")

    # MP4 wants uint8 RGB frames, not bool mode
    video_frames.append(np.array(frame.convert("RGB"), dtype=np.uint8))


# Repeat animation in video
video_frames_looped = video_frames * VIDEO_LOOPS

# =========================
# SAVE MP4
# =========================

imageio.mimsave(
    OUT_DIR / "blink.mp4",
    video_frames_looped,
    fps=FPS,
    macro_block_size=None,
)

# =========================
# SAVE GIF
# =========================

gif_images = [Image.fromarray(f) for f in video_frames_looped]

gif_images[0].save(
    OUT_DIR / "blink.gif",
    save_all=True,
    append_images=gif_images[1:],
    duration=int(1000 / FPS),
    loop=0,
)

print("")
print("Done.")
print(f"Video saved: {OUT_DIR / 'blink.mp4'}")
print(f"GIF saved:   {OUT_DIR / 'blink.gif'}")
print(f"PNG frames:  {FRAMES_DIR}")
print(f"OLED frames: {FRAMES_BW_DIR}")