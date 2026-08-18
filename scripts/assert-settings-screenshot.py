#!/usr/bin/env python3
from collections import Counter
from pathlib import Path
import sys
from PIL import Image


def dominant(image: Image.Image, box: tuple[int, int, int, int]) -> tuple[int, int, int]:
    return Counter(image.crop(box).get_flattened_data()).most_common(1)[0][0]


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit("usage: assert-settings-screenshot.py PRODUCT.png FAILURE.png")
    product_path, failure_path = map(Path, sys.argv[1:])
    product = Image.open(product_path).convert("RGB")
    failure = Image.open(failure_path).convert("RGB")
    if product.size != (720, 1200) or failure.size != (720, 1200):
        raise SystemExit(f"unexpected dimensions: product={product.size} failure={failure.size}")
    if len(set(product.get_flattened_data())) < 100 or len(set(failure.get_flattened_data())) < 100:
        raise SystemExit("Settings screenshots lack rendered text/detail")

    dark = dominant(product, (80, 192, 320, 272))
    contrast = dominant(product, (400, 192, 640, 272))
    celsius = dominant(product, (80, 352, 320, 432))
    fahrenheit = dominant(product, (400, 352, 640, 432))
    failure_status = dominant(failure, (16, 1104, 704, 1184))

    if not (contrast[0] > contrast[1] + 20 and contrast[1] > contrast[2] + 20 and contrast[2] < 100):
        raise SystemExit(f"High Contrast selection is not a dark amber surface: {contrast}")
    if not (fahrenheit[1] > fahrenheit[0] + 30 and fahrenheit[2] > fahrenheit[0] + 35):
        raise SystemExit(f"Fahrenheit selection is not a distinct teal surface: {fahrenheit}")
    if dark == contrast or celsius == fahrenheit:
        raise SystemExit("selected and unselected controls are visually identical")
    if not (failure_status[0] > failure_status[1] + 45 and failure_status[0] < 220 and failure_status[1] < 130):
        raise SystemExit(f"failure status is not a dark error surface: {failure_status}")

    print(
        "settings_pixels "
        f"size={product.width}x{product.height} unique={len(set(product.get_flattened_data()))} "
        f"dark={dark} contrast={contrast} celsius={celsius} fahrenheit={fahrenheit} "
        f"failure_status={failure_status}"
    )


if __name__ == "__main__":
    main()
