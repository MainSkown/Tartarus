"""Compare screenshot runs of the same specs before and after a change, tolerating animation noise.

usage: compare_shots.py BASE_DIR[,BASE_DIR...] AFTER_DIR[,AFTER_DIR...]

The harness is not deterministic (spinners, pulse markers, hover transitions, drawer and toast slide-ins). A pixel counts
as changed only when it differs in every pairing of a baseline run with an after run AND lies outside every area where
two runs of the same code disagree (that area, from all same-code pairs, is widened by 3 px for anti-aliasing).
Exit 0 when no image has such a pixel, none changed size and none is missing from a run.
"""
import os
import sys

from PIL import Image, ImageChops, ImageFilter


def differing_pixels(a: Image.Image, b: Image.Image) -> Image.Image:
    return ImageChops.difference(a, b).convert("L").point(lambda value: 255 if value else 0)


def every_pair_differs(first: list[Image.Image], second: list[Image.Image]) -> Image.Image:
    masks = [differing_pixels(a, b) for a in first for b in second]
    everywhere = masks[0]
    for mask in masks[1:]:
        everywhere = ImageChops.darker(everywhere, mask)
    return everywhere


def run_to_run_noise(runs: list[Image.Image]) -> Image.Image:
    noise = Image.new("L", runs[0].size, 0)
    for index, a in enumerate(runs):
        for b in runs[index + 1:]:
            noise = ImageChops.lighter(noise, differing_pixels(a, b))
    return noise.filter(ImageFilter.MaxFilter(7))


def consistent_change(baselines: list[Image.Image], afters: list[Image.Image]) -> Image.Image:
    noise = ImageChops.lighter(run_to_run_noise(baselines), run_to_run_noise(afters))
    return ImageChops.subtract(every_pair_differs(baselines, afters), noise)


def count_set(mask: Image.Image) -> int:
    return mask.histogram()[255]


def main(base_dirs: list[str], after_dirs: list[str]) -> int:
    failed, unstable, same, missing = [], [], 0, []
    for root, _, files in os.walk(base_dirs[0]):
        for name in sorted(files):
            rel = os.path.relpath(os.path.join(root, name), base_dirs[0])
            paths = [os.path.join(d, rel) for d in base_dirs + after_dirs]
            if not all(os.path.exists(p) for p in paths):
                missing.append(rel)
                continue
            images = [Image.open(p).convert("RGB") for p in paths]
            baselines, afters = images[: len(base_dirs)], images[len(base_dirs):]
            if len({image.size for image in images}) != 1:
                failed.append((rel, "size", sorted({image.size for image in images})))
                continue
            changed = consistent_change(baselines, afters)
            if changed.getbbox():
                failed.append((rel, "pixels", count_set(changed), changed.getbbox()))
            elif any(differing_pixels(baselines[0], after).getbbox() for after in afters):
                unstable.append(rel)
            else:
                same += 1
    print(f"identical to the first baseline: {same}   differ only in pixels that also vary between runs: {len(unstable)}   CHANGED: {len(failed)}   missing: {len(missing)}")
    for row in failed:
        print("CHANGED", *row)
    for rel in missing:
        print("MISSING", rel)
    return 1 if failed or missing else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1].split(","), sys.argv[2].split(",")))
