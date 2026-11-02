"""Generate a high-resolution social preview image for MedFire Watch."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
OUTPUT_PATH = ROOT / "docs" / "media" / "social-preview.png"


def get_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidate_names = (
        ["segoeuib.ttf", "arialbd.ttf", "DejaVuSans-Bold.ttf"]
        if bold
        else ["segoeui.ttf", "arial.ttf", "DejaVuSans.ttf"]
    )
    for name in candidate_names:
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def generate_social_preview(output_path: Path = OUTPUT_PATH) -> None:
    width, height = 1280, 640
    # Dark dashboard background (#0e1117)
    image = Image.new("RGBA", (width, height), (14, 17, 23, 255))
    draw = ImageDraw.Draw(image)

    # Decorative background elements (dark subtle grid lines and radial/linear accents)
    grid_color = (24, 30, 42, 255)
    for x in range(0, width, 40):
        draw.line([(x, 0), (x, height)], fill=grid_color, width=1)
    for y in range(0, height, 40):
        draw.line([(0, y), (width, y)], fill=grid_color, width=1)

    # Top & Bottom accent gradient line (fire orange to deep red)
    accent_orange = (255, 87, 34, 255)
    accent_amber = (255, 171, 0, 255)
    accent_dark = (216, 67, 21, 255)

    for i in range(6):
        draw.line([(0, i), (width, i)], fill=accent_orange)
        draw.line([(0, height - 1 - i), (width, height - 1 - i)], fill=accent_dark)

    # Glowing badge pill at top
    tag_box = [80, 80, 310, 115]
    draw.rounded_rectangle(tag_box, radius=8, fill=(33, 41, 57, 255), outline=accent_orange, width=1)
    tag_font = get_font(18, bold=True)
    draw.text((100, 87), "WILDFIRE INTELLIGENCE", font=tag_font, fill=accent_amber)

    # Project Title
    title_font = get_font(68, bold=True)
    draw.text((80, 135), "MedFire Watch", font=title_font, fill=(255, 255, 255, 255))

    # Accent fire icon / dot
    draw.ellipse([580, 150, 604, 174], fill=accent_orange)

    # Subtitle
    sub_font = get_font(28, bold=False)
    subtitle_lines = [
        "Wildfire & Smoke Detection with YOLOv8",
        "NASA Satellite Hotspots, Fire-Weather Risk & Telegram Alerts",
    ]
    draw.text((80, 235), subtitle_lines[0], font=sub_font, fill=(220, 225, 235, 255))
    draw.text((80, 275), subtitle_lines[1], font=sub_font, fill=(160, 170, 185, 255))

    # Metric feature cards
    cards = [
        ("0.747 mAP50", "D-Fire official test split"),
        ("205.8 FPS", "GPU video analysis (batch 8)"),
        ("24h Hotspots", "NASA VIIRS global satellite"),
        ("Telegram Bot", "Live camera persistent alerts"),
    ]

    card_x = 80
    card_y = 360
    card_w = 260
    card_h = 130
    gap = 20

    for i, (metric, label) in enumerate(cards):
        x0 = card_x + i * (card_w + gap)
        y0 = card_y
        x1 = x0 + card_w
        y1 = y0 + card_h

        # Card container
        draw.rounded_rectangle([x0, y0, x1, y1], radius=10, fill=(21, 26, 36, 255), outline=(45, 55, 75, 255), width=1)
        # Accent top bar for card
        draw.rounded_rectangle([x0, y0, x1, y0 + 4], radius=2, fill=accent_orange)

        metric_font = get_font(26, bold=True)
        draw.text((x0 + 16, y0 + 26), metric, font=metric_font, fill=(255, 255, 255, 255))

        label_font = get_font(16, bold=False)
        draw.text((x0 + 16, y0 + 72), label, font=label_font, fill=(150, 160, 175, 255))

    # Bottom metadata footer
    footer_font = get_font(18, bold=False)
    footer_text = "AGPL-3.0 License  •  FastAPI + Streamlit  •  PyTorch + YOLOv8"
    draw.text((80, 560), footer_text, font=footer_font, fill=(110, 120, 135, 255))
    draw.text((1020, 560), "github.com/jasser-z/medfire-watch", font=footer_font, fill=(140, 155, 175, 255))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    # Convert RGBA to RGB for optimized saving
    rgb_image = image.convert("RGB")
    rgb_image.save(output_path, format="PNG", optimize=True)
    size_kb = output_path.stat().st_size / 1024
    print(f"Generated {output_path} ({width}x{height}, {size_kb:.1f} KB)")


if __name__ == "__main__":
    generate_social_preview()

