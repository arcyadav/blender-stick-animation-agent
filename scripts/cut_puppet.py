"""Cut a cartoon character's parts out of generated part sheets (flat green background) and find
each part's joints, for the puppet look (blender_worker/puppet.py).

    python -m scripts.cut_puppet          # assets/girl/sheet_{side,front}.png -> assets/girl/parts/

A part is named by seed points (inside the regions enclosed by its outline); outline pixels go to the
nearest part. Joints are found from each limb's round ends, or set in the sheet's own coordinates.
"""
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage

ROOT = Path(__file__).resolve().parents[1]
DIR = ROOT / "assets" / "girl"

# part -> seed points (x, y) in the sheet; a seed on a dark pixel (hair) takes its whole piece
SIDE = {
    "head": [(170, 170), (165, 320)], "hair_back": [(480, 200)], "hair_front": [(760, 130)],
    "torso": [(180, 500), (150, 425)], "hips": [(170, 640)],
    "thigh_a": [(170, 785)], "shin_a": [(165, 1000)], "shoe_a": [(205, 1135)],
    "thigh_b": [(430, 800)], "shin_b": [(430, 1015)], "shoe_b": [(465, 1135)],
    "upper_a": [(432, 530)], "upper_b": [(610, 535)], "fore": [(625, 755)],
}


# front sheet: image-left is her right side. "*" = take the whole piece the seed is on
FRONT = {
    "head": ["*", (447, 150)], "hair_front": ["*", (170, 100)], "hair_back": ["*", (720, 180)],
    "neck": ["*", (448, 320)], "torso": ["*", (448, 500)],
    "upper_r": ["*", (148, 447)], "upper_l": ["*", (745, 447)], "fore_r": ["*", (110, 600)],
    "fore_l": ["*", (780, 600)], "hand_r": ["*", (79, 722)], "hand_l": ["*", (805, 722)],
    "thigh_r": [(375, 772), (355, 672)], "shin_r": [(361, 972)], "thigh_l": [(520, 772), (540, 672)],
    "shin_l": [(533, 972)], "shoe_r": ["*", (325, 1140)], "shoe_l": ["*", (570, 1140)],
}
FILL_FRONT = {"shin_r": [(370, 880, 30)], "shin_l": [(530, 880, 30)],
              "torso": [(448, 380, 36, "neck")]}           # the scooped neckline shows skin

# joints hidden under another part's round end: the sheet never drew them (the notch opens when the joint
# bends), so a disc of the part's own colour fills them. part -> [(x, y, radius)] in sheet px
FILL_SIDE = {"shin_a": [(176, 884, 44)], "shin_b": [(437.5, 897.5, 38)], "upper_a": [(432.5, 616.5, 28)],
             "upper_b": [(610, 620, 28)], "thigh_a": [(170.5, 707.5, 50)]}


def fill_joints(im, masks, fills):
    """Fill each listed joint disc where the part is empty, with the part's main colour. -> per-part images."""
    out = {}
    h, w = next(iter(masks.values())).shape
    yy, xx = np.mgrid[0:h, 0:w]
    for n, m in masks.items():
        img = im.copy()
        for x, y, r, *src in fills.get(n, []):
            disc = (xx - x) ** 2 + (yy - y) ** 2 <= r * r
            body = (masks[src[0]] if src else m) & (im.sum(-1) / 3 > 75)   # colour: this part, or another
            colour = np.median(im[body], axis=0)
            new = disc & ~m
            img[new] = colour
            m |= disc
        out[n] = img
    return out


def key(sheet):
    im = np.asarray(Image.open(sheet).convert("RGB")).astype(int)
    r, g, b = im[..., 0], im[..., 1], im[..., 2]
    green = (g > 150) & (g - r > 60) & (g - b > 60)
    # take the green tint out of the anti-aliased edge: g never above the brighter of r and b
    soft = (g > np.maximum(r, b)) & ~green
    im[..., 1] = np.where(soft, np.maximum(r, b), g)
    return im, ~green


def split(im, fg, seeds):
    lum = im.sum(-1) / 3
    inner = fg & (lum > 75)
    lab, _ = ndimage.label(inner)
    pieces, _ = ndimage.label(fg)
    owner = np.zeros(fg.shape, int)                    # 0 = nobody yet
    names = list(seeds)
    for k, n in enumerate(names, 1):
        whole = seeds[n][0] == "*"
        for x, y in [q for q in seeds[n] if q != "*"]:
            if whole:
                owner[(pieces == pieces[y, x]) & (owner == 0)] = k
            elif inner[y, x]:
                owner[lab == lab[y, x]] = k
            else:                                      # a dark part (hair): its whole piece
                owner[(pieces == pieces[y, x]) & (owner == 0)] = k
    # everything else in a piece (outlines, small details) goes to the nearest owned pixel of that piece;
    # pieces with no seed (e.g. spare drawings on the sheet) are dropped
    _, (iy, ix) = ndimage.distance_transform_edt(owner == 0, return_indices=True)
    near = owner[iy, ix]
    same = pieces[iy, ix] == pieces
    seeded = np.isin(pieces, np.unique(pieces[owner > 0]))
    owner = np.where(fg & (owner == 0) & same & seeded, near, owner)
    owner[~fg | ~seeded] = 0
    return {n: owner == k for k, n in enumerate(names, 1)}


def save(ims, masks, out):
    out.mkdir(parents=True, exist_ok=True)
    info = {}
    for n, m in masks.items():
        im = ims[n]
        ys, xs = np.nonzero(m)
        y0, y1, x0, x1 = ys.min(), ys.max() + 1, xs.min(), xs.max() + 1
        mm = m[y0:y1, x0:x1]
        # empty pixels take the nearest drawn pixel's colour (the outline), so edges never blend to white
        _, (iy, ix) = ndimage.distance_transform_edt(~mm, return_indices=True)
        rgb = im[y0:y1, x0:x1][iy, ix]
        rgba = np.dstack([rgb.astype(np.uint8), (mm * 255).astype(np.uint8)])
        Image.fromarray(rgba).save(out / f"{n}.png")
        info[n] = {"origin": [int(x0), int(y0)], "size": [int(x1 - x0), int(y1 - y0)]}
    return info


def ends(m):
    """A vertical limb's two joint centres: the middle of each round end, half its width in."""
    ys, xs = np.nonzero(m)
    y0, y1 = ys.min(), ys.max()

    def row(y):
        c = xs[ys == y]
        return (c.min() + c.max()) / 2, c.max() - c.min()
    tx, tw = row(int(y0 + 0.08 * (y1 - y0)))
    bx, bw = row(int(y1 - 0.08 * (y1 - y0)))
    return [float(tx), float(y0 + tw / 2)], [float(bx), float(y1 - bw / 2)]


if __name__ == "__main__":
    im, fg = key(DIR / "sheet_side.png")
    masks = split(im, fg, SIDE)
    info = save(fill_joints(im, masks, FILL_SIDE), masks, DIR / "parts" / "side")
    for n in info:
        if n.startswith(("thigh", "shin", "upper", "fore")):
            info[n]["ends"] = ends(masks[n])
    for n in ("thigh_b", "shin_b", "shoe_b", "upper_a", "fore"):     # the far side is drawn a little darker
        rgba = np.asarray(Image.open(DIR / "parts" / "side" / f"{n}.png")).astype(float)
        rgba[..., :3] *= 0.8
        Image.fromarray(rgba.astype(np.uint8)).save(DIR / "parts" / "side" / f"{n}_dark.png")
    (DIR / "parts" / "side" / "parts.json").write_text(json.dumps(info, indent=1))
    im, fg = key(DIR / "sheet_front.png")
    masks = split(im, fg, FRONT)
    info = save(fill_joints(im, masks, FILL_FRONT), masks, DIR / "parts" / "front")
    for n in info:
        if n.startswith(("thigh", "shin", "upper", "fore", "hand")):
            info[n]["ends"] = ends(masks[n])
    (DIR / "parts" / "front" / "parts.json").write_text(json.dumps(info, indent=1))
    for n, v in info.items():
        print(n, v)
