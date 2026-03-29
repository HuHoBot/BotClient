import aiohttp
import math
from io import BytesIO
from PIL import Image
from libs.basic import *
from ymbotpy import logging

_log = logging.get_logger()


async def _download_image(session, url, timeout=5):
    """异步下载图片，直接返回 PIL Image 对象"""
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=timeout)) as response:
            if response.status == 200:
                data = await response.read()
                return Image.open(BytesIO(data))
            return None
    except Exception as e:
        _log.error(f"下载失败: {e}")
        return None


def _phash(img, hash_size=8, dct_size=32):
    """
    计算感知哈希 (pHash)
    1. 缩放到 dct_size x dct_size 灰度图
    2. 对像素矩阵做 2D DCT-II 变换
    3. 取左上 hash_size x hash_size 的低频分量
    4. 以中位数为阈值生成二进制哈希
    """
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


def _hamming_distance(hash1, hash2, bits=64):
    """计算两个哈希的汉明距离"""
    xor = hash1 ^ hash2
    return bin(xor).count("1")


def _hash_similarity(hash1, hash2, bits=64):
    """将汉明距离转为 0~1 的相似度"""
    dist = _hamming_distance(hash1, hash2, bits)
    return 1.0 - dist / bits


async def compare_qq_avatars(APPID,qq_number, openid):
    """
    返回值说明: (相似度, 错误代码, 错误信息)
    错误代码定义:
    0 - 成功
    1 - QQ头像下载失败
    2 - OpenID头像下载失败
    5 - 哈希计算失败
    """
    qq_url = f"https://q.qlogo.cn/g?b=qq&nk={qq_number}&s=100"
    openid_url = getQLogoUrl(APPID,OpenID=openid, size=100)

    async with aiohttp.ClientSession() as session:
        img1 = await _download_image(session, qq_url)
        if img1 is None:
            return (-1.0, 1, f"QQ头像下载失败（可能原因：网络超时/QQ号不存在） URL: {qq_url}")

        img2 = await _download_image(session, openid_url)
        if img2 is None:
            return (-1.0, 2, f"OpenID头像下载失败（可能原因：授权过期/用户未设置） URL: {openid_url}")

        try:
            hash1 = _phash(img1)
            hash2 = _phash(img2)
            similarity = _hash_similarity(hash1, hash2)
        except Exception as e:
            return (-1.0, 5, f"哈希计算失败（{e}）")

        return (similarity, 0, "成功")


# 使用示例
if __name__ == "__main__":
    import asyncio
    async def _test():
        result = await compare_qq_avatars("APPID","123456", "ABCD")
        if result[1] == 0:
            print(f"相似度：{result[0]:.2%}")
        else:
            print(f"错误 ({result[1]}): {result[2]}")
    asyncio.run(_test())
