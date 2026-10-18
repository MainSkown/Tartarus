"""Compare an 'after' screenshot run against a baseline, ignoring the regions that differ between two baseline runs.

usage: compare_shots.py BASE_DIR BASE2_DIR AFTER_DIR
Exit 0 when no image differs from the baseline outside its noise box, no size changed and none is missing.
"""
import os
import sys

from PIL import Image, ImageChops


def diff_mask(a: Image.Image, b: Image.Image) -> Image.Image:
    return ImageChops.difference(a, b).convert("L").point(lambda v: 255 if v else 0)


def blank_box(mask: Image.Image, box: tuple[int, int, int, int]) -> Image.Image:
    mask = mask.copy()
    mask.paste(0, box)
    return mask


def main(base: str, base2: str, after: str) -> int:
    failed, noisy_only, same, missing = [], [], 0, []
    for root, _, files in os.walk(base):
        for name in sorted(files):
            rel = os.path.relpath(os.path.join(root, name), base)
            paths = [os.path.join(d, rel) for d in (base, base2, after)]
            if not all(os.path.exists(p) for p in paths):
                missing.append(rel)
                continue
            b1, b2, af = (Image.open(p).convert("RGB") for p in paths)
            if not (b1.size == b2.size == af.size):
                failed.append((rel, "size", b1.size, af.size))
                continue
            noise_box = diff_mask(b1, b2).getbbox()
            against_base = diff_mask(b1, af)
            outside = against_base if noise_box is None else blank_box(against_base, noise_box)
            if outside.getbbox():
                failed.append((rel, "outside noise box", outside.getbbox(), noise_box))
            elif against_base.getbbox():
                noisy_only.append((rel, against_base.getbbox(), noise_box))
            else:
                same += 1
    print(f"identical: {same}   differs only inside the noise box (look at these): {len(noisy_only)}   FAILED: {len(failed)}   missing: {len(missing)}")
    for row in noisy_only:
        print("NOISY ", *row)
    for row in failed:
        print("FAILED", *row)
    for rel in missing:
        print("MISSING", rel)
    return 1 if failed or missing else 0


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:4]))
