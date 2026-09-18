"""生成 Gitee 第三方应用可上传的 Logo（512x512，PNG + JPG，均远小于 2MB）。

用法：python scripts/_mk_gitee_logo.py
产物：.workbuddy/artifacts/gitee-real-creation/aioa-logo.{png,jpg}
"""
import os

from PIL import Image, ImageDraw, ImageFont

S = 512
OUT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    ".workbuddy", "artifacts", "gitee-real-creation",
)
os.makedirs(OUT, exist_ok=True)

img = Image.new("RGBA", (S, S), (0, 0, 0, 0))

# 圆角方形竖向渐变底：深蓝 -> 青
top, bot = (18, 52, 116), (0, 150, 168)
grad = Image.new("RGB", (1, S))
for y in range(S):
    t = y / (S - 1)
    grad.putpixel((0, y), tuple(int(top[i] + (bot[i] - top[i]) * t) for i in range(3)))
grad = grad.resize((S, S))

mask = Image.new("L", (S, S), 0)
ImageDraw.Draw(mask).rounded_rectangle([0, 0, S - 1, S - 1], radius=112, fill=255)
img.paste(grad, (0, 0), mask)

d = ImageDraw.Draw(img)
font_path = r"C:\Windows\Fonts\msyhbd.ttc"
f_big = ImageFont.truetype(font_path, 176)
f_small = ImageFont.truetype(font_path, 46)

txt = "AIOA"
bb = d.textbbox((0, 0), txt, font=f_big)
w, h = bb[2] - bb[0], bb[3] - bb[1]
d.text(((S - w) / 2 - bb[0], (S - h) / 2 - bb[1] - 36), txt, font=f_big, fill=(255, 255, 255, 255))

sub = "AI 公共服务平台"
bb2 = d.textbbox((0, 0), sub, font=f_small)
d.text(((S - (bb2[2] - bb2[0])) / 2 - bb2[0], S / 2 + 92), sub, font=f_small, fill=(226, 243, 255, 240))

png = os.path.join(OUT, "aioa-logo.png")
jpg = os.path.join(OUT, "aioa-logo.jpg")
img.convert("RGB").save(png, "PNG", optimize=True)
img.convert("RGB").save(jpg, "JPEG", quality=92)
for p in (png, jpg):
    print(os.path.basename(p), os.path.getsize(p), "bytes", Image.open(p).size)
