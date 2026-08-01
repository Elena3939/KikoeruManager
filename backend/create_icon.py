"""
生成应用图标
"""
from PIL import Image, ImageDraw

def create_app_icon():
    # 创建 256x256 的透明图像
    img = Image.new('RGBA', (256, 256), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    
    # 绘制圆形背景（蓝色渐变）
    draw.ellipse([10, 10, 246, 246], fill=(66, 133, 244, 255))
    
    # 绘制内圈
    draw.ellipse([20, 20, 236, 236], fill=(76, 143, 254, 255))
    
    # 绘制字母 "K"（代表 Kikoeru）
    # 先画竖线
    draw.rectangle([80, 60, 110, 196], fill=(255, 255, 255, 255))
    # 画左斜线
    draw.polygon([(110, 60), (110, 90), (160, 128), (160, 100), (110, 60)], fill=(255, 255, 255, 255))
    # 画右斜线
    draw.polygon([(110, 196), (110, 166), (170, 128), (170, 156), (110, 196)], fill=(255, 255, 255, 255))
    
    # 保存为多个尺寸的 ICO 文件
    icon_sizes = [256, 128, 64, 48, 32, 16]
    
    # 创建不同尺寸的图像
    images = []
    for size in icon_sizes:
        resized = img.resize((size, size), Image.Resampling.LANCZOS)
        images.append(resized)
    
    # 保存为 ICO 文件
    ico_path = 'app.ico'
    images[0].save(
        ico_path,
        format='ICO',
        sizes=[(s, s) for s in icon_sizes],
        append_images=images[1:]
    )
    
    print(f"图标已生成：{ico_path}")
    return ico_path

if __name__ == '__main__':
    create_app_icon()
