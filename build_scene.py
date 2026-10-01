# Builds the Cybersensorn tabletop model (v2, tactical hardware + HUD) and exports
# cybersensorn.glb / .usdz / .blend.
# Run inside Blender (via the MCP add-on) or headless:
#   blender.exe --background --python build_scene.py
# Units are metres: the model is ~45 cm across so it sits on a table in AR.
import math, random
import bpy, bmesh
from mathutils import Matrix, Vector

OUT = r"C:\Users\esbjo\Blender AR"
FPS, LOOP = 24, 192  # 8 s loop

# Source hubs, in the presentation's order (HUB_IDS in src/visualization/network.ts)
HUBS = [
    ("N-01", "SKRAPNINGAR\nDIGITALA KANALER"),
    ("N-02", "TELEFONEXTRAKTIONER"),
    ("N-03", "EKONOMISKA\nTRANSAKTIONER"),
    ("N-04", "ANMÄLNINGSFLÖDET /\nFÖRUNDERSÖKNINGAR"),
    ("N-05", "UNDERRÄTTELSEFLÖDET"),
    ("N-06", "RESEDATA"),
    ("N-07", "INTERNATIONELL\nSAMVERKAN"),
]
N = len(HUBS)
SLAB_R, SLAB_TOP = 0.215, 0.010   # armoured lower slab (labels sit on it)
DECK_R, DECK_TOP = 0.158, 0.018   # radar deck
RING_R = 0.135                    # pylon ring. index.html mirrors RING_R, hub_pos and CORE.
LABEL_R = 0.168
CORE = Vector((0, 0, 0.0955))     # reactor core inside the tower cage
TOWER_TOP = 0.133
BR = 0.032                        # half size of the target bracket around each data cluster


def hub_angle(k):  # same as HUB_ANGLE: N-01 on the left, then clockwise
    return math.radians(180 - k * 360 / N)


def hub_pos(k):  # centre of the floating data cluster above pylon k
    a = hub_angle(k)
    return Vector((RING_R * math.cos(a), RING_R * math.sin(a), 0.10 + 0.012 * math.sin(k * 2.4)))


PHONE_A = (hub_angle(0) + hub_angle(N - 1) + 2 * math.pi) / 2  # between N-01 and N-07, front-left
PHONE = Vector((0.185 * math.cos(PHONE_A), 0.185 * math.sin(PHONE_A), SLAB_TOP + 0.0015))


# ---------- materials ----------
def lin(hex_):  # sRGB hex -> linear RGBA
    def c(v):
        v /= 255
        return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4
    return (*[c(int(hex_[i:i + 2], 16)) for i in (0, 2, 4)], 1)


def material(name, base, emit=None, strength=0.0, rough=0.5, metal=0.0, alpha=1.0):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    p = m.node_tree.nodes["Principled BSDF"]
    p.inputs["Base Color"].default_value = lin(base)
    p.inputs["Roughness"].default_value = rough
    p.inputs["Metallic"].default_value = metal
    if emit:
        p.inputs["Emission Color"].default_value = lin(emit)
        p.inputs["Emission Strength"].default_value = strength
    if alpha < 1:
        p.inputs["Alpha"].default_value = alpha
        m.blend_method = 'BLEND'
    return m


# ---------- geometry helpers (bmesh, no operators, so it also runs headless) ----------
def T(x, y, z):
    return Matrix.Translation((x, y, z))


def RZ(a):
    return Matrix.Rotation(a, 4, 'Z')


def polar(a, r, z):  # frame at angle a: local +X points outward, +Y along the tangent, +Z up
    return RZ(a) @ T(r, 0, z)


def box(bm, sx, sy, sz, m):
    bmesh.ops.create_cube(bm, size=1, matrix=m @ Matrix.Diagonal((sx, sy, sz, 1)))


def cyl(bm, r, h, m, seg=24, r2=None, caps=True):
    bmesh.ops.create_cone(bm, cap_ends=caps, segments=seg, radius1=r, radius2=r if r2 is None else r2, depth=h, matrix=m)


def sphere(bm, c, r, seg=16):
    bmesh.ops.create_uvsphere(bm, u_segments=seg, v_segments=max(seg // 2, 4), radius=r, matrix=Matrix.Translation(c))


def tube(bm, a, b, r=0.0006, seg=5):
    a, b = Vector(a), Vector(b)
    d = b - a
    rot = d.to_track_quat('Z', 'Y').to_matrix().to_4x4()
    bmesh.ops.create_cone(bm, cap_ends=False, segments=seg, radius1=r, radius2=r, depth=d.length,
                          matrix=Matrix.Translation((a + b) / 2) @ rot)


def path(bm, pts, r=0.0006, m=Matrix.Identity(4)):
    pts = [m @ Vector(p) for p in pts]
    for a, b in zip(pts, pts[1:]):
        tube(bm, a, b, r)


def torus(bm, R, r, m=Matrix.Identity(4), major=64, minor=6):
    vs = [[bm.verts.new(m @ Vector(((R + r * math.cos(j * 2 * math.pi / minor)) * math.cos(i * 2 * math.pi / major),
                                    (R + r * math.cos(j * 2 * math.pi / minor)) * math.sin(i * 2 * math.pi / major),
                                    r * math.sin(j * 2 * math.pi / minor))))
           for j in range(minor)] for i in range(major)]
    for i in range(major):
        for j in range(minor):
            bm.faces.new((vs[i][j], vs[(i + 1) % major][j], vs[(i + 1) % major][(j + 1) % minor], vs[i][(j + 1) % minor]))


def brackets(bm, c, h, L, r=0.0007):  # eight corner brackets of a cube: a 3D targeting frame
    for sx in (-1, 1):
        for sy in (-1, 1):
            for sz in (-1, 1):
                p = Vector(c) + Vector((sx * h, sy * h, sz * h))
                for d in (Vector((-sx * L, 0, 0)), Vector((0, -sy * L, 0)), Vector((0, 0, -sz * L))):
                    tube(bm, p, p + d, r)


def obj_from(bm, name, mat, loc=(0, 0, 0), parent=None):
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    me.polygons.foreach_set("use_smooth", [True] * len(me.polygons))
    me.set_sharp_from_angle(angle=math.radians(35))
    me.materials.append(mat)
    ob = bpy.data.objects.new(name, me)
    ob.location = loc
    ob.parent = parent
    bpy.context.scene.collection.objects.link(ob)
    return ob


def text(name, body, size, mat, loc, rot_z, align_y='TOP'):
    cu = bpy.data.curves.new(name, 'FONT')
    cu.body, cu.size, cu.align_x, cu.align_y = body, size, 'CENTER', align_y
    cu.space_line = 1.15
    tmp = bpy.data.objects.new(name + "_curve", cu)
    bpy.context.scene.collection.objects.link(tmp)
    dg = bpy.context.evaluated_depsgraph_get()
    dg.update()
    me = bpy.data.meshes.new_from_object(tmp.evaluated_get(dg))  # real mesh: glTF/USDZ have no text
    bpy.data.objects.remove(tmp)
    bpy.data.curves.remove(cu)
    me.materials.append(mat)
    ob = bpy.data.objects.new(name, me)
    ob.location, ob.rotation_euler = loc, (0, 0, rot_z)
    bpy.context.scene.collection.objects.link(ob)
    return ob


def key(ob, frame, loc=None, scale=None, rot=None):
    if loc is not None:
        ob.location = loc
        ob.keyframe_insert("location", frame=frame)
    if scale is not None:
        ob.scale = (scale,) * 3
        ob.keyframe_insert("scale", frame=frame)
    if rot is not None:
        ob.rotation_euler = rot
        ob.keyframe_insert("rotation_euler", frame=frame)


def spin(ob, turns):  # constant rotation about Z that loops seamlessly
    key(ob, 1, rot=(0, 0, 0))
    key(ob, LOOP + 1, rot=(0, 0, 2 * math.pi * turns))


# ---------- build ----------
def build():
    for coll in (bpy.data.objects, bpy.data.meshes, bpy.data.materials, bpy.data.curves,
                 bpy.data.actions, bpy.data.lights, bpy.data.cameras):
        for item in list(coll):
            coll.remove(item)
    sc = bpy.context.scene
    sc.render.fps, sc.frame_start, sc.frame_end = FPS, 1, LOOP
    edit = bpy.context.preferences.edit
    old_interp, edit.keyframe_new_interpolation_type = edit.keyframe_new_interpolation_type, 'LINEAR'
    rnd = random.Random(7)

    # emission strengths near 1: without bloom (there is none in AR) anything higher just clips to white
    MAT = {
        "Armor": material("Armor", "3A4239", rough=0.55, metal=0.85),       # olive gunmetal
        "Dark": material("Dark", "121518", rough=0.5, metal=0.7),
        "HUD": material("HUD", "000000", emit="E2E8EE", strength=0.9),       # white overlay lines
        "Red": material("Red", "000000", emit="FF3B30", strength=1.6),       # target markers
        "Cyan": material("Cyan", "000000", emit="7FD6FF", strength=1.0),
        "Link": material("Link", "000000", emit="7FD6FF", strength=0.3),
        "Amber": material("Amber", "000000", emit="FFBA78", strength=1.5),
        "Ink": material("Ink", "000000", emit="E2E8EE", strength=0.7),
        "Scan": material("Scan", "000000", emit="BFE9FF", strength=1.0, alpha=0.06),
        "PhoneFrame": material("PhoneFrame", "6B7480", rough=0.3, metal=1.0),
        "PhoneScreen": material("PhoneScreen", "000000", rough=0.05),
    }
    S = {k: bmesh.new() for k in ("Armor", "Dark", "HUD", "Red", "Cyan", "Link")}  # static geometry, one mesh per material
    A, D, H, R, C, L = (S[k] for k in ("Armor", "Dark", "HUD", "Red", "Cyan", "Link"))

    # --- platform ---
    cyl(A, SLAB_R, SLAB_TOP, T(0, 0, SLAB_TOP / 2), seg=14)
    cyl(D, DECK_R, DECK_TOP - SLAB_TOP, T(0, 0, (DECK_TOP + SLAB_TOP) / 2), seg=64)
    torus(H, DECK_R, 0.0008, T(0, 0, DECK_TOP), major=96)
    for rr in (0.075, 0.110, 0.145):                       # radar range rings
        torus(H, rr, 0.0004, T(0, 0, DECK_TOP + 0.0003), major=96, minor=4)
    for i in range(72):                                    # bearing ticks, longer every 30 degrees
        ln = 0.007 if i % 6 == 0 else 0.003
        box(H, ln, 0.0007, 0.0005, polar(math.radians(i * 5), 0.1555 - ln / 2, DECK_TOP + 0.0003))
    for k in range(5):                                     # bolts in the gaps between labels
        cyl(A, 0.004, 0.003, polar(hub_angle(k) - math.pi / N, 0.203, SLAB_TOP + 0.0015), seg=6)

    # front console with the name plate
    box(A, 0.17, 0.085, SLAB_TOP, T(0, -0.2425, SLAB_TOP / 2))
    box(D, 0.15, 0.03, 0.0012, T(0, -0.238, SLAB_TOP + 0.0006))
    for i in range(7):
        box(D, 0.002, 0.018, 0.002, T(0.045 + i * 0.005, -0.268, SLAB_TOP + 0.001))  # vent grille
    for i in range(3):
        sphere(R if i == 0 else C, (-0.072 + i * 0.009, -0.268, SLAB_TOP + 0.001), 0.0022, seg=8)  # status LEDs

    # --- central sensor tower ---
    cyl(A, 0.050, 0.022, T(0, 0, DECK_TOP + 0.011), seg=6)             # hex housing
    cyl(D, 0.030, 0.020, T(0, 0, 0.050))
    for i in range(24):                                                # heat-sink fins
        box(D, 0.024, 0.0015, 0.018, polar(i * math.pi / 12, 0.040, 0.050))
    cyl(A, 0.045, 0.006, T(0, 0, 0.063), seg=32)
    for i in range(6):                                                 # cage ribs around the core
        box(A, 0.004, 0.006, 0.059, polar(i * math.pi / 3 + math.pi / 6, 0.041, 0.0955))
    cyl(A, 0.045, 0.008, T(0, 0, 0.129), seg=32)
    torus(C, 0.0455, 0.0008, T(0, 0, 0.066))
    torus(C, 0.0455, 0.0008, T(0, 0, 0.125))
    for sx in (-1, 1):                                                 # whip antennas with red tips
        tube(D, (sx * 0.036, 0.012, TOWER_TOP), (sx * 0.046, 0.016, 0.205), r=0.0008)
        sphere(R, (sx * 0.046, 0.016, 0.205), 0.002, seg=8)
    for k in range(N):                                                 # equipment boxes on the deck
        w, d, h = rnd.uniform(0.012, 0.02), rnd.uniform(0.010, 0.016), rnd.uniform(0.004, 0.010)
        box(A if k % 2 else D, w, d, h, polar(hub_angle(k) - math.pi / N, 0.068, DECK_TOP + h / 2))

    # --- seven source pylons with floating, bracketed data clusters ---
    for k, (code, label) in enumerate(HUBS):
        a, c = hub_angle(k), hub_pos(k)
        cyl(A, 0.011, 0.030, polar(a, RING_R, DECK_TOP + 0.015), seg=6)
        cyl(D, 0.014, 0.004, polar(a, RING_R, DECK_TOP + 0.032), seg=6)
        emitter = polar(a, RING_R, DECK_TOP + 0.035).translation
        sphere(C, emitter, 0.005, seg=10)
        box(A, 0.085, 0.008, 0.004, polar(a, 0.0925, DECK_TOP + 0.002))          # conduit to the tower
        box(L, 0.085, 0.0015, 0.0006, polar(a, 0.0925, DECK_TOP + 0.0043))       # energy strip on it
        tube(L, emitter, c, r=0.0005)                                            # projection beam
        tube(L, c, CORE, r=0.0007)
        tube(L, c, hub_pos((k + 1) % N), r=0.0005)
        brackets(H, c, BR, 0.012)

        # HUD tag: leader line with an elbow, frame, red marker, data bars. Faces outward.
        m = polar(a, RING_R, c.z)
        x, z0, z1 = BR + 0.02, BR + 0.03, BR + 0.055
        path(H, [(BR, 0, BR), (x, 0, z0)], m=m)
        path(H, [(x, -0.028, z0), (x, 0.028, z0), (x, 0.028, z1), (x, -0.028, z1), (x, -0.028, z0)], m=m)
        zm = (z0 + z1) / 2
        torus(R, 0.006, 0.0009, m @ T(x, -0.018, zm) @ Matrix.Rotation(math.pi / 2, 4, 'Y'), major=20)
        sphere(R, m @ Vector((x, -0.018, zm)), 0.0022, seg=8)
        for i in range(3):
            path(H, [(x, -0.006, zm + 0.006 - i * 0.006), (x, -0.006 + rnd.uniform(0.012, 0.03), zm + 0.006 - i * 0.006)], m=m)

        # the data cluster itself, slowly rotating
        bm = bmesh.new()
        sphere(bm, Vector(), 0.009, seg=20)
        for _ in range(9):
            v = Vector((rnd.uniform(-1, 1), rnd.uniform(-1, 1), rnd.uniform(-0.8, 0.8))).normalized() * rnd.uniform(0.016, 0.028)
            sphere(bm, v, rnd.uniform(0.002, 0.0035), seg=8)
            tube(bm, Vector(), v, r=0.0004)
        spin(obj_from(bm, f"Hub_{code}", MAT["Cyan"], loc=c), 1 if k % 2 else -1)

        text(f"Label_{code}", f"{code}\n{label}", 0.0075, MAT["Ink"],
             (LABEL_R * math.cos(a), LABEL_R * math.sin(a), SLAB_TOP + 0.0006), a + math.pi / 2)

        # data pulse cluster -> core, four trips per loop, staggered per hub
        bm = bmesh.new()
        sphere(bm, Vector(), 0.003, seg=8)
        pulse = obj_from(bm, f"Pulse_{code}", MAT["Cyan"], loc=c)
        for trip in range(4):
            s = 2 + trip * 48 + k * 3
            key(pulse, s - 1, loc=c, scale=0)
            key(pulse, s, scale=1)
            key(pulse, s + 24, loc=CORE, scale=0)

    text("Title", "CYBERSENSORN", 0.015, MAT["Ink"], (0, -0.238, SLAB_TOP + 0.0018), 0, align_y='CENTER')

    # --- the phone from the intro: target acquired ---
    pm = T(*PHONE) @ RZ(PHONE_A + math.pi / 2)
    bm = bmesh.new()
    box(bm, 0.06, 0.028, 0.003, pm)
    obj_from(bm, "Phone", MAT["PhoneFrame"])
    bm = bmesh.new()
    box(bm, 0.057, 0.025, 0.0004, pm @ T(0, 0, 0.0015))
    obj_from(bm, "PhoneScreen", MAT["PhoneScreen"])
    for sx in (-1, 1):
        for sy in (-1, 1):
            cx, cy = sx * 0.034, sy * 0.018
            path(H, [(cx - sx * 0.008, cy, 0), (cx, cy, 0), (cx, cy - sy * 0.008, 0)], m=pm)
    sphere(R, pm @ Vector((0.034, 0.018, 0)), 0.002, seg=8)
    tube(L, PHONE, hub_pos(0), r=0.0005)

    for name, bm in S.items():
        obj_from(bm, "Static_" + name, MAT[name])

    # --- animated parts ---
    bm = bmesh.new()
    sphere(bm, Vector(), 0.022, seg=32)
    core = obj_from(bm, "Core", MAT["Cyan"], loc=CORE)
    for f, s in ((1, 1), (48, 1.08), (96, 1), (144, 1.08), (160, 1), (166, 1.45), (178, 1), (LOOP + 1, 1)):
        key(core, f, scale=s)  # breathes, then flares when the signal lands
    for i, (rr, tilt) in enumerate(((0.029, 0.5), (0.035, -0.9))):
        bm = bmesh.new()
        torus(bm, rr, 0.0009)
        ring = obj_from(bm, f"CoreRing{i + 1}", MAT["Cyan"], loc=CORE)
        turn = 2 * math.pi * (1 if i == 0 else -1)
        for f, t in ((1, 0), (LOOP + 1, 1)):
            key(ring, f, rot=(tilt + turn * t, tilt * 0.6, turn * t) if i == 0 else (tilt, turn * t, tilt * 0.4))

    # rotating radar head on the tower, and its sweep across the deck
    bm = bmesh.new()
    cyl(bm, 0.005, 0.03, T(0, 0, 0.015), seg=8)
    tilt = Matrix.Rotation(math.radians(-15), 4, 'X')
    box(bm, 0.075, 0.005, 0.032, T(0, 0, 0.046) @ tilt)
    for i in range(5):
        box(bm, 0.002, 0.003, 0.028, T(0, 0, 0.046) @ tilt @ T(-0.028 + i * 0.014, -0.004, 0))
    box(bm, 0.022, 0.014, 0.012, T(0, 0.009, 0.040))
    spin(obj_from(bm, "Radar", MAT["Armor"], loc=(0, 0, TOWER_TOP)), 2)
    bm = bmesh.new()
    arc = [bm.verts.new((DECK_R * 0.98 * math.cos(math.radians(d)), DECK_R * 0.98 * math.sin(math.radians(d)), 0))
           for d in range(245, 296, 5)]  # 50 degree fan, centred on the radar's facing direction (-Y)
    centre = bm.verts.new((0, 0, 0))
    for p, q in zip(arc, arc[1:]):
        bm.faces.new((centre, p, q))
    spin(obj_from(bm, "Sweep", MAT["Scan"], loc=(0, 0, DECK_TOP + 0.0008)), 2)

    # two collector drones orbiting the tower, each with a scan cone
    orbit = bpy.data.objects.new("Drones", None)
    sc.collection.objects.link(orbit)
    spin(orbit, 1)
    body, rotors, leds, cones = bmesh.new(), bmesh.new(), bmesh.new(), bmesh.new()
    for sx, z in ((1, 0.245), (-1, 0.225)):
        m = T(sx * 0.17, 0, z)
        box(body, 0.014, 0.022, 0.008, m)
        sphere(body, m @ Vector((0, 0, -0.006)), 0.004, seg=10)  # camera gimbal
        for d in (45, 135):
            box(body, 0.052, 0.003, 0.002, m @ RZ(math.radians(d)))
        for d in (45, 135, 225, 315):
            p = m @ RZ(math.radians(d)) @ T(0.026, 0, 0.003)
            cyl(body, 0.002, 0.004, p, seg=6)
            torus(rotors, 0.012, 0.0005, p @ T(0, 0, 0.002), major=20, minor=4)
        sphere(leds, m @ Vector((0, sx * 0.012, 0)), 0.0018, seg=8)
        depth = z - DECK_TOP - 0.01
        cyl(cones, 0.028, depth, m @ T(0, 0, -0.006 - depth / 2), seg=32, r2=0.001, caps=False)
    for name, bm, mat in (("DroneBodies", body, "Dark"), ("DroneRotors", rotors, "HUD"),
                          ("DroneLeds", leds, "Red"), ("DroneCones", cones, "Scan")):
        obj_from(bm, name, MAT[mat], parent=orbit)

    # amber signal: phone -> N-01 -> ... -> N-07 -> core
    bm = bmesh.new()
    sphere(bm, Vector(), 0.006, seg=16)
    sig = obj_from(bm, "Signal", MAT["Amber"])
    key(sig, 1, loc=PHONE + Vector((0, 0, 0.004)), scale=0)
    key(sig, 6, scale=1)
    for k in range(N):
        key(sig, 25 + 18 * k, loc=hub_pos(k))
    key(sig, 150, scale=1)
    key(sig, 160, loc=CORE)
    key(sig, 162, scale=0)
    key(sig, LOOP + 1, loc=CORE, scale=0)

    edit.keyframe_new_interpolation_type = old_interp
    sc.frame_set(60)


def export():
    bpy.ops.wm.save_as_mainfile(filepath=OUT + r"\cybersensorn.blend")
    bpy.ops.export_scene.gltf(filepath=OUT + r"\cybersensorn.glb", export_format='GLB',
                              export_animations=True, export_animation_mode='SCENE')
    bpy.ops.wm.usd_export(filepath=OUT + r"\cybersensorn.usdz", export_animation=True)


build()
export()
meshes = [o for o in bpy.data.objects if o.type == 'MESH']
for o in meshes:
    o.data.calc_loop_triangles()
print("objects:", len(bpy.data.objects), "tris:", sum(len(o.data.loop_triangles) for o in meshes))
