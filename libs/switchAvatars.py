import math
import uuid
from io import BytesIO
from pathlib import Path

import aiohttp
from PIL import Image, ImageDraw
from ymbotpy import logging

from libs.basic import GetQLogoUrl
from libs.configManager import ConfigManager

_log = logging.get_logger()
_config_manager = ConfigManager()
COMPARE_IMAGE_PATH = Path("imgs") / "compare.png"


async def _DownloadImage(session, url, timeout=5):
    """异步下载图片，并直接返回 `PIL.Image` 对象。"""
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=timeout)) as response:
            if response.status == 200:
                data = await response.read()
                image = Image.open(BytesIO(data))
                image.load()
                return image
            return None
    except Exception as e:
        _log.error(f"下载失败: {e}")
        return None


def _PrepareAvatar(image: Image.Image, size: int) -> Image.Image:
    """把头像裁剪为居中的正方形并缩放。"""
    image = image.convert("RGBA")
    min_side = min(image.size)
    left = (image.width - min_side) // 2
    top = (image.height - min_side) // 2
    image = image.crop((left, top, left + min_side, top + min_side))
    return image.resize((size, size), Image.LANCZOS)


def _ApplyRoundMask(image: Image.Image, radius: int) -> Image.Image:
    """给图片应用圆角透明蒙版。"""
    image = image.convert("RGBA")
    mask = Image.new("L", image.size, 0)
    draw = ImageDraw.Draw(mask)
    draw.rounded_rectangle((0, 0, image.width, image.height), radius=radius, fill=255)
    image.putalpha(mask)
    return image


def _LoadCompareImage(size: int) -> Image.Image:
    """读取头像对比中间图标。"""
    compare_image = Image.open(COMPARE_IMAGE_PATH)
    compare_image.load()
    return compare_image.convert("RGBA").resize((size, size), Image.LANCZOS)


def _RenderAvatarCompareImage(openid_image: Image.Image, qq_image: Image.Image) -> Image.Image:
    """生成带圆角边框的头像横向对比图。"""
    avatar_size = 100
    gap = int(avatar_size * 0.1)
    compare_size = int(avatar_size * 0.5)
    padding = 12
    border_width = 2
    width = padding * 2 + avatar_size * 2 + compare_size + gap * 2
    height = padding * 2 + avatar_size

    image = Image.new("RGBA", (width, height), (255, 255, 255, 0))
    draw = ImageDraw.Draw(image)
    card_box = (border_width // 2, border_width // 2, width - border_width // 2 - 1, height - border_width // 2 - 1)
    draw.rounded_rectangle(
        card_box,
        radius=18,
        fill=(255, 255, 255, 255),
        outline=(203, 213, 225, 255),
        width=border_width,
    )

    openid_avatar = _ApplyRoundMask(_PrepareAvatar(openid_image, avatar_size), 12)
    compare_image = _LoadCompareImage(compare_size)
    qq_avatar = _ApplyRoundMask(_PrepareAvatar(qq_image, avatar_size), 12)

    avatar_y = padding
    openid_x = padding
    compare_x = openid_x + avatar_size + gap
    compare_y = (height - compare_size) // 2
    qq_x = compare_x + compare_size + gap

    image.alpha_composite(openid_avatar, (openid_x, avatar_y))
    image.alpha_composite(compare_image, (compare_x, compare_y))
    image.alpha_composite(qq_avatar, (qq_x, avatar_y))
    return image


def _SaveAvatarCompareImage(openid_image: Image.Image, qq_image: Image.Image, image_id: str) -> dict:
    """保存头像对比图，并返回可通过图片服务访问的数据。"""
    Path("imgs").mkdir(parents=True, exist_ok=True)
    output = _RenderAvatarCompareImage(openid_image, qq_image)
    file_name = f"imgs/{image_id}.png"
    output.save(file_name)
    width, height = output.size
    return {
        "fileName": file_name,
        "imgUrl": _config_manager.BuildGenerateImgUrl(image_id),
        "width": width,
        "height": height,
    }


def _Phash(img, hash_size=8, dct_size=32):
    """计算图片的感知哈希值。"""
    img = img.convert("L").resize((dct_size, dct_size), Image.LANCZOS)
    pixels = list(img.getdata())

    # 构建 2D 像素矩阵
    matrix = []
    for y in range(dct_size):
        matrix.append(pixels[y * dct_size:(y + 1) * dct_size])

    # 预计算 cos 值，避免重复运算
    cos_table = {}
    for k in range(hash_size):
        for n in range(dct_size):
            cos_table[(k, n)] = math.cos(math.pi * (2 * n + 1) * k / (2 * dct_size))

    # 计算 2D DCT-II（只算左上 hash_size x hash_size）
    dct = []
    for u in range(hash_size):
        for v in range(hash_size):
            s = 0.0
            for y in range(dct_size):
                for x in range(dct_size):
                    s += matrix[y][x] * cos_table[(u, y)] * cos_table[(v, x)]
            cu = 1.0 / math.sqrt(2) if u == 0 else 1.0
            cv = 1.0 / math.sqrt(2) if v == 0 else 1.0
            dct.append(s * cu * cv * 2.0 / dct_size)

    # 去掉 DC 分量（第一个值），用剩余值算中位数
    dct_no_dc = dct[1:]
    median = sorted(dct_no_dc)[len(dct_no_dc) // 2]

    # 生成哈希：大于中位数为 1，否则为 0
    return int("".join("1" if v > median else "0" for v in dct), 2)


def _HammingDistance(hash1, hash2, bits=64):
    """计算两个哈希之间的汉明距离。"""
    xor = hash1 ^ hash2
    return bin(xor).count("1")


def _HashSimilarity(hash1, hash2, bits=64):
    """把汉明距离换算为 0 到 1 的相似度。"""
    dist = _HammingDistance(hash1, hash2, bits)
    return 1.0 - dist / bits


async def CompareQQAvatars(app_id, qq_number, openid):
    """比较 QQ 头像和 OpenID 头像的相似度。"""
    qq_url = f"https://q.qlogo.cn/g?b=qq&nk={qq_number}&s=100"
    openid_url = GetQLogoUrl(app_id, openid, size=100)

    async with aiohttp.ClientSession() as session:
        img1 = await _DownloadImage(session, qq_url)
        if img1 is None:
            return (-1.0, 1, f"QQ头像下载失败（可能原因：网络超时/QQ号不存在） URL: {qq_url}")

        img2 = await _DownloadImage(session, openid_url)
        if img2 is None:
            return (-1.0, 2, f"OpenID头像下载失败（可能原因：授权过期/用户未设置） URL: {openid_url}")

        try:
            hash1 = _Phash(img1)
            hash2 = _Phash(img2)
            similarity = _HashSimilarity(hash1, hash2)
        except Exception as e:
            return (-1.0, 5, f"哈希计算失败（{e}）")

        return (similarity, 0, "成功")


async def GenerateQQAvatarCompareImage(app_id, qq_number, openid, image_id=None):
    """生成 OpenId 头像到 QQ 号头像的对比图片。"""
    qq_url = f"https://q.qlogo.cn/g?b=qq&nk={qq_number}&s=640"
    openid_url = GetQLogoUrl(app_id, openid, size=640)
    image_id = image_id or str(uuid.uuid4())

    async with aiohttp.ClientSession() as session:
        openid_image = await _DownloadImage(session, openid_url)
        if openid_image is None:
            return {"success": False, "code": 2, "msg": f"OpenID头像下载失败 URL: {openid_url}"}

        qq_image = await _DownloadImage(session, qq_url)
        if qq_image is None:
            return {"success": False, "code": 1, "msg": f"QQ头像下载失败 URL: {qq_url}"}

    try:
        image_data = _SaveAvatarCompareImage(openid_image, qq_image, image_id)
        return {"success": True, **image_data}
    except Exception as e:
        return {"success": False, "code": 5, "msg": f"头像对比图生成失败（{e}）"}


# 使用示例
if __name__ == "__main__":
    import asyncio

    async def _Test():
        app_id = "102006490"
        open_id = "7193DB23F8FB8029CA80F56937A01206"
        qq_number = "2351078777"
        result = await GenerateQQAvatarCompareImage(app_id, qq_number, open_id, "test")
        print(result)

    asyncio.run(_Test())
