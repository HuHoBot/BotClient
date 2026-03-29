from PIL import Image, ImageDraw, ImageFont

from libs.configManager import ConfigManager

_config_manager = ConfigManager()

# Minecraft 格式映射（颜色+样式）
MC_COLORS = {
    '0': (0, 0, 0),  # 黑色
    '1': (0, 0, 170),  # 深蓝色
    '2': (0, 170, 0),  # 深绿色
    '3': (0, 170, 170),  # 青色
    '4': (170, 0, 0),  # 深红色
    '5': (170, 0, 170),  # 紫色
    '6': (255, 170, 0),  # 金色
    '7': (170, 170, 170),  # 浅灰色
    '8': (85, 85, 85),  # 深灰色
    '9': (85, 85, 255),  # 蓝色
    'a': (85, 255, 85),  # 绿色
    'b': (85, 255, 255),  # 浅青色
    'c': (255, 85, 85),  # 红色
    'd': (255, 85, 255),  # 粉色
    'e': (255, 255, 85),  # 黄色
    'f': (255, 255, 255),  # 白色
    'g': (221, 214, 5),  # minecoin_gold
    'h': (227, 212, 209),  # material_quartz
    'i': (206, 202, 202),  # material_iron
    'j': (68, 58, 59),  # material_netherite
    #'m': (151, 22, 7),  # material_redstone
    #'n': (180, 104, 77),  # material_copper
    'p': (222, 177, 45),  # material_gold
    'q': (17, 160, 54),  # material_emerald
    's': (44, 186, 168),  # material_diamond
    't': (33, 73, 123),  # material_lapis
    'u': (154, 92, 198),  # material_amethyst
    'v': (235, 114, 20),  # material_resin
}

MC_STYLES = {
    'l': 'bold',  # 粗体
    'o': 'italic',  # 斜体
    'n': 'underline',  # 下划线
    'm': 'strikethrough',  # 删除线
    'k': 'random',  # 随机（暂不实现）
    'r': 'reset',  # 重置所有样式
}

def render_mc_text(text, font_path, font_size=12, bg_color=(0, 0, 0, 255), max_line_width=600, scale=2):
    """
    渲染Minecraft风格文本，支持颜色和样式
    """
    # 预处理：每行末尾添加§r确保样式重置
    text = '\n'.join([line + '§r' for line in text.split('\n')])

    scaled_font_size = font_size * scale
    font = ImageFont.truetype(font_path, scaled_font_size)
    draw_temp = ImageDraw.Draw(Image.new('RGBA', (1, 1)))

    # 解析§格式：逐字符拆分并标记样式
    segments = []
    current_color = MC_COLORS['f']
    current_styles = set()
    i = 0
    while i < len(text):
        if text[i] == '§' and i + 1 < len(text):
            code = text[i + 1].lower()
            if code in MC_COLORS:
                current_color = MC_COLORS[code]
                i += 2
            elif code in MC_STYLES:
                style = MC_STYLES[code]
                if style == 'reset':
                    current_color = MC_COLORS['f']
                    current_styles = set()
                else:
                    current_styles ^= {style}  # 切换样式
                i += 2
            else:
                i += 1  # 跳过无效代码
        else:
            # 逐个字符解析，确保样式精确到每个字符
            char = text[i]
            segments.append(
                {
                    'char': char,
                    'color': current_color,
                    'styles': current_styles.copy()
                }
            )
            i += 1

    # 自动换行处理
    lines = []
    current_line = []
    current_line_width = 0
    for seg in segments:
        if seg['char'] == '\n':
            lines.append(current_line)
            current_line = []
            current_line_width = 0
            continue
        char_width = draw_temp.textbbox((0, 0), seg['char'], font=font)[2]
        scaled_max_width = max_line_width * scale
        if current_line_width + char_width > scaled_max_width and current_line:
            lines.append(current_line)
            current_line = []
            current_line_width = 0
        current_line.append(seg)
        current_line_width += char_width
    if current_line:
        lines.append(current_line)

    # 计算图片尺寸
    max_width = 0
    total_height = 0
    for line in lines:
        if not line:
            total_height += scaled_font_size
            continue
        line_width = 0
        for seg in line:
            line_width += draw_temp.textbbox((0, 0), seg['char'], font=font)[2]
        max_width = max(max_width, line_width)
        total_height += scaled_font_size

    img_width = max_width + 20 * scale
    img_height = total_height + 20 * scale
    img = Image.new('RGBA', (img_width, img_height), bg_color)
    draw = ImageDraw.Draw(img)
    y = 10 * scale

    # 绘制文字与强制样式
    for line in lines:
        if not line:
            y += scaled_font_size
            continue
        x = 10 * scale
        for seg in line:
            # 绘制基础文字
            draw.text((x, y), seg['char'], font=font, fill=seg['color'], antialias=True)

            # 强制计算字符尺寸
            char_bbox = draw_temp.textbbox((0, 0), seg['char'], font=font)
            char_width = char_bbox[2] - char_bbox[0]
            char_height = char_bbox[3] - char_bbox[1]

            # 强制渲染所有样式
            for style in seg['styles']:
                if style == 'bold':
                    # 粗体：在原位置左右上下各加1像素
                    draw.text((x + 1, y), seg['char'], font=font, fill=seg['color'], antialias=True)
                    draw.text((x, y + 1), seg['char'], font=font, fill=seg['color'], antialias=True)
                elif style == 'underline':
                    # 下划线：使用字符底部作为基准
                    underline_y = y + char_bbox[3] - (2 * scale) +2
                    draw.line(
                        (x, underline_y, x + char_width, underline_y),
                        fill=seg['color'],
                        width=2 * scale
                    )
                elif style == 'strikethrough':
                    # 删除线：使用字符中心作为基准
                    strike_y = y + char_height - 5*scale
                    draw.line(
                        (x, strike_y, x + char_width, strike_y),
                        fill=seg['color'],
                        width=2 * scale
                    )
                elif style == 'italic':
                    # 斜体：向右下偏移
                    draw.text((x + 2, y + 1), seg['char'], font=font, fill=seg['color'], antialias=True)

            x += char_width
        y += scaled_font_size

    # 缩放图片以提升清晰度
    target_width = img_width // scale
    target_height = img_height // scale
    img = img.resize((target_width, target_height), Image.LANCZOS)

    return img

def generate_img(text,fileName="minecraft_styles_fixed"):
    """
    生成图片并保存为文件
    """
    font_path = _config_manager.get('TtfPath', ConfigManager.DEFAULT_TTF_PATH)
    image = render_mc_text(text, font_path, font_size=30, max_line_width=1000, scale=10)
    image.save("imgs/"+fileName+".png")
    return "imgs/"+fileName+".png"

# 调用示例（确保§格式正确）
if __name__ == "__main__":
    mc_text = """--- Server Status ---
Uptime: §a1 days 7 hours 2 minutes 16 seconds
Used VM memory: §a1197.81 MB (58.49%)
Total VM memory: §a1522.0 MB
Maximum JVM memory: §a2048.0 MB
Players: §a0/20


--- Worlds Status ---
- world
  TPS: §a20.0
  MSPT: §a0.9060486
  TickUsage: §a1.8120972%
  Chunks: §a29
  Entities: §a0
  BlockEntities: §a5


- backrooms
  TPS: §a20.0
  MSPT: §a0.3295191
  TickUsage: §a0.6590382%
  Chunks: §a29
  Entities: §a0
  BlockEntities: §a0


"""
    generate_img(mc_text)

    print("带完整强制样式的图片生成完成！")
