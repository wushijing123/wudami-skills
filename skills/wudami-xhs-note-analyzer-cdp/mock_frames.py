import os
from PIL import Image, ImageDraw

os.makedirs('outputs/_frames', exist_ok=True)
for i in range(1, 10):
    img = Image.new('RGB', (320, 180), color=(73, 109, i*25))
    d = ImageDraw.Draw(img)
    d.text((10,10), f"Mock Frame {i}", fill=(255,255,0))
    img.save(f'outputs/_frames/frame_{i:03d}.jpg')
