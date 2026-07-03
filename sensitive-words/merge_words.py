# -*- coding: utf-8 -*-
"""违禁词词库合并脚本。

读取当前目录下所有 *.txt 文件，每行一个词，合并去重后写入 words.txt。
"""

import glob
import os
import sys


def main():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    output_file = os.path.join(script_dir, "words.txt")

    # 收集所有非输出文件自己的 *.txt
    txt_files = [
        f for f in glob.glob(os.path.join(script_dir, "*.txt"))
        if os.path.basename(f) != "words.txt"
    ]

    if not txt_files:
        print("当前目录没有找到 *.txt 文件")
        return

    words = set()
    for filepath in txt_files:
        with open(filepath, "r", encoding="utf-8") as f:
            for line in f:
                word = line.strip()
                if word:
                    words.add(word)

    # 按字母序排序写入
    with open(output_file, "w", encoding="utf-8") as f:
        for word in sorted(words):
            f.write(word + "\n")

    print(f"已合并 {len(txt_files)} 个文件 → {output_file}")
    print(f"去重后共 {len(words)} 个词")


if __name__ == "__main__":
    main()
