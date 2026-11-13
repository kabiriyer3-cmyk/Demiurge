#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Demiurge asset generator.

Every visual of the mod (entity textures + emissive layers, items, HUD icons,
particles, effect icon, mod icon) AND the cuboid geometry of every entity model
are produced procedurally by this file. No binary assets live in git.

Pure Python 3 standard library. Gradle runs it before compiling:
    python3 tools/assetgen.py build/generated/assetgen
Writes:
    <out>/resources/assets/demiurge/...           (PNG textures)
    <out>/java/dev/hurma/demiurge/client/model/gen (model geometry classes)
"""
import math, os, struct, sys, zlib

MODID = "demiurge"
JAVA_PKG = "dev.hurma.demiurge.client.model.gen"
S = 2  # texel density: each model pixel is painted with SxS texels (HD textures)

# ================================================================ math & colour
def clamp(x, a=0.0, b=1.0): return a if x < a else b if x > b else x
def lerp(a, b, t): return a + (b - a) * t
def mix(c1, c2, t): return (lerp(c1[0], c2[0], t), lerp(c1[1], c2[1], t), lerp(c1[2], c2[2], t))
def mul(c, k): return (clamp(c[0] * k), clamp(c[1] * k), clamp(c[2] * k))
def hexc(h):
    h = h.lstrip('#'); return tuple(int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4))
def smooth(t): return t * t * (3 - 2 * t)
def ramp(t, stops):
    t = clamp(t) * (len(stops) - 1); i = min(int(t), len(stops) - 2)
    return mix(stops[i], stops[i + 1], t - i)

def _h(x, y, s):
    n = (x * 374761393 + y * 668265263 + s * 1442695041) & 0xFFFFFFFF
    n = ((n ^ (n >> 13)) * 1274126177) & 0xFFFFFFFF
    return ((n ^ (n >> 16)) & 0xFFFFFF) / 16777215.0
def rnd(x, y, s=0): return _h(int(x), int(y), s)
def vnoise(x, y, s=0):
    xi, yi = math.floor(x), math.floor(y)
    xf, yf = smooth(x - xi), smooth(y - yi)
    a = _h(xi, yi, s); b = _h(xi + 1, yi, s); c = _h(xi, yi + 1, s); d = _h(xi + 1, yi + 1, s)
    return lerp(lerp(a, b, xf), lerp(c, d, xf), yf)
def fbm(x, y, s=0, octaves=3):
    t, amp, f, norm = 0.0, 1.0, 1.0, 0.0
    for o in range(octaves):
        t += vnoise(x * f, y * f, s + o * 101) * amp
        norm += amp; amp *= 0.5; f *= 2.03
    return t / norm

# ================================================================ image
class Img:
    def __init__(self, w, h):
        self.w, self.h = w, h
        self.px = [[0.0, 0.0, 0.0, 0.0] for _ in range(w * h)]
    def get(self, x, y): return self.px[y * self.w + x]
    def set(self, x, y, c, a=1.0):
        if 0 <= x < self.w and 0 <= y < self.h: self.px[y * self.w + x] = [c[0], c[1], c[2], a]
    def over(self, x, y, c, a):
        if not (0 <= x < self.w and 0 <= y < self.h) or a <= 0: return
        p = self.px[y * self.w + x]; na = a + p[3] * (1 - a)
        for i in range(3): p[i] = (c[i] * a + p[i] * p[3] * (1 - a)) / na
        p[3] = na
    def add(self, x, y, c, k=1.0):
        if 0 <= x < self.w and 0 <= y < self.h:
            p = self.px[y * self.w + x]
            for i in range(3): p[i] = clamp(p[i] + c[i] * k)
            p[3] = max(p[3], clamp(k))
    def save(self, path):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        raw = bytearray()
        for y in range(self.h):
            raw.append(0)
            for p in self.px[y * self.w:(y + 1) * self.w]:
                raw += bytes(int(clamp(v) * 255 + 0.5) for v in p)
        def chunk(t, d): return struct.pack('>I', len(d)) + t + d + struct.pack('>I', zlib.crc32(t + d) & 0xFFFFFFFF)
        data = (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', self.w, self.h, 8, 6, 0, 0, 0))
                + chunk(b'IDAT', zlib.compress(bytes(raw), 9)) + chunk(b'IEND', b''))
        with open(path, 'wb') as f: f.write(data)

class Canvas:
    """Supersampled vector canvas for icons/items (anti-aliased shapes)."""
    def __init__(self, w, h, ss=4):
        self.w, self.h, self.ss = w, h, ss
        self.W, self.H = w * ss, h * ss
        self.c = [[0.0, 0.0, 0.0, 0.0] for _ in range(self.W * self.H)]
    def _plot(self, X, Y, col, a):
        p = self.c[Y * self.W + X]; na = a + p[3] * (1 - a)
        if na <= 0: return
        for i in range(3): p[i] = (col[i] * a + p[i] * p[3] * (1 - a)) / na
        p[3] = na
    def fill(self, inside, col, a=1.0, box=None):
        """inside(x, y) -> bool or float coverage, in output-pixel coordinates."""
        x0, y0, x1, y1 = box or (0, 0, self.w, self.h)
        X0, Y0 = max(0, int(x0 * self.ss)), max(0, int(y0 * self.ss))
        X1, Y1 = min(self.W, int(math.ceil(x1 * self.ss))), min(self.H, int(math.ceil(y1 * self.ss)))
        for Y in range(Y0, Y1):
            y = (Y + 0.5) / self.ss
            for X in range(X0, X1):
                k = inside((X + 0.5) / self.ss, y)
                if k:
                    cc = col(((X + 0.5) / self.ss, y)) if callable(col) else col
                    self._plot(X, Y, cc, a * (1.0 if k is True else k))
    def circle(self, cx, cy, r, col, a=1.0):
        self.fill(lambda x, y: (x - cx) ** 2 + (y - cy) ** 2 <= r * r, col, a, (cx - r - 1, cy - r - 1, cx + r + 1, cy + r + 1))
    def ring(self, cx, cy, r, w, col, a=1.0):
        self.fill(lambda x, y: abs(math.hypot(x - cx, y - cy) - r) <= w / 2, col, a, (cx - r - w, cy - r - w, cx + r + w, cy + r + w))
    def ellipse_ring(self, cx, cy, rx, ry, ang, w, col, a=1.0, front=None):
        ca, sa = math.cos(ang), math.sin(ang)
        def ins(x, y):
            dx, dy = x - cx, y - cy
            lx, ly = dx * ca + dy * sa, -dx * sa + dy * ca
            if front is not None and (ly > 0) != front: return False
            d = math.hypot(lx / rx, ly / ry)
            return abs(d - 1) * min(rx, ry) <= w / 2
        m = max(rx, ry) + w
        self.fill(ins, col, a, (cx - m, cy - m, cx + m, cy + m))
    def line(self, x0, y0, x1, y1, w, col, a=1.0):
        dx, dy = x1 - x0, y1 - y0; L2 = dx * dx + dy * dy or 1e-9
        def ins(x, y):
            t = clamp(((x - x0) * dx + (y - y0) * dy) / L2)
            return math.hypot(x - (x0 + t * dx), y - (y0 + t * dy)) <= w / 2
        self.fill(ins, col, a, (min(x0, x1) - w, min(y0, y1) - w, max(x0, x1) + w, max(y0, y1) + w))
    def poly(self, pts, col, a=1.0):
        def ins(x, y):
            c = False; n = len(pts)
            for i in range(n):
                (xa, ya), (xb, yb) = pts[i], pts[(i + 1) % n]
                if (ya > y) != (yb > y) and x < (xb - xa) * (y - ya) / (yb - ya) + xa: c = not c
            return c
        xs = [p[0] for p in pts]; ys = [p[1] for p in pts]
        self.fill(ins, col, a, (min(xs) - 1, min(ys) - 1, max(xs) + 1, max(ys) + 1))
    def glow(self, cx, cy, r, col, a=1.0):
        self.fill(lambda x, y: clamp(1 - math.hypot(x - cx, y - cy) / r) ** 2, col, a, (cx - r, cy - r, cx + r, cy + r))
    def img(self):
        out = Img(self.w, self.h); n = self.ss * self.ss
        for y in range(self.h):
            for x in range(self.w):
                r = g = b = a = 0.0
                for Y in range(y * self.ss, (y + 1) * self.ss):
                    for X in range(x * self.ss, (x + 1) * self.ss):
                        p = self.c[Y * self.W + X]; r += p[0] * p[3]; g += p[1] * p[3]; b += p[2] * p[3]; a += p[3]
                if a > 0: out.set(x, y, (r / a, g / a, b / a), a / n)
        return out

# ================================================================ model spec
def C(o, s, mat, dil=0.0, **kw):
    d = dict(o=tuple(float(v) for v in o), s=tuple(int(v) for v in s), mat=mat, dil=float(dil))
    d.update(kw); return d
def P(name, parent, pivot=(0, 0, 0), rot=(0, 0, 0), cubes=()):
    return dict(name=name, parent=parent, pivot=tuple(round(float(v), 4) for v in pivot),
                rot=tuple(round(float(v), 4) for v in rot), cubes=list(cubes))
def ring(prefix, parent, center, radius, n, seg, mat, plane='xy'):
    out = [P(prefix, parent, center)]
    for i in range(n):
        a = 2 * math.pi * i / n
        if plane == 'xy':
            piv, rot = (radius * math.cos(a), radius * math.sin(a), 0), (0, 0, a + math.pi / 2)
        else:
            piv, rot = (radius * math.cos(a), 0, radius * math.sin(a)), (0, -(a + math.pi / 2), 0)
        out.append(P('%s_%d' % (prefix, i), prefix, piv, rot, [C((-seg / 2.0, -0.5, -0.5), (seg, 1, 1), mat)]))
    return out
def radial_spikes(prefix, parent, n, r, length, mat, tilt=0.5, phase=0.0, long_idx=None):
    out = []
    for i in range(n):
        a = 2 * math.pi * i / n + phase
        L = length + (2 if i == long_idx else 0)
        out.append(P('%s_%d' % (prefix, i), parent, (r * math.sin(a), 0, -r * math.cos(a)),
                     (tilt * math.cos(a), 0, tilt * math.sin(a)), [C((-0.5, -L, -0.5), (1, L, 1), mat)]))
    return out

HEM_V = '#5a2d91'; HEM_G = '#d9a441'

def model_shade():
    V = 'void_cloth'
    return [
        P('body', None, (0, 0, 0), cubes=[
            C((-4, 0, -2), (8, 11, 4), 'void_plate', seams=3, decals=[('front', 'runes', dict(color='#a65cff', rows=1, y=0.28))]),
            C((-4.5, 10, -2.5), (9, 2, 5), 'leather', dil=0.05)]),
        P('mantle', 'body', (0, 0, 0), cubes=[C((-5, -0.5, -3), (10, 3, 6), V, dil=0.15, hide=('bottom',))]),
        P('head', 'body', (0, 0, 0), cubes=[
            C((-3, -7, -3), (6, 7, 6), 'shadow_inner', decals=[('front', 'eyes', dict(style='slit', color='#c77dff', y=0.5, sep=0.22, ew=1.6))]),
            C((-4, -8.5, -4), (8, 9, 8), V, hide=('bottom',), decals=[('front', 'hood_opening', dict(w=0.76, top=0.22))])]),
        P('hood_tip', 'head', (0, -7, 3.5), (0.7, 0, 0), cubes=[C((-2, -1.5, 0), (4, 3, 5), V)]),
        P('cloak', 'body', (0, 0.5, 2.3), (0.08, 0, 0), cubes=[C((-5, 0, 0), (10, 21, 0), V, plane=True, tatter=True, hem=HEM_V)]),
        P('tabard', 'body', (0, 11.5, -2.4), cubes=[C((-3, 0, 0), (6, 9, 0), V, plane=True, tatter=True, hem=HEM_V)]),
        P('arm_r', 'body', (-5, 1.5, 0), cubes=[C((-2, -1.5, -1.5), (3, 11, 3), 'wraps'), C((-2.5, 6, -2), (4, 5, 4), 'void_plate', seams=1)]),
        P('pauldron_r', 'arm_r', (0, 0, 0), cubes=[C((-3.5, -2.5, -2.5), (5, 4, 5), 'void_plate', dil=0.1, seams=1),
                                                  C((-2.5, -4.5, -0.5), (1, 2, 1), 'void_crystal')]),
        P('blade', 'arm_r', (-0.5, 9.5, 0), (0.45, 0, 0), cubes=[
            C((-0.5, -0.5, -1.5), (1, 1, 3), 'leather'),
            C((-0.5, -2.5, -2.5), (1, 5, 1), 'void_plate', seams=0),
            C((-0.5, -1.5, -16.5), (1, 3, 14), 'void_crystal'),
            C((-0.5, 1.5, -15.5), (1, 1, 12), 'light_violet')]),
        P('arm_l', 'body', (5, 1.5, 0), cubes=[C((-1, -1.5, -1.5), (3, 11, 3), 'wraps'), C((-1.5, 6, -2), (4, 5, 4), 'void_plate', seams=1)]),
        P('pauldron_l', 'arm_l', (0, 0, 0), cubes=[C((-1.5, -2.5, -2.5), (5, 4, 5), 'void_plate', dil=0.1, seams=1),
                                                  C((1.5, -4.5, -0.5), (1, 2, 1), 'void_crystal')]),
        P('leg_r', None, (-2, 12, 0), cubes=[C((-1.5, 0, -1.5), (3, 12, 3), 'wraps'), C((-2, 7, -2), (4, 5, 4), 'void_plate', seams=1)]),
        P('leg_l', None, (2, 12, 0), cubes=[C((-1.5, 0, -1.5), (3, 12, 3), 'wraps'), C((-2, 7, -2), (4, 5, 4), 'void_plate', seams=1)]),
    ]

def model_devourer():
    F = 'void_flesh'
    parts = [
        P('body', None, (0, 13, 2), cubes=[
            C((-4.5, -4.5, -8), (9, 9, 8), F, decals=[('left', 'ribs', {}), ('right', 'ribs', {})]),
            C((-3.5, -3.5, 0), (7, 7, 8), F),
            C((-1.5, -6, -7.5), (3, 2, 15), 'void_plate', seams=0)]),
        P('spines', 'body', (0, -6, 0), (-0.35, 0, 0), cubes=[
            C((-0.5, -4, -6), (1, 4, 2), 'void_crystal'), C((-0.5, -5, -2.5), (1, 5, 2), 'void_crystal'),
            C((-0.5, -4, 1), (1, 4, 2), 'void_crystal'), C((-0.5, -3, 4.5), (1, 3, 2), 'void_crystal')]),
        P('neck', 'body', (0, -1.5, -8), (-0.3, 0, 0), cubes=[C((-2.5, -2.5, -3), (5, 5, 3), F)]),
        P('head', 'neck', (0, 0, -3), (0.3, 0, 0), cubes=[
            C((-3.5, -3.5, -4), (7, 6, 4), 'void_plate', seams=0, decals=[('front', 'eyes', dict(style='multi', color='#d38cff'))]),
            C((-2.5, -1.5, -8), (5, 3, 4), F, decals=[('front', 'fangs', dict(where='bottom')), ('right', 'fangs', dict(where='bottom')), ('left', 'fangs', dict(where='bottom'))])]),
        P('horn_r', 'head', (-2.5, -3, -1), (0.6, -0.35, 0), cubes=[C((-0.5, -0.5, 0), (1, 1, 6), 'bone')]),
        P('horn_l', 'head', (2.5, -3, -1), (0.6, 0.35, 0), cubes=[C((-0.5, -0.5, 0), (1, 1, 6), 'bone')]),
        P('jaw', 'head', (0, 1.5, -4), cubes=[C((-2, 0, -4), (4, 2, 4), F, decals=[('front', 'fangs', dict(where='top')), ('right', 'fangs', dict(where='top')), ('left', 'fangs', dict(where='top'))])]),
        P('tail', 'body', (0, -2, 8), (0.45, 0, 0), cubes=[C((-1, -1, 0), (2, 2, 6), F)]),
        P('tail_tip', 'tail', (0, 0, 6), (0.25, 0, 0), cubes=[C((-0.5, -0.5, 0), (1, 1, 5), 'void_plate', seams=0), C((-0.5, -2, 3), (1, 2, 3), 'void_crystal')]),
    ]
    for nm, x, z, back in (('fr', -3, -5, False), ('fl', 3, -5, False), ('br', -2.5, 7, True), ('bl', 2.5, 7, True)):
        thigh = C((-2, -2, -2), (4, 7, 4), F) if back else C((-1.5, -1, -1.5), (3, 6, 3), F)
        parts.append(P('leg_' + nm, None, (x, 15, z), cubes=[thigh]))
        parts.append(P('shin_' + nm, 'leg_' + nm, (0, 5, 0), cubes=[C((-1, 0, -1), (2, 4, 2), 'void_plate', seams=0), C((-1.5, 3, -2.5), (3, 1, 3), 'bone')]))
    return parts

def model_seraph():
    parts = [
        P('body', None, (0, 4, 0), cubes=[
            C((-3, -6, -2), (6, 8, 4), 'void_plate', seams=0, decals=[('front', 'ribs', dict(light=True))]),
            C((-1.5, -4.5, -2.6), (3, 3, 1), 'light_violet'),
            C((-2, 2, -1.5), (4, 5, 3), 'void_cloth')]),
        P('trail', 'body', (0, 7, 0), (0.15, 0, 0), cubes=[
            C((-2.5, 0, 0), (5, 10, 0), 'void_cloth', plane=True, tatter=True, hem=HEM_V),
            C((0, 0, -2.5), (0, 10, 5), 'void_cloth', plane=True, tatter=True, hem=HEM_V)]),
        P('head', 'body', (0, -6, 0), cubes=[C((-2.5, -5, -2.5), (5, 5, 5), 'void_plate', seams=0, decals=[('front', 'eye_sigil', dict(color='#d9a6ff', scale=0.92))])]),
        P('crown', 'head', (0, -5, 0)),
    ]
    parts += radial_spikes('thorn', 'crown', 6, 2.0, 4, 'void_crystal', 0.55, math.pi / 6)
    parts += ring('halo', 'head', (0, -3.5, 4), 5, 10, 3, 'light_violet', 'xy')
    parts += [
        P('wing_ur', 'body', (-2, -5, 1.8), (0, 0.45, 0.25), cubes=[C((-16, -10, 0), (16, 14, 0), 'void_feather', plane=True, side='r')]),
        P('wing_ul', 'body', (2, -5, 1.8), (0, -0.45, -0.25), cubes=[C((0, -10, 0), (16, 14, 0), 'void_feather', plane=True, side='l')]),
        P('wing_lr', 'body', (-2, 0, 1.8), (0, 0.55, -0.35), cubes=[C((-12, -2, 0), (12, 10, 0), 'void_feather', plane=True, side='r')]),
        P('wing_ll', 'body', (2, 0, 1.8), (0, -0.55, 0.35), cubes=[C((0, -2, 0), (12, 10, 0), 'void_feather', plane=True, side='l')]),
        P('arm_r', 'body', (-3.5, -5, 0), cubes=[C((-1.5, -0.5, -1), (2, 9, 2), 'void_flesh'), C((-1.5, 7, -1), (2, 3, 2), 'void_crystal')]),
        P('arm_l', 'body', (3.5, -5, 0), cubes=[C((-0.5, -0.5, -1), (2, 9, 2), 'void_flesh'), C((-0.5, 7, -1), (2, 3, 2), 'void_crystal')]),
    ]
    return parts

def model_colossus():
    O = 'obsidian'
    return [
        P('body', None, (0, -4, 0), cubes=[
            C((-9, -12, -5.5), (18, 12, 11), O, cracks=1.0),
            C((-6, 0, -4), (12, 7, 8), O, cracks=0.7),
            C((-7, 6, -4.5), (14, 4, 9), 'void_plate', seams=1)]),
        P('crystal_a', 'body', (-4, -12, 4), (-0.35, 0, -0.3), cubes=[C((-1.5, -8, -1.5), (3, 8, 3), 'void_crystal')]),
        P('crystal_b', 'body', (0.5, -12, 4.5), (-0.45, 0, 0.05), cubes=[C((-2, -10, -2), (4, 10, 4), 'void_crystal')]),
        P('crystal_c', 'body', (4.5, -12, 4), (-0.3, 0, 0.35), cubes=[C((-1.5, -7, -1.5), (3, 7, 3), 'void_crystal')]),
        P('head', 'body', (0, -12, -2.5), cubes=[C((-4, -7, -4.5), (8, 8, 8), O, cracks=0.4, decals=[('front', 'visor_line', dict(color='#c77dff', y=0.45))])]),
        P('horn_r', 'head', (-3.5, -5.5, -1), (0, 0, -0.55), cubes=[C((-1, -5, -1), (2, 5, 2), 'void_crystal')]),
        P('horn_l', 'head', (3.5, -5.5, -1), (0, 0, 0.55), cubes=[C((-1, -5, -1), (2, 5, 2), 'void_crystal')]),
        P('arm_r', 'body', (-11, -10, 0), cubes=[C((-5, -4, -4.5), (7, 7, 9), O, cracks=0.8), C((-4, 3, -3), (5, 10, 6), 'void_flesh')]),
        P('forearm_r', 'arm_r', (-1.5, 12, 0), cubes=[C((-3.5, 0, -4), (7, 13, 8), O, cracks=0.9), C((-3, 12, -4.5), (6, 3, 9), 'void_plate', seams=0)]),
        P('arm_l', 'body', (11, -10, 0), cubes=[C((-2, -4, -4.5), (7, 7, 9), O, cracks=0.8), C((-1, 3, -3), (5, 10, 6), 'void_flesh')]),
        P('forearm_l', 'arm_l', (1.5, 12, 0), cubes=[C((-3.5, 0, -4), (7, 13, 8), O, cracks=0.9), C((-3, 12, -4.5), (6, 3, 9), 'void_plate', seams=0)]),
        P('leg_r', None, (-4.5, 6, 0), cubes=[C((-3.5, 0, -3.5), (7, 9, 7), O, cracks=0.5)]),
        P('shin_r', 'leg_r', (0, 9, 0), cubes=[C((-4, 0, -4), (8, 9, 8), 'void_plate', seams=2, cracks=0.35)]),
        P('leg_l', None, (4.5, 6, 0), cubes=[C((-3.5, 0, -3.5), (7, 9, 7), O, cracks=0.5)]),
        P('shin_l', 'leg_l', (0, 9, 0), cubes=[C((-4, 0, -4), (8, 9, 8), 'void_plate', seams=2, cracks=0.35)]),
    ]

def model_sentinel():
    M, G = 'marble', 'gold'
    parts = [
        P('body', None, (0, -2, 0), cubes=[
            C((-5, -10, -3), (10, 12, 6), M, trim=True, decals=[('front', 'sun_emblem', dict(y=0.4, r=0.3))]),
            C((-5.5, 2, -3.5), (11, 4, 7), G)]),
        P('tabard', 'body', (0, 6, -3.6), cubes=[C((-3, 0, 0), (6, 11, 0), 'robe_white', plane=True, hem=HEM_G, decals=[('front', 'sun_emblem', dict(y=0.32, r=0.3))])]),
        P('cape', 'body', (0, -9.5, 3.2), (0.1, 0, 0), cubes=[C((-6, 0, 0), (12, 24, 0), 'robe_white', plane=True, hem=HEM_G, tatter=True)]),
        P('head', 'body', (0, -10, 0), cubes=[C((-3.5, -8, -3.5), (7, 8, 7), M, trim=True, decals=[('front', 'visor_t', dict(color='#9ff3ff'))])]),
        P('crest', 'head', (0, -8, 0), cubes=[C((-0.5, -4, -3.5), (1, 4, 8), G)]),
    ]
    parts += ring('halo', 'head', (0, -5, 4.5), 6, 12, 3, 'light_gold', 'xy')
    parts += [
        P('arm_r', 'body', (-6.5, -8, 0), cubes=[C((-2.5, -1, -2), (4, 11, 4), M), C((-3, 7, -2.5), (5, 5, 5), G)]),
        P('pauldron_r', 'arm_r', (0, 0, 0), cubes=[C((-4, -3, -3.5), (6, 5, 7), G, dil=0.05)]),
        P('sword', 'arm_r', (-0.5, 10, 0), (0.35, 0, 0), cubes=[
            C((-0.5, -0.5, -1.5), (1, 1, 4), 'leather'), C((-1, -3.5, -2.5), (2, 7, 1), G),
            C((-0.5, -1.5, -20.5), (1, 3, 18), 'light_blade')]),
        P('arm_l', 'body', (6.5, -8, 0), cubes=[C((-1.5, -1, -2), (4, 11, 4), M), C((-2, 7, -2.5), (5, 5, 5), G)]),
        P('pauldron_l', 'arm_l', (0, 0, 0), cubes=[C((-2, -3, -3.5), (6, 5, 7), G, dil=0.05)]),
        P('shield', 'arm_l', (3, 6, 0), cubes=[C((0, -7, -6), (1, 14, 12), M, trim=True, decals=[('left', 'sun_emblem', dict(y=0.45, r=0.34))])]),
        P('leg_r', None, (-2.5, 4, 0), cubes=[C((-2.5, 0, -2.5), (5, 14, 5), M, trim=True), C((-3, 5, -3.2), (6, 3, 1), G), C((-3, 14, -3.5), (6, 6, 6), G)]),
        P('leg_l', None, (2.5, 4, 0), cubes=[C((-2.5, 0, -2.5), (5, 14, 5), M, trim=True), C((-3, 5, -3.2), (6, 3, 1), G), C((-3, 14, -3.5), (6, 6, 6), G)]),
    ]
    return parts

def model_arbiter():
    R, G = 'robe_white', 'gold'
    parts = [
        P('body', None, (0, 0, 0), cubes=[
            C((-4, -12, -2.5), (8, 10, 5), R, hem=HEM_G, decals=[('front', 'eye_sigil', dict(color='#ffd36b', scale=0.62, y=0.42))]),
            C((-5, -2, -3.5), (10, 10, 7), R, hem=HEM_G),
            C((-4.5, 8, -3), (9, 6, 6), R)]),
        P('strips', 'body', (0, 14, 0), cubes=[
            C((-4, 0, -3.1), (8, 8, 0), R, plane=True, tatter=True, hem=HEM_G),
            C((-4, 0, 3.1), (8, 8, 0), R, plane=True, tatter=True, hem=HEM_G),
            C((-4.6, 0, -3), (0, 8, 6), R, plane=True, tatter=True),
            C((4.6, 0, -3), (0, 8, 6), R, plane=True, tatter=True)]),
        P('head', 'body', (0, -12, 0), cubes=[
            C((-3, -7, -3), (6, 7, 6), 'marble', decals=[('front', 'mask', dict(color='#ffe7a3'))]),
            C((-3.5, -8, -3.5), (7, 8, 7), R, hide=('bottom',), decals=[('front', 'hood_opening', dict(w=0.84, top=0.14))])]),
    ]
    parts += ring('ring_a', 'body', (0, -3, 0), 9, 16, 3, 'light_gold', 'xz')
    parts += ring('ring_b', 'body', (0, -11, 5), 7, 12, 3, 'light_gold', 'xy')
    parts += [
        P('arm_r', 'body', (-5, -10, 0), cubes=[C((-2, -1, -2), (3, 9, 4), R), C((-2.5, 6, -2.5), (4, 3, 5), G)]),
        P('orb', 'arm_r', (-0.5, 12, -1), cubes=[C((-1.5, -1.5, -1.5), (3, 3, 3), 'light_gold'), C((-2, -2, -2), (4, 4, 4), 'gold_cage', dil=0.05)]),
        P('arm_l', 'body', (5, -10, 0), cubes=[C((-1, -1, -2), (3, 9, 4), R), C((-1.5, 6, -2.5), (4, 3, 5), G)]),
        P('sigil', 'body', (0, -7, -7), cubes=[C((-5, -5, 0), (10, 10, 0), 'sigil', plane=True)]),
    ]
    return parts

def model_archon():
    M, G, R = 'marble', 'gold', 'robe_white'
    parts = [
        P('body', None, (0, -4, 0), cubes=[
            C((-6, -14, -3.5), (12, 14, 7), M, trim=True, decals=[('front', 'sun_emblem', dict(y=0.38, r=0.3))]),
            C((-4.5, 0, -3), (9, 3, 6), G),
            C((-6, 3, -4), (12, 12, 8), M, trim=True, bands=3),
            C((-5, 15, -3.5), (10, 8, 7), R, hem=HEM_G)]),
        P('strips', 'body', (0, 23, 0), cubes=[
            C((-5, 0, -3.6), (10, 6, 0), R, plane=True, tatter=True, hem=HEM_G),
            C((-5, 0, 3.6), (10, 6, 0), R, plane=True, tatter=True, hem=HEM_G)]),
        P('head', 'body', (0, -14, 0), cubes=[C((-4, -9, -4), (8, 9, 8), G, decals=[('front', 'eye_sigil', dict(color='#a8f4ff', scale=0.95, y=0.5))])]),
        P('crown', 'head', (0, -9, 0)),
    ]
    parts += radial_spikes('spike', 'crown', 8, 3.0, 4, 'light_gold', 0.42, 0.0, long_idx=0)
    parts += ring('halo_outer', 'head', (0, -5, 5), 10, 18, 3, 'light_gold', 'xy')
    parts += ring('halo_inner', 'head', (0, -5, 5.5), 6.5, 12, 3, 'light_cyan', 'xy')
    parts += [
        P('wing_r1', 'body', (-3, -12, 3.6), (0, 0.35, 0.6), cubes=[C((-22, -14, 0), (22, 16, 0), 'light_feather', plane=True, side='r')]),
        P('wing_l1', 'body', (3, -12, 3.6), (0, -0.35, -0.6), cubes=[C((0, -14, 0), (22, 16, 0), 'light_feather', plane=True, side='l')]),
        P('wing_r2', 'body', (-3, -7, 3.6), (0, 0.65, 0.05), cubes=[C((-18, -6, 0), (18, 12, 0), 'light_feather', plane=True, side='r')]),
        P('wing_l2', 'body', (3, -7, 3.6), (0, -0.65, -0.05), cubes=[C((0, -6, 0), (18, 12, 0), 'light_feather', plane=True, side='l')]),
        P('wing_r3', 'body', (-3, -2, 3.6), (0, 0.9, -0.5), cubes=[C((-14, 0, 0), (14, 10, 0), 'light_feather', plane=True, side='r')]),
        P('wing_l3', 'body', (3, -2, 3.6), (0, -0.9, 0.5), cubes=[C((0, 0, 0), (14, 10, 0), 'light_feather', plane=True, side='l')]),
        P('arm_r', 'body', (-7.5, -12, 0), cubes=[C((-3, 0, -2.5), (5, 13, 5), M), C((-3.5, 9, -3), (6, 5, 6), G)]),
        P('pauldron_r', 'arm_r', (0, 0, 0), cubes=[C((-4.5, -3.5, -4), (7, 6, 8), G, dil=0.05)]),
        P('spear', 'arm_r', (-0.5, 12, 0), cubes=[C((-0.5, -30, -0.5), (1, 40, 1), G), C((-1, -37, -1), (2, 7, 2), 'light_blade'), C((-1.5, -31, -1.5), (3, 2, 3), G)]),
        P('arm_l', 'body', (7.5, -12, 0), cubes=[C((-2, 0, -2.5), (5, 13, 5), M), C((-2.5, 9, -3), (6, 5, 6), G)]),
        P('pauldron_l', 'arm_l', (0, 0, 0), cubes=[C((-2.5, -3.5, -4), (7, 6, 8), G, dil=0.05)]),
        P('hand_sigil', 'arm_l', (0.5, 15, -3), (-1.2, 0, 0), cubes=[C((-4, -4, 0), (8, 8, 0), 'sigil', plane=True)]),
    ]
    return parts

MODELS = [
    # name, java class, parts, (minimum texture width in UV units)
    ('shade_legionnaire', 'ShadeLegionnaire', model_shade, 64),
    ('void_devourer', 'VoidDevourer', model_devourer, 64),
    ('void_seraph', 'VoidSeraph', model_seraph, 64),
    ('colossus', 'Colossus', model_colossus, 128),
    ('custodian_sentinel', 'CustodianSentinel', model_sentinel, 64),
    ('arbiter', 'Arbiter', model_arbiter, 64),
    ('archon', 'Archon', model_archon, 128),
]

# ================================================================ UV packing
def layout_size(s):
    sx, sy, sz = s
    return max(1, 2 * (sx + sz)), max(1, sz + sy)

def pack(parts, minw):
    cubes = [c for p in parts for c in p['cubes']]
    order = sorted(range(len(cubes)), key=lambda i: (-layout_size(cubes[i]['s'])[1], -layout_size(cubes[i]['s'])[0]))
    W = minw
    while True:
        x = y = rowh = 0; ok = True
        for i in order:
            w, h = layout_size(cubes[i]['s'])
            if w > W: ok = False; break
            if x + w > W: x = 0; y += rowh; rowh = 0
            cubes[i]['uv'] = (x, y); x += w; rowh = max(rowh, h)
        H = 1
        while H < y + rowh: H *= 2
        if ok and H <= W * 2: return W, max(H, 32)
        W *= 2

def faces_of(c):
    u, v = c['uv']; sx, sy, sz = c['s']
    return {'top': (u + sz, v, sx, sz), 'bottom': (u + sz + sx, v, sx, sz),
            'right': (u, v + sz, sz, sy), 'front': (u + sz, v + sz, sx, sy),
            'left': (u + sz + sx, v + sz, sz, sy), 'back': (u + 2 * sz + sx, v + sz, sx, sy)}

SIDES = ('right', 'front', 'left', 'back')

# ================================================================ materials
class Face:
    pass

def m_void_cloth(f, x, y, u, v, ux, uy):
    n = fbm(ux * 0.45, uy * 0.28, f.seed, 3)
    fold = math.sin(u * f.wu * 1.35 + n * 5.0)
    t = clamp(0.38 + 0.2 * fold + 0.55 * (n - 0.5))
    col = ramp(t, [hexc('#08060c'), hexc('#171023'), hexc('#2c1f40'), hexc('#46325f')])
    if (x + 2 * y) % 4 == 0: col = mul(col, 1.06)
    return col, 1.0, None

def m_robe(f, x, y, u, v, ux, uy):
    n = fbm(ux * 0.4, uy * 0.25, f.seed + 41, 3)
    fold = math.sin(u * f.wu * 1.2 + n * 4.5)
    col = ramp(clamp(0.55 + 0.22 * fold + 0.35 * (n - 0.5)), [hexc('#9c9382'), hexc('#d3cab9'), hexc('#efe9dd'), hexc('#fffdf6')])
    if (x + 2 * y) % 4 == 0: col = mul(col, 0.98)
    return col, 1.0, None

def m_void_flesh(f, x, y, u, v, ux, uy):
    n = fbm(ux * 0.4, uy * 0.4, f.seed + 21, 3)
    sw = fbm(ux * 0.8 + n * 2.6, uy * 0.8 - n * 2.1, f.seed + 22, 2)
    col = ramp(clamp(sw * n * 2.1 - 0.05), [hexc('#050309'), hexc('#130b1e'), hexc('#311a4f'), hexc('#5d3290')])
    glow = None
    if rnd(f.gx0 + x, f.gy0 + y, f.seed + 5) > 0.993:
        col = hexc('#9a68ff'); glow = mul(hexc('#9b59ff'), 0.7)
    return col, 1.0, glow

def m_wraps(f, x, y, u, v, ux, uy):
    band = ((ux * 0.9 + uy * 1.1) % 2.4) / 2.4
    col = mix(hexc('#120d19'), hexc('#2f2342'), 0.25 + 0.6 * math.sin(band * math.pi))
    if band < 0.08: col = mul(col, 0.55)
    col = mul(col, 0.82 + 0.35 * fbm(ux * 0.7, uy * 0.7, f.seed + 31, 2))
    return col, 1.0, None

def m_leather(f, x, y, u, v, ux, uy):
    n = fbm(ux * 0.8, uy * 0.8, f.seed + 51, 2)
    col = mix(hexc('#24170f'), hexc('#4d3423'), n)
    if f.h >= 4 and (y == 1 or y == f.h - 2) and x % 3 == 0: col = hexc('#8a6a4a')
    return col, 1.0, None

def m_bone(f, x, y, u, v, ux, uy):
    n = fbm(ux * 0.9, uy * 0.9, f.seed + 61, 2)
    col = mix(hexc('#9d9078'), hexc('#efe7d4'), clamp(0.35 + 0.8 * (n - 0.35) + 0.25 * (1 - v)))
    if rnd(f.gx0 + x, f.gy0 + y, f.seed + 62) > 0.95: col = mul(col, 0.8)
    return col, 1.0, None

def m_shadow_inner(f, x, y, u, v, ux, uy):
    n = fbm(ux * 0.6, uy * 0.6, f.seed + 71, 2)
    return mix(hexc('#020104'), hexc('#0d0716'), n), 1.0, None

def m_void_plate(f, x, y, u, v, ux, uy):
    n = fbm(ux * 0.5, uy * 0.5, f.seed + 9, 3)
    col = mix(hexc('#17151e'), hexc('#3d3a4c'), clamp(0.3 + 0.7 * (n - 0.5) + 0.3 * (1 - v)))
    seams = f.cube.get('seams', 2)
    if seams and f.name in SIDES and f.h >= 8:
        period = max(4, int(f.h / (seams + 1)))
        py = y % period
        if y > 1 and py == 0: col = mul(col, 0.45)
        elif y > 1 and py == 1: col = mul(col, 1.35)
    if rnd(int(ux * 3), int(uy * 9), f.seed + 8) > 0.965: col = mul(col, 1.25)
    if f.name in SIDES and f.w >= 8 and f.h >= 8 and (x in (2, f.w - 3)) and (y in (2, f.h - 3)):
        col = hexc('#77728a')
    return col, 1.0, None

def m_void_crystal(f, x, y, u, v, ux, uy):
    off = 0.5 if f.name in ('left', 'back', 'bottom') else 0.0
    fac = (u * 1.7 + v * 2.3 + off) % 1.0
    band = abs(fac - 0.5) * 2
    col = ramp(clamp(0.22 + 0.55 * (1 - band) + 0.22 * (1 - v)), [hexc('#0e0519'), hexc('#3a146f'), hexc('#8547ff'), hexc('#ecd8ff')])
    glow = mul(hexc('#7a2cff'), 0.25 + 0.45 * (1 - band))
    if x == 0 or y == 0 or x == f.w - 1 or y == f.h - 1:
        col = mix(col, hexc('#f2e2ff'), 0.5); glow = mul(hexc('#cfa2ff'), 0.8)
    return col, 1.0, glow

def m_light(core, edge, gk=1.0):
    core, edge = hexc(core), hexc(edge)
    def fn(f, x, y, u, v, ux, uy):
        e = clamp(min(u, 1 - u, v, 1 - v) * 3.0)
        col = mix(edge, core, e)
        return col, 1.0, mul(col, gk)
    return fn

def m_light_blade(f, x, y, u, v, ux, uy):
    e = min(u, 1 - u, v, 1 - v)
    edge = e < 0.18
    col = hexc('#fffaf0') if edge else mix(hexc('#f3d68a'), hexc('#fff3cc'), fbm(ux * 0.5, uy * 0.5, f.seed, 2))
    glow = mul(hexc('#ffe7a8'), 1.0 if edge else 0.55)
    return col, 1.0, glow

def m_marble(f, x, y, u, v, ux, uy):
    n = fbm(ux * 0.35, uy * 0.35, f.seed + 3, 3)
    vein = abs(math.sin(ux * 0.55 + uy * 0.25 + n * 9.0))
    col = mix(hexc('#cfc7b8'), hexc('#f6f2ea'), clamp(n * 1.3 - 0.1))
    if vein < 0.06: col = mix(col, hexc('#8f877b'), 0.55)
    elif vein < 0.13: col = mix(col, hexc('#b3ab9e'), 0.3)
    bands = f.cube.get('bands', 0)
    if bands and f.name in SIDES:
        period = max(3, int(f.h / bands))
        if y % period == period - 1: col = hexc('#b8862e')
        elif y % period == period - 2: col = mul(col, 0.8)
    return col, 1.0, None

def m_gold(f, x, y, u, v, ux, uy):
    n = fbm(ux * 0.6, uy * 0.6, f.seed + 5, 2)
    t = clamp(0.55 + 0.3 * math.sin(u * 3.2 + v * 1.3 + n * 2) - 0.25 * v + 0.2 * (n - 0.5))
    col = ramp(t, [hexc('#4f2f07'), hexc('#94621a'), hexc('#d6a13f'), hexc('#ffe7a3')])
    if f.w >= 10 and f.h >= 10 and ((x + y) % 8 == 0 or (x - y) % 8 == 0): col = mul(col, 0.9)
    return col, 1.0, None

def m_gold_cage(f, x, y, u, v, ux, uy):
    if x in (0, f.w - 1) or y in (0, f.h - 1) or abs(u - 0.5) < 0.13 or abs(v - 0.5) < 0.13:
        return m_gold(f, x, y, u, v, ux, uy)
    return None

def m_obsidian(f, x, y, u, v, ux, uy):
    cx, cy = ux / 2.6, uy / 2.6
    ix, iy = math.floor(cx), math.floor(cy)
    b1 = b2 = 9.0; bid = 0.0
    for oy in (-1, 0, 1):
        for ox in (-1, 0, 1):
            gx, gy = ix + ox, iy + oy
            px, py = gx + _h(gx, gy, f.seed), gy + _h(gx, gy, f.seed + 1)
            d = (px - cx) ** 2 + (py - cy) ** 2
            if d < b1: b2 = b1; b1 = d; bid = _h(gx, gy, f.seed + 2)
            elif d < b2: b2 = d
    edge = math.sqrt(b2) - math.sqrt(b1)
    col = mix(hexc('#0a0710'), hexc('#2b1f40'), 0.2 + 0.65 * bid)
    if edge < 0.07: col = mix(col, hexc('#5c4884'), 0.55)
    return col, 1.0, None

def m_feather(dark, mid, light, tip):
    dark, mid, light, tip = hexc(dark), hexc(mid), hexc(light), hexc(tip)
    def fn(f, x, y, u, v, ux, uy):
        side = f.cube.get('side', 'r')
        d = (1 - u) if (side == 'r') == (f.name == 'front') else u
        lead = 0.03 + 0.28 * d * d
        N = 7; k = d * N; ff = k - int(k)
        trail = 1.0 - 0.36 * d ** 1.3 - 0.07 * (1 - math.sin(math.pi * ff))
        if v < lead or v > trail: return None
        rel = (v - lead) / max(0.01, trail - lead)
        if rel < 0.42:
            k2 = d * N * 2.3 + rel * 2.5; f2 = k2 - int(k2)
            col = mix(dark, mid, 0.35 + 0.45 * math.sin(math.pi * f2))
            if f2 < 0.08: col = mul(col, 0.7)
        else:
            col = mix(dark, mid, 0.3 + 0.55 * (1 - abs(ff - 0.5) * 2))
            if abs(ff - 0.5) < 0.07: col = mix(col, light, 0.7)
            if ff < 0.06 or ff > 0.94: col = mul(col, 0.62)
        g = smooth(clamp((rel - 0.72) / 0.28))
        if g > 0: col = mix(col, tip, g * 0.7)
        return col, 1.0, (mul(tip, g) if g > 0.05 else None)
    return fn

def m_sigil(f, x, y, u, v, ux, uy):
    cx, cy = u - 0.5, v - 0.5
    r = math.hypot(cx, cy) * 2; a = math.atan2(cy, cx)
    on = abs(r - 0.92) < 0.055 or abs(r - 0.72) < 0.04 or r < 0.12
    t = (a + math.pi) / (2 * math.pi) * 24
    if 0.76 < r < 0.88 and int(t) % 2 == 0 and abs(t % 1 - 0.5) < 0.2: on = True
    pts = [(0.68 * math.cos(-math.pi / 2 + i * 2 * math.pi / 3), 0.68 * math.sin(-math.pi / 2 + i * 2 * math.pi / 3)) for i in range(3)]
    px, py = cx * 2, cy * 2
    for i in range(3):
        (x0, y0), (x1, y1) = pts[i], pts[(i + 1) % 3]
        dx, dy = x1 - x0, y1 - y0; tt = clamp(((px - x0) * dx + (py - y0) * dy) / (dx * dx + dy * dy))
        if math.hypot(px - x0 - tt * dx, py - y0 - tt * dy) < 0.04: on = True
    if not on: return None
    return hexc('#ffeab0'), 1.0, hexc('#ffd36b')

MATS = {
    'void_cloth': m_void_cloth, 'robe_white': m_robe, 'void_flesh': m_void_flesh, 'wraps': m_wraps,
    'leather': m_leather, 'bone': m_bone, 'shadow_inner': m_shadow_inner, 'void_plate': m_void_plate,
    'void_crystal': m_void_crystal, 'light_violet': m_light('#f6ecff', '#a45cff'),
    'light_gold': m_light('#fffbe8', '#ffc94d'), 'light_cyan': m_light('#f2feff', '#5fe3ff'),
    'light_blade': m_light_blade, 'marble': m_marble, 'gold': m_gold, 'gold_cage': m_gold_cage,
    'obsidian': m_obsidian, 'sigil': m_sigil,
    'void_feather': m_feather('#07050b', '#1f1630', '#4a3a66', '#b277ff'),
    'light_feather': m_feather('#c9bfa9', '#f3eee2', '#ffffff', '#ffd36b'),
}
FACE_K = {'top': 1.06, 'bottom': 0.72, 'front': 1.0, 'back': 0.9, 'right': 0.95, 'left': 0.95}

# ================================================================ decals
def inside_slit(px, py, cx, cy, hw, hh):
    return abs(px - cx) <= hw and abs(py - cy) <= hh * (1 - (abs(px - cx) / hw) ** 2.5)

def decal(f, img, glow, kind, prm):
    W, H = f.w, f.h
    X0, Y0 = f.gx0, f.gy0
    col = hexc(prm.get('color', '#c77dff'))
    def put(x, y, c, a=1.0, g=None, gk=1.0):
        if 0 <= x < W and 0 <= y < H:
            img.over(X0 + x, Y0 + y, c, a)
            if g is not None: glow.add(X0 + x, Y0 + y, g, gk)
    if kind == 'eyes':
        style = prm.get('style', 'slit')
        if style == 'slit':
            ew, eh = prm.get('ew', 1.6) * S, 0.5 * S
            for sgn in (-1, 1):
                cx, cy = W * (0.5 + sgn * prm.get('sep', 0.22)), H * prm.get('y', 0.5)
                for y in range(H):
                    for x in range(W):
                        px, py = x + 0.5, y + 0.5
                        if inside_slit(px, py, cx, cy, ew + 1, eh + 1): put(x, y, (0.01, 0.0, 0.02))
                        if inside_slit(px, py, cx, cy, ew, eh):
                            k = 1 - abs(px - cx) / ew
                            put(x, y, mix(col, (1, 1, 1), k * 0.6), 1.0, mix(col, (1, 1, 1), k * 0.5), 1.0)
        else:
            spots = [(0.16, 0.2, 0.7), (0.3, 0.13, 0.55), (0.11, 0.33, 0.45)]
            for (ex, ey, r) in spots:
                for sx in (ex, 1 - ex):
                    cx, cy, rr = sx * W, ey * H, r * S
                    for y in range(H):
                        for x in range(W):
                            d = math.hypot(x + 0.5 - cx, y + 0.5 - cy)
                            if d <= rr + 0.6: put(x, y, (0.02, 0.0, 0.03))
                            if d <= rr: put(x, y, mix(col, (1, 1, 1), 0.5 * (1 - d / rr)), 1.0, col, 1.0)
    elif kind == 'eye_sigil':
        cx, cy = W * 0.5, H * prm.get('y', 0.5)
        a, b = W * 0.42 * prm.get('scale', 0.9), H * 0.2 * prm.get('scale', 0.9)
        for y in range(H):
            for x in range(W):
                px, py = (x + 0.5 - cx) / a, (y + 0.5 - cy) / b
                lim = 1 - px * px
                if abs(px) <= 1.08 and abs(py) <= lim * 1.25 + 0.12: put(x, y, (0.04, 0.02, 0.05))
                if abs(px) <= 1 and abs(py) <= lim:
                    rr = math.hypot(px * a, py * b) / (b * 0.95)
                    if rr < 1.0:
                        c = mix(mix(col, (1, 1, 1), 0.65), col, rr)
                        if abs(x + 0.5 - cx) < max(0.6, 0.12 * b) and rr < 0.85: c = (0.02, 0.0, 0.03); put(x, y, c)
                        else: put(x, y, c, 1.0, c, 1.0)
                    else: put(x, y, mix((0.08, 0.06, 0.1), col, 0.18), 1.0, col, 0.15)
        put(int(cx - b * 0.35), int(cy - b * 0.35), (1, 1, 1), 1.0, (1, 1, 1), 1.0)
    elif kind == 'visor_t' or kind == 'visor_line':
        for y in range(H):
            for x in range(W):
                u, v = (x + 0.5) / W, (y + 0.5) / H
                on = abs(v - prm.get('y', 0.42)) < 0.07 and abs(u - 0.5) < 0.38
                if kind == 'visor_t': on = on or (abs(u - 0.5) < 0.075 and prm.get('y', 0.42) < v < 0.86)
                if on:
                    k = 1 - abs(u - 0.5) * 1.6
                    put(x, y, mix(col, (1, 1, 1), 0.4 * k), 1.0, mix(col, (1, 1, 1), 0.3 * k), 1.0)
                elif (abs(v - prm.get('y', 0.42)) < 0.12 and abs(u - 0.5) < 0.42):
                    put(x, y, (0.05, 0.04, 0.05), 0.85)
    elif kind == 'hood_opening':
        top, w = prm.get('top', 0.2), prm.get('w', 0.75)
        for y in range(H):
            for x in range(W):
                u, v = (x + 0.5) / W, (y + 0.5) / H
                if v <= top: continue
                hw = (w / 2) * min(1.0, math.sqrt((v - top) / 0.32))
                d = abs(u - 0.5)
                if d < hw: img.set(X0 + x, Y0 + y, (0, 0, 0), 0.0)
                elif d < hw + 1.2 / W: put(x, y, (0.02, 0.01, 0.03), 0.8)
    elif kind == 'sun_emblem':
        cx, cy = W * 0.5, H * prm.get('y', 0.45)
        R = min(W, H) * prm.get('r', 0.3)
        gold = hexc('#f6c75a')
        for y in range(H):
            for x in range(W):
                dx, dy = x + 0.5 - cx, y + 0.5 - cy
                d = math.hypot(dx, dy) / R; a = math.atan2(dy, dx)
                ray = 0.72 < d < 1.0 and abs(((a / (2 * math.pi) * 12) % 1) - 0.5) < 0.22 * (1.0 - d) / 0.28
                if d < 0.42: put(x, y, mix(hexc('#fff3c4'), gold, d / 0.42), 1.0, hexc('#ffd36b'), 0.55)
                elif 0.5 < d < 0.62 or ray: put(x, y, mix(gold, hexc('#9c6a1c'), (d - 0.5)), 1.0, hexc('#ffb83a'), 0.25)
    elif kind == 'runes':
        cy0 = int(H * prm.get('y', 0.3))
        gw, gh = 3 * S, 4 * S
        n = max(1, (W - 2) // (gw + S))
        x0 = (W - n * (gw + S) + S) // 2
        for i in range(n):
            sd = f.seed * 31 + i * 7
            segs = [s for s in range(7) if _h(i, s, sd) > 0.45] or [0, 3]
            for s in segs:
                for t in range(gh if s in (0, 1, 2) else gw):
                    if s == 0: px, py = 0, t
                    elif s == 1: px, py = gw - 1, t
                    elif s == 2: px, py = gw // 2, t
                    elif s == 3: px, py = t, 0
                    elif s == 4: px, py = t, gh // 2
                    elif s == 5: px, py = t, gh - 1
                    else: px, py = t, int(t * (gh - 1) / max(1, gw - 1))
                    put(x0 + i * (gw + S) + px, cy0 + py, mix(col, (1, 1, 1), 0.3), 1.0, col, 1.0)
    elif kind == 'ribs':
        rc = hexc('#d8c8ff') if prm.get('light') else hexc('#6d5c86')
        for y in range(H):
            for x in range(W):
                u, v = (x + 0.5) / W, (y + 0.5) / H
                yy = v * 4.0 + (u - 0.5) ** 2 * 1.6
                if 0.4 < v < 0.95 and abs(yy % 1.0 - 0.5) < 0.12 and abs(u - 0.5) > 0.07:
                    put(x, y, rc, 0.85, (mul(hexc('#a66bff'), 0.5) if prm.get('light') else None), 1.0)
    elif kind == 'fangs':
        where = prm.get('where', 'bottom')
        fw = 1.5 * S; fh = 1.8 * S
        for y in range(H):
            for x in range(W):
                py = (H - 1 - y) if where == 'bottom' else y
                lx = (x + 0.5) % fw / fw
                limit = fh * (1 - abs(lx - 0.5) * 2)
                if py + 0.5 < limit: put(x, y, mix(hexc('#f4ecdc'), hexc('#bfb29a'), py / max(1, fh)))
                elif py < limit + 1.2: put(x, y, (0.05, 0.01, 0.04))
    elif kind == 'mask':
        for y in range(H):
            for x in range(W):
                u, v = (x + 0.5) / W, (y + 0.5) / H
                if abs(u - 0.5) < 0.07 and 0.22 < v < 0.82:
                    k = 1 - abs(u - 0.5) / 0.07
                    put(x, y, mix(col, (1, 1, 1), 0.5 * k), 1.0, col, 1.0)
                elif abs(v - 0.2) < 0.045 and abs(u - 0.5) < 0.36:
                    put(x, y, hexc('#c99536'))
                elif (abs(u - 0.22) + abs(v - 0.55) < 0.07) or (abs(u - 0.78) + abs(v - 0.55) < 0.07):
                    put(x, y, hexc('#e2b04a'), 1.0, hexc('#ffcf5a'), 0.4)

# ================================================================ paint models
def paint_model(parts, W, H):
    img, glow = Img(W * S, H * S), Img(W * S, H * S)
    ci = 0
    for p in parts:
        for c in p['cubes']:
            ci += 1
            mat = MATS[c['mat']]
            plane = c.get('plane', False)
            for fname, (fu, fv, fw, fh) in faces_of(c).items():
                if fw <= 0 or fh <= 0: continue
                f = Face(); f.name = fname; f.cube = c; f.seed = ci * 17 + 3
                f.w, f.h = fw * S, fh * S; f.wu, f.hu = fw, fh; f.gx0, f.gy0 = fu * S, fv * S
                hidden = fname in c.get('hide', ())
                for y in range(f.h):
                    for x in range(f.w):
                        if hidden: continue
                        u, v = (x + 0.5) / f.w, (y + 0.5) / f.h
                        ux, uy = (f.gx0 + x + 0.5) / S, (f.gy0 + y + 0.5) / S
                        r = mat(f, x, y, u, v, ux, uy)
                        if r is None: continue
                        col, a, g = r
                        if c.get('tatter') and fname in SIDES:
                            pc = u if fname in ('front', 'left') else 1 - u
                            jag = (0.6 + 2.2 * vnoise(pc * f.wu * 0.9, 3.3, ci)) * S
                            if vnoise(pc * f.wu * 0.45, 7.7, ci) > 0.72: jag += 2.5 * S
                            if (f.h - y) < jag: continue
                        hem = c.get('hem')
                        if hem and fname in SIDES:
                            hb = f.h - y
                            tj = (0.6 + 2.2 * vnoise((u if fname in ('front', 'left') else 1 - u) * f.wu * 0.9, 3.3, ci)) * S if c.get('tatter') else 0
                            if hb - tj < 1.6 * S: col = mix(hexc(hem), col, 0.25)
                            elif hb - tj < 2.1 * S: col = mul(hexc(hem), 1.25)
                        if c.get('cracks') and c['mat'] != 'void_crystal':
                            cr = c['cracks']; rr = abs(fbm(ux * 0.22, uy * 0.22, ci + 77, 2) - 0.5)
                            if rr < 0.026 * cr + 0.008: col = hexc('#b46cff'); g = hexc('#c88cff')
                            elif rr < 0.05 * cr + 0.012: col = mix(col, hexc('#6a2bb8'), 0.6); g = mul(hexc('#7a3cff'), 0.45)
                        k = FACE_K[fname]
                        if not plane:
                            if fname in SIDES: k *= lerp(1.07, 0.86, v)
                            edge = min(x, y, f.w - 1 - x, f.h - 1 - y)
                            if fname in SIDES:
                                if y == 0: k *= 1.16
                                elif y == f.h - 1: k *= 0.7
                                elif x == 0 or x == f.w - 1: k *= 0.86
                            elif edge == 0: k *= 0.88
                            if c.get('trim') and f.w >= 8 and f.h >= 8 and edge <= 1:
                                col = ramp(0.7 - 0.2 * v + (0.2 if edge == 1 else -0.25), [hexc('#5a3a0c'), hexc('#a8761f'), hexc('#f0c35c'), hexc('#fff0bd')])
                        else:
                            k = 1.0 if fname == 'front' else 0.92
                        img.set(f.gx0 + x, f.gy0 + y, mul(col, k), a)
                        if g is not None: glow.add(f.gx0 + x, f.gy0 + y, g, 1.0)
                if not hidden:
                    for (dface, kind, prm) in c.get('decals', []):
                        if dface == fname: decal(f, img, glow, kind, prm)
    return img, glow

# ================================================================ java geometry
def jf(v): return ('%.4f' % v).rstrip('0').rstrip('.') + 'F' if v != 0 else '0.0F'
def camel(s):
    parts = s.split('_'); return parts[0] + ''.join(p[:1].upper() + p[1:] for p in parts[1:])

def java_geo(cls, parts, W, H):
    L = []
    L.append('// GENERATED by tools/assetgen.py - do not edit, change the generator instead.')
    L.append('package %s;' % JAVA_PKG)
    L.append('')
    L.append('import net.minecraft.client.model.Dilation;')
    L.append('import net.minecraft.client.model.ModelData;')
    L.append('import net.minecraft.client.model.ModelPart;')
    L.append('import net.minecraft.client.model.ModelPartBuilder;')
    L.append('import net.minecraft.client.model.ModelPartData;')
    L.append('import net.minecraft.client.model.ModelTransform;')
    L.append('import net.minecraft.client.model.TexturedModelData;')
    L.append('import net.minecraft.client.render.entity.model.SinglePartEntityModel;')
    L.append('import net.minecraft.entity.Entity;')
    L.append('')
    L.append('public abstract class %sGeo<T extends Entity> extends SinglePartEntityModel<T> {' % cls)
    L.append('    protected final ModelPart root;')
    for p in parts: L.append('    protected final ModelPart %s;' % camel(p['name']))
    L.append('')
    L.append('    protected %sGeo(ModelPart root) {' % cls)
    L.append('        this.root = root;')
    for p in parts:
        par = 'root' if p['parent'] is None else 'this.' + camel(p['parent'])
        L.append('        this.%s = %s.getChild("%s");' % (camel(p['name']), par, p['name']))
    L.append('    }')
    L.append('')
    L.append('    @Override')
    L.append('    public ModelPart getPart() {')
    L.append('        return this.root;')
    L.append('    }')
    L.append('')
    L.append('    /** Restores the rest pose so animations can be written additively. */')
    L.append('    protected void resetPose() {')
    for p in parts:
        n = camel(p['name']); (px, py, pz), (rx, ry, rz) = p['pivot'], p['rot']
        L.append('        %s.pivotX = %s; %s.pivotY = %s; %s.pivotZ = %s; %s.pitch = %s; %s.yaw = %s; %s.roll = %s;' %
                 (n, jf(px), n, jf(py), n, jf(pz), n, jf(rx), n, jf(ry), n, jf(rz)))
    L.append('    }')
    L.append('')
    L.append('    public static TexturedModelData getTexturedModelData() {')
    L.append('        ModelData modelData = new ModelData();')
    L.append('        ModelPartData d_root = modelData.getRoot();')
    for p in parts:
        b = 'ModelPartBuilder.create()'
        for c in p['cubes']:
            (ox, oy, oz), (sx, sy, sz) = c['o'], c['s']
            b += '.uv(%d, %d).cuboid(%s, %s, %s, %s, %s, %s, new Dilation(%s))' % (c['uv'][0], c['uv'][1], jf(ox), jf(oy), jf(oz), jf(sx), jf(sy), jf(sz), jf(c['dil']))
        (px, py, pz), (rx, ry, rz) = p['pivot'], p['rot']
        par = 'd_root' if p['parent'] is None else 'd_' + p['parent']
        L.append('        ModelPartData d_%s = %s.addChild("%s", %s, ModelTransform.of(%s, %s, %s, %s, %s, %s));' %
                 (p['name'], par, p['name'], b, jf(px), jf(py), jf(pz), jf(rx), jf(ry), jf(rz)))
    L.append('        return TexturedModelData.of(modelData, %d, %d);' % (W, H))
    L.append('    }')
    L.append('}')
    return '\n'.join(L) + '\n'

# ================================================================ misc textures
def tex_shadow_veil():
    img = Img(64, 64)
    for y in range(64):
        for x in range(64):
            n = fbm(x / 9.0, y / 9.0, 901, 4)
            img.set(x, y, mul((1, 1, 1), 0.55 + 0.45 * n), 0.82 + 0.18 * n)
    return img

def tex_disk():
    img = Img(128, 32)
    for y in range(32):
        for x in range(128):
            r = y / 31.0
            a = x / 128.0
            streak = fbm(a * 24.0, r * 3.0 + a * 6.0, 911, 3)
            heat = (1 - r) ** 1.6
            k = clamp(heat * (0.55 + 0.9 * streak) * smooth(clamp(r * 6)))
            c = ramp(k, [hexc('#000000'), hexc('#2a0c5c'), hexc('#7d3cff'), hexc('#c9a2ff'), hexc('#ffffff')])
            img.set(x, y, c, 1.0)
    return img

def tex_halo():
    img = Img(64, 64)
    for y in range(64):
        for x in range(64):
            r = math.hypot(x + 0.5 - 32, y + 0.5 - 32) / 32.0
            ring = math.exp(-((r - 0.36) / 0.035) ** 2) * 1.1
            soft = math.exp(-((r - 0.36) / 0.22) ** 2) * 0.35 if r > 0.3 else 0
            k = clamp(ring + soft) if r < 1 else 0
            img.set(x, y, mix(hexc('#000000'), mix(hexc('#8f5cff'), hexc('#ffffff'), clamp(ring)), k), 1.0)
    return img

def tex_flat(col, w=16, h=16):
    img = Img(w, h)
    for y in range(h):
        for x in range(w): img.set(x, y, hexc(col), 1.0)
    return img

def tex_atom(frame):
    cv = Canvas(16, 16, 4)
    cv.glow(8, 8, 7.5, (1, 1, 1), 0.35)
    for i in range(3):
        ang = i * math.pi / 3 + frame * math.pi / 8
        cv.ellipse_ring(8, 8, 6.6, 2.3, ang, 0.75, (0.85, 0.85, 0.9), 0.85)
        t = frame * 1.2 + i * 2.1
        ca, sa = math.cos(ang), math.sin(ang)
        lx, ly = 6.6 * math.cos(t), 2.3 * math.sin(t)
        cv.circle(8 + lx * ca - ly * sa, 8 + lx * sa + ly * ca, 1.05, (1, 1, 1))
    cv.circle(8, 8, 2.0, (1, 1, 1))
    return cv.img()

def tex_spark(frame):
    cv = Canvas(16, 16, 4)
    s = [1.0, 0.8, 0.55, 0.3][frame]
    cv.glow(8, 8, 7 * s + 1, (1, 1, 1), 0.5)
    cv.poly([(8, 8 - 7.5 * s), (8.9, 8), (8, 8 + 7.5 * s), (7.1, 8)], (1, 1, 1))
    cv.poly([(8 - 7.5 * s, 8), (8, 8.9), (8 + 7.5 * s, 8), (8, 7.1)], (1, 1, 1))
    cv.circle(8, 8, 1.6 * s + 0.4, (1, 1, 1))
    return cv.img()

DARK = hexc('#0a0610'); VIO = hexc('#a45cff'); VIOL = hexc('#d9b8ff'); CYAN = hexc('#7fe8ff'); GOLD = hexc('#f6c75a')

def outline_text_shape(cv, draw, w_out=1.2):
    draw(cv, DARK, w_out); draw(cv, None, 0)

def icon(name):
    cv = Canvas(32, 32, 4)
    if name == 'erasure':
        cv.circle(13, 9.5, 5.2, DARK); cv.poly([(5, 30), (21, 30), (18.5, 15), (7.5, 15)], DARK)
        cv.circle(13, 9.5, 4.2, hexc('#05030a')); cv.poly([(6.2, 29), (19.8, 29), (17.6, 16), (8.4, 16)], hexc('#05030a'))
        cv.ring(13, 9.5, 4.2, 0.9, VIO); cv.line(8.4, 16, 6.2, 29, 0.9, VIO); cv.line(17.6, 16, 19.8, 29, 0.9, VIO); cv.line(8.4, 16, 17.6, 16, 0.9, VIO)
        for i in range(14):
            x = 19 + _h(i, 1, 5) * 11; y = 6 + _h(i, 2, 5) * 22; s = 0.8 + _h(i, 3, 5) * 1.4
            cv.poly([(x - s, y - s), (x + s, y - s), (x + s, y + s), (x - s, y + s)], mix(VIO, (1, 1, 1), _h(i, 4, 5)), 1 - (x - 19) / 13)
    elif name == 'atomize':
        for i in range(3): cv.ellipse_ring(16, 16, 13, 5, i * math.pi / 3, 3.2, DARK)
        for i in range(3): cv.ellipse_ring(16, 16, 13, 5, i * math.pi / 3, 1.5, [CYAN, VIO, VIOL][i])
        for i in range(3):
            ang = i * math.pi / 3; t = 0.8 + i * 2.0
            lx, ly = 13 * math.cos(t), 5 * math.sin(t)
            cv.circle(16 + lx * math.cos(ang) - ly * math.sin(ang), 16 + lx * math.sin(ang) + ly * math.cos(ang), 2.1, (1, 1, 1))
        cv.glow(16, 16, 8, VIOL, 0.6); cv.circle(16, 16, 3.6, DARK); cv.circle(16, 16, 2.8, (1, 1, 1))
    elif name == 'recreate':
        cv.fill(lambda x, y: abs(math.hypot(x - 16, y - 16) - 12) <= 2.6 and not (math.atan2(y - 16, x - 16) > 1.9 and math.atan2(y - 16, x - 16) < 2.9), DARK)
        cv.fill(lambda x, y: abs(math.hypot(x - 16, y - 16) - 12) <= 1.3 and not (math.atan2(y - 16, x - 16) > 1.9 and math.atan2(y - 16, x - 16) < 2.9), CYAN)
        ax, ay = 16 + 12 * math.cos(1.85), 16 + 12 * math.sin(1.85)
        cv.poly([(ax - 4.6, ay - 2.2), (ax + 3.6, ay - 3.6), (ax + 0.4, ay + 4.4)], DARK); cv.poly([(ax - 3, ay - 1.4), (ax + 2.4, ay - 2.4), (ax + 0.3, ay + 2.8)], CYAN)
        top = [(16, 9), (22, 12), (16, 15), (10, 12)]; lf = [(10, 12), (16, 15), (16, 22), (10, 19)]; rt = [(16, 15), (22, 12), (22, 19), (16, 22)]
        for pts, c in ((top, VIOL), (lf, VIO), (rt, hexc('#6a34c2'))):
            cv.poly([(x + (x - 16) * 0.12, y + (y - 15.5) * 0.12) for x, y in pts], DARK); cv.poly(pts, c)
        for i in range(6): cv.circle(16 + 7 * math.cos(i), 15.5 + 7 * math.sin(i * 1.3), 0.9, (1, 1, 1), 0.8)
    elif name == 'singularity':
        cv.glow(16, 16, 15, VIO, 0.9); cv.ring(16, 16, 10, 2.4, VIOL)
        cv.ellipse_ring(16, 16, 14.5, 4, -0.35, 2.2, hexc('#ffd9a8'), 1.0, front=False)
        cv.circle(16, 16, 8.4, (1, 1, 1)); cv.circle(16, 16, 7.6, hexc('#000000'))
        cv.ellipse_ring(16, 16, 14.5, 4, -0.35, 2.2, hexc('#fff1d6'), 1.0, front=True)
    elif name == 'stasis':
        frame = [(8, 4), (24, 4), (24, 6.5), (8, 6.5)]; frame2 = [(8, 25.5), (24, 25.5), (24, 28), (8, 28)]
        cv.poly([(7, 3), (25, 3), (25, 7.5), (7, 7.5)], DARK); cv.poly([(7, 24.5), (25, 24.5), (25, 29), (7, 29)], DARK)
        cv.poly([(9, 6), (23, 6), (17.6, 16), (23, 26), (9, 26), (14.4, 16)], DARK)
        cv.poly([(10.5, 7), (21.5, 7), (16.6, 16), (21.5, 25), (10.5, 25), (15.4, 16)], hexc('#1b2a3d'), 0.9)
        cv.poly([(12.2, 8.5), (19.8, 8.5), (16, 14)], CYAN); cv.poly([(16, 19), (20.5, 24.5), (11.5, 24.5)], CYAN)
        cv.line(16, 14, 16, 19, 1.0, (1, 1, 1))
        cv.poly(frame, GOLD); cv.poly(frame2, GOLD)
        for (x, y) in ((5, 14), (27, 12), (26, 21)):
            cv.line(x - 2, y, x + 2, y, 0.8, (1, 1, 1)); cv.line(x, y - 2, x, y + 2, 0.8, (1, 1, 1))
    elif name == 'dominion':
        pts = [(4, 25), (4, 11), (10, 17), (16, 6), (22, 17), (28, 11), (28, 25)]
        cv.poly([(x + (x - 16) * 0.09, y + (y - 17) * 0.11) for x, y in pts], DARK); cv.poly(pts, GOLD)
        cv.poly([(4, 21), (28, 21), (28, 25), (4, 25)], hexc('#b07d22'))
        for x, y, r in ((4, 10.5, 2.2), (16, 5.5, 2.5), (28, 10.5, 2.2)): cv.circle(x, y, r + 0.8, DARK); cv.circle(x, y, r, VIOL)
        for x in (10, 16, 22): cv.circle(x, 23, 1.6, VIO)
    elif name == 'legion':
        for (cx, cy, s) in ((8, 13, 0.75), (24, 13, 0.75), (16, 16, 1.0)):
            cv.circle(cx, cy, 6.6 * s, DARK); cv.poly([(cx - 8 * s, cy + 14 * s), (cx + 8 * s, cy + 14 * s), (cx + 5 * s, cy + 3 * s), (cx - 5 * s, cy + 3 * s)], DARK)
            cv.circle(cx, cy, 5.6 * s, hexc('#241a35')); cv.poly([(cx - 7 * s, cy + 13 * s), (cx + 7 * s, cy + 13 * s), (cx + 4.5 * s, cy + 3.6 * s), (cx - 4.5 * s, cy + 3.6 * s)], hexc('#2c2040'))
            cv.circle(cx, cy + 0.6 * s, 3.6 * s, hexc('#040208'))
            for sg in (-1, 1): cv.line(cx + sg * 1.0 * s, cy + 0.5 * s, cx + sg * 2.6 * s, cy + 0.1 * s, 1.0 * s, VIOL)
    elif name == 'rewrite':
        cv.fill(lambda x, y: abs(math.hypot(x - 12, y - 20) - (2 + (math.atan2(y - 20, x - 12) + math.pi) * 1.25)) < 1.3 and math.hypot(x - 12, y - 20) < 10.5, VIO)
        q = [(27, 3), (29, 5), (13, 23), (10.5, 24.5), (11.5, 21.5)]
        cv.poly([(x + (x - 19) * 0.1, y + (y - 14) * 0.1) for x, y in q], DARK); cv.poly(q, hexc('#f4efe4'))
        cv.line(27.5, 4.5, 12, 23, 0.7, hexc('#9a8f7a')); cv.line(12, 23, 8, 28, 1.2, GOLD)
    elif name == 'blink':
        cv.ellipse_ring(23, 16, 4.5, 11, 0, 3.4, DARK); cv.ellipse_ring(23, 16, 4.5, 11, 0, 1.8, VIOL); cv.glow(23, 16, 10, VIO, 0.5)
        for i, x in enumerate((3, 7.5, 11.5)): cv.line(x, 16, x + 2.6, 16, 2.0, mix(CYAN, (1, 1, 1), i / 3), 0.45 + i * 0.2)
        cv.line(14.5, 16, 26, 16, 4.2, DARK); cv.poly([(25, 10.5), (31, 16), (25, 21.5)], DARK)
        cv.line(15, 16, 26, 16, 2.4, CYAN); cv.poly([(26, 12.5), (29.8, 16), (26, 19.5)], CYAN)
    return cv.img()

def icon_seal():
    cv = Canvas(18, 18, 4)
    cv.circle(9, 9, 8.2, DARK); cv.ring(9, 9, 6.8, 1.6, GOLD); cv.circle(9, 9, 5.6, hexc('#3a2a0c'))
    cv.circle(9, 7.6, 1.9, hexc('#fff0bd')); cv.poly([(8, 8.4), (10, 8.4), (11, 13), (7, 13)], hexc('#fff0bd'))
    for i in range(8):
        a = i * math.pi / 4; cv.line(9 + 7.6 * math.cos(a), 9 + 7.6 * math.sin(a), 9 + 8.8 * math.cos(a), 9 + 8.8 * math.sin(a), 0.9, GOLD)
    return cv.img()

def item_scepter():
    cv = Canvas(32, 32, 4)
    cv.glow(24, 8, 9, VIO, 0.55)
    cv.line(5, 28, 21, 12, 4.2, DARK); cv.line(5, 28, 21, 12, 2.4, hexc('#3a3648')); cv.line(5.6, 27, 20.4, 12.2, 0.9, hexc('#6f6a82'))
    for t in (0.18, 0.52, 0.86):
        x, y = 5 + 16 * t, 28 - 16 * t
        cv.line(x - 1.8, y - 1.8, x + 1.8, y + 1.8, 2.8, DARK); cv.line(x - 1.4, y - 1.4, x + 1.4, y + 1.4, 1.6, GOLD)
    cv.circle(4.5, 28.5, 2.8, DARK); cv.circle(4.5, 28.5, 1.9, GOLD)
    for sgn in (-1, 1):
        cv.fill(lambda x, y, sgn=sgn: abs(math.hypot(x - 23.5 + sgn * 3.2, y - 8.5 - sgn * 3.2) - 6.2) < 1.6 and ((x - 21) * sgn - (y - 11) * sgn) * 0 + (x + y) > 30.5 and (x + y) < 33.5 + 4 * 1, DARK)
    cv.ellipse_ring(23.5, 8.5, 7.4, 4.2, -math.pi / 4, 3.2, DARK, 1.0)
    cv.ellipse_ring(23.5, 8.5, 7.4, 4.2, -math.pi / 4, 1.5, GOLD, 1.0)
    d = [(24, 1.5), (29, 7.5), (24, 15.5), (19, 7.5)]
    cv.poly([(x + (x - 24) * 0.25, y + (y - 8.5) * 0.18) for x, y in d], DARK)
    cv.poly(d, VIO); cv.poly([(24, 1.5), (29, 7.5), (24, 8.5)], VIOL); cv.poly([(24, 8.5), (19, 7.5), (24, 15.5)], hexc('#5b25b0'))
    cv.circle(22.5, 5.5, 1.1, (1, 1, 1))
    return cv.img()

def item_spark():
    cv = Canvas(32, 32, 4)
    cv.glow(16, 16, 15, VIO, 0.75)
    for i in range(8):
        a = i * math.pi / 4; L = 14 if i % 2 == 0 else 8; w = 2.6 if i % 2 == 0 else 1.8
        ca, sa = math.cos(a), math.sin(a)
        cv.poly([(16 + ca * L, 16 + sa * L), (16 - sa * w, 16 + ca * w), (16 - ca * 2, 16 - sa * 2), (16 + sa * w, 16 - ca * w)], VIOL if i % 2 else (1, 1, 1))
    cv.ring(16, 16, 9.5, 1.0, VIO, 0.8)
    cv.circle(16, 16, 5.2, DARK); cv.circle(16, 16, 4.4, hexc('#e9d6ff')); cv.circle(16, 16, 2.4, (1, 1, 1))
    cv.fill(lambda x, y: abs(x - 16) < 0.6 and abs(y - 16) < 3.5, hexc('#2a0d55'))
    return cv.img()

def item_shard():
    cv = Canvas(32, 32, 4)
    cv.glow(16, 16, 13, hexc('#fff3c4'), 0.5)
    pts = [(16, 1.5), (22.5, 10), (20, 29), (12, 29), (9.5, 11)]
    cv.poly([(x + (x - 16) * 0.12, y + (y - 15) * 0.07) for x, y in pts], DARK)
    cv.poly(pts, hexc('#f3e7c8'))
    cv.poly([(16, 1.5), (22.5, 10), (16, 12)], (1, 1, 1)); cv.poly([(9.5, 11), (16, 12), (12, 29)], hexc('#d8c495'))
    cv.poly([(16, 12), (22.5, 10), (20, 29)], hexc('#e8d6a6'))
    cv.poly([(16, 9), (18.4, 16), (16, 24), (13.6, 16)], CYAN); cv.circle(16, 16, 1.4, (1, 1, 1))
    cv.line(9.5, 11, 12, 29, 0.7, GOLD); cv.line(22.5, 10, 20, 29, 0.7, GOLD)
    return cv.img()

def mod_icon():
    cv = Canvas(128, 128, 3)
    cv.fill(lambda x, y: True, lambda p: mix(hexc('#2a1250'), hexc('#040208'), clamp(math.hypot(p[0] - 64, p[1] - 64) / 80)))
    for i in range(70):
        x, y = _h(i, 1, 99) * 128, _h(i, 2, 99) * 128
        cv.circle(x, y, 0.4 + _h(i, 3, 99) * 0.8, (1, 1, 1), 0.3 + 0.6 * _h(i, 4, 99))
    cv.glow(64, 64, 60, VIO, 0.6)
    for i in range(24):
        a = i * math.pi / 12; L = 60 if i % 2 == 0 else 52
        ca, sa = math.cos(a), math.sin(a)
        cv.poly([(64 + ca * 44, 64 + sa * 44 - 0), (64 + ca * L - sa * 1.6, 64 + sa * L + ca * 1.6), (64 + ca * L + sa * 1.6, 64 + sa * L - ca * 1.6)], GOLD, 0.9)
    cv.ring(64, 64, 42, 6, DARK); cv.ring(64, 64, 42, 3.6, GOLD); cv.ring(64, 64, 42, 1.2, hexc('#fff0bd'))
    for i in range(3): cv.ellipse_ring(64, 64, 36, 12, i * math.pi / 3 + 0.3, 1.6, CYAN, 0.55)
    a, b = 30, 15
    cv.fill(lambda x, y: abs(x - 64) < a + 3 and abs(y - 64) < (b + 3) * (1 - ((x - 64) / (a + 3)) ** 2), DARK)
    cv.fill(lambda x, y: abs(x - 64) < a and abs(y - 64) < b * (1 - ((x - 64) / a) ** 2), hexc('#f2e9ff'))
    cv.circle(64, 64, 12.5, DARK)
    cv.fill(lambda x, y: math.hypot(x - 64, y - 64) < 11.5, lambda p: mix(hexc('#ffffff'), VIO, clamp(math.hypot(p[0] - 64, p[1] - 64) / 11.5)))
    cv.fill(lambda x, y: abs(x - 64) < 2.2 * (1 - abs(y - 64) / 11) and abs(y - 64) < 11, hexc('#0b0414'))
    cv.circle(59.5, 59.5, 2.4, (1, 1, 1))
    return cv.img()

POWERS = ['erasure', 'atomize', 'recreate', 'singularity', 'stasis', 'dominion', 'legion', 'rewrite', 'blink']

# ================================================================ main
def main(out):
    res = os.path.join(out, 'resources', 'assets', MODID)
    jdir = os.path.join(out, 'java', *JAVA_PKG.split('.'))
    os.makedirs(jdir, exist_ok=True)
    tex = os.path.join(res, 'textures')
    for name, cls, fn, minw in MODELS:
        parts = fn()
        names = [p['name'] for p in parts]
        assert len(names) == len(set(names)), 'duplicate part names in ' + name
        W, H = pack(parts, minw)
        img, glow = paint_model(parts, W, H)
        img.save(os.path.join(tex, 'entity', name + '.png'))
        glow.save(os.path.join(tex, 'entity', name + '_glow.png'))
        with open(os.path.join(jdir, cls + 'Geo.java'), 'w', encoding='utf-8') as fh:
            fh.write(java_geo(cls, parts, W, H))
        print('model %-20s %3dx%-3d uv, %2d parts' % (name, W, H, len(parts)))
    tex_shadow_veil().save(os.path.join(tex, 'entity', 'shadow_veil.png'))
    tex_disk().save(os.path.join(tex, 'entity', 'singularity_disk.png'))
    tex_halo().save(os.path.join(tex, 'entity', 'singularity_halo.png'))
    tex_flat('#000000').save(os.path.join(tex, 'entity', 'singularity_core.png'))
    for i in range(4):
        tex_atom(i).save(os.path.join(tex, 'particle', 'atom_%d.png' % i))
        tex_spark(i).save(os.path.join(tex, 'particle', 'spark_%d.png' % i))
    for i, pw in enumerate(POWERS): icon(pw).save(os.path.join(tex, 'gui', 'power', pw + '.png'))
    icon_seal().save(os.path.join(tex, 'mob_effect', 'seal.png'))
    item_scepter().save(os.path.join(tex, 'item', 'scepter_of_will.png'))
    item_spark().save(os.path.join(tex, 'item', 'demiurge_spark.png'))
    item_shard().save(os.path.join(tex, 'item', 'world_shard.png'))
    mod_icon().save(os.path.join(res, 'icon.png'))
    print('assets written to', out)

if __name__ == '__main__':
    main(sys.argv[1] if len(sys.argv) > 1 else 'build/generated/assetgen')
