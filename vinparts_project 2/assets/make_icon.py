"""Рисует значок приложения (список деталей с цветными метками). Запуск: python assets/make_icon.py"""
from pathlib import Path

from PIL import Image, ImageDraw

OUT = Path(__file__).parent
INK, PAPER = (23, 33, 43, 255), (242, 244, 243, 255)
ROLES = [(179, 38, 30, 255), (214, 150, 20, 255), (29, 90, 138, 255)]   # обязательно / рекомендуется / по состоянию


def draw(size: int = 1024) -> Image.Image:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    u = size / 100
    d.rounded_rectangle([4 * u, 4 * u, 96 * u, 96 * u], radius=20 * u, fill=INK)
    for i, color in enumerate(ROLES):
        y = (24 + i * 22) * u
        d.rounded_rectangle([16 * u, y, 25 * u, y + 14 * u], radius=2 * u, fill=color)          # цветная метка
        d.rounded_rectangle([31 * u, y, (84 - i * 10) * u, y + 14 * u], radius=4 * u, fill=PAPER)  # строка
    # жёлтая подсветка, как на странице руководства
    d.rounded_rectangle([31 * u, 46 * u, (74) * u, 60 * u], radius=4 * u, fill=(255, 214, 0, 255))
    return img


if __name__ == "__main__":
    big = draw()
    big.resize((256, 256), Image.LANCZOS).save(OUT / "icon.png")
    big.resize((64, 64), Image.LANCZOS).save(OUT / "favicon.png")
    big.save(OUT / "icon.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    big.save(OUT / "icon.icns")
    print("готово:", sorted(p.name for p in OUT.iterdir()))
