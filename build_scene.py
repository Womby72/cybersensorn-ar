# Builds the Cybersensorn tabletop model and exports cybersensorn.glb / .usdz / .blend.
# Run inside Blender (via the MCP add-on) or headless:
#   blender.exe --background --python build_scene.py
# Units are metres: the model is ~42 cm across so it sits on a table in AR.
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
TOP = 0.02            # plinth top
PLINTH_R = 0.21
RING_R = 0.14         # hub ring radius
LABEL_R = 0.150
CORE = Vector((0, 0, 0.135))


def hub_angle(k):  # same as HUB_ANGLE: N-01 on the left, then clockwise
    return math.radians(180 - k * 360 / len(HUBS))


def hub_pos(k):
    a = hub_angle(k)
    return Vector((RING_R * math.cos(a), RING_R * math.sin(a), 0.10 + 0.015 * math.sin(k * 2.4)))


PHONE_A = (hub_angle(0) + hub_angle(len(HUBS) - 1) + 2 * math.pi) / 2  # between N-01 and N-07, front-left
PHONE = Vector((0.172 * math.cos(PHONE_A), 0.172 * math.sin(PHONE_A), TOP + 0.0015))


# ---------- materials ----------
def lin(hex_):  # sRGB hex -> linear RGBA
    def c(v):
        v /= 255
        return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4
    return (*[c(int(hex_[i:i + 2], 16)) for i in (0, 2, 4)], 1)


def material(name, base, emit=None, strength=0.0, rough=0.5, metal=0.0):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    p = m.node_tree.nodes["Principled BSDF"]
    p.inputs["Base Color"].default_value = lin(base)
    p.inputs["Roughness"].default_value = rough
    p.inputs["Metallic"].default_value = metal
    if emit:
        p.inputs["Emission Color"].default_value = lin(emit)
        p.inputs["Emission Strength"].default_value = strength
    return m


# ---------- geometry helpers (bmesh, no operators, so it also runs headless) ----------
def sphere(bm, c, r, seg=16):
    bmesh.ops.create_uvsphere(bm, u_segments=seg, v_segments=seg // 2, radius=r, matrix=Matrix.Translation(c))


def tube(bm, a, b, r=0.0008, seg=6):
    d = b - a
    rot = d.to_track_quat('Z', 'Y').to_matrix().to_4x4()
    bmesh.ops.create_cone(bm, cap_ends=False, segments=seg, radius1=r, radius2=r, depth=d.length,
                          matrix=Matrix.Translation((a + b) / 2) @ rot)


def torus(bm, R, r, major=64, minor=8):
    vs = [[bm.verts.new(((R + r * math.cos(j * 2 * math.pi / minor)) * math.cos(i * 2 * math.pi / major),
                         (R + r * math.cos(j * 2 * math.pi / minor)) * math.sin(i * 2 * math.pi / major),
                         r * math.sin(j * 2 * math.pi / minor)))
           for j in range(minor)] for i in range(major)]
    for i in range(major):
        for j in range(minor):
            bm.faces.new((vs[i][j], vs[(i + 1) % major][j], vs[(i + 1) % major][(j + 1) % minor], vs[i][(j + 1) % minor]))


def obj_from(bm, name, mat, loc=(0, 0, 0), smooth=True):
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    if smooth:
        me.polygons.foreach_set("use_smooth", [True] * len(me.polygons))
    me.materials.append(mat)
    ob = bpy.data.objects.new(name, me)
    ob.location = loc
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

    M_PLINTH = material("Plinth", "0B0E13", rough=0.35, metal=0.7)
    # strengths near 1: without bloom (there is none in AR) anything higher just clips to white
    M_CYAN = material("Cyan", "000000", emit="7FD6FF", strength=1.0)
    M_LINK = material("Link", "000000", emit="7FD6FF", strength=0.3)
    M_AMBER = material("Amber", "000000", emit="FFBA78", strength=1.5)
    M_INK = material("Ink", "000000", emit="E2E8EE", strength=0.7)
    M_PHONE = material("PhoneFrame", "6B7480", rough=0.3, metal=1.0)
    M_SCREEN = material("PhoneScreen", "000000", rough=0.05)

    # plinth + glowing rim
    bm = bmesh.new()
    bmesh.ops.create_cone(bm, cap_ends=True, segments=96, radius1=PLINTH_R, radius2=PLINTH_R, depth=TOP,
                          matrix=Matrix.Translation((0, 0, TOP / 2)))
    plinth = obj_from(bm, "Plinth", M_PLINTH)
    plinth.data.set_sharp_from_angle(angle=math.radians(40))
    bm = bmesh.new()
    torus(bm, PLINTH_R - 0.004, 0.0012, major=96)
    obj_from(bm, "Rim", M_CYAN, loc=(0, 0, TOP))

    # core + two tumbling rings
    bm = bmesh.new()
    sphere(bm, Vector(), 0.026, seg=32)
    core = obj_from(bm, "Core", M_CYAN, loc=CORE)
    for f, s in ((1, 1), (48, 1.08), (96, 1), (144, 1.08), (160, 1), (166, 1.4), (178, 1), (LOOP + 1, 1)):
        key(core, f, scale=s)  # breathes, then flares when the signal lands
    for i, (R, tilt) in enumerate(((0.040, 0.5), (0.048, -0.9))):
        bm = bmesh.new()
        torus(bm, R, 0.0011)
        ring = obj_from(bm, f"CoreRing{i + 1}", M_CYAN, loc=CORE)
        turn = 2 * math.pi * (1 if i == 0 else -1)
        for f, t in ((1, 0), (LOOP + 1, 1)):
            key(ring, f, rot=(tilt + turn * t, tilt * 0.6, turn * t) if i == 0 else (tilt, turn * t, tilt * 0.4))

    # links: hub-core, hub-neighbour, hub-label drop line
    n = len(HUBS)
    bm = bmesh.new()
    for k in range(n):
        p = hub_pos(k)
        tube(bm, p, CORE)
        tube(bm, p, hub_pos((k + 1) % n))
        a = hub_angle(k)
        tube(bm, p, Vector((LABEL_R * math.cos(a), LABEL_R * math.sin(a), TOP)), r=0.0005)
    tube(bm, PHONE, hub_pos(0), r=0.0005)
    obj_from(bm, "Links", M_LINK)

    # hubs: node + small cluster, slowly rotating; labels flat on the plinth, readable from outside
    rnd = random.Random(7)
    for k, (code, label) in enumerate(HUBS):
        bm = bmesh.new()
        sphere(bm, Vector(), 0.011, seg=20)
        for _ in range(8):
            v = Vector((rnd.uniform(-1, 1), rnd.uniform(-1, 1), rnd.uniform(-0.7, 0.7))).normalized() * rnd.uniform(0.022, 0.04)
            sphere(bm, v, rnd.uniform(0.0025, 0.0045), seg=10)
            tube(bm, Vector(), v, r=0.0005)
        hub = obj_from(bm, f"Hub_{code}", M_CYAN, loc=hub_pos(k))
        turn = 2 * math.pi * (1 if k % 2 else -1)
        key(hub, 1, rot=(0, 0, 0))
        key(hub, LOOP + 1, rot=(0, 0, turn))

        a = hub_angle(k)
        text(f"Label_{code}", f"{code}\n{label}", 0.0075, M_INK,
             (LABEL_R * math.cos(a), LABEL_R * math.sin(a), TOP + 0.0006), a + math.pi / 2)

        # data pulse hub -> core, four trips per loop, staggered per hub
        bm = bmesh.new()
        sphere(bm, Vector(), 0.003, seg=10)
        pulse = obj_from(bm, f"Pulse_{code}", M_CYAN, loc=hub_pos(k))
        for trip in range(4):
            s = 2 + trip * 48 + k * 3
            key(pulse, s - 1, loc=hub_pos(k), scale=0)
            key(pulse, s, scale=1)
            key(pulse, s + 24, loc=CORE, scale=0)

    text("Title", "CYBERSENSORN", 0.017, M_INK, (0, -0.012, TOP + 0.0006), 0, align_y='CENTER')

    # the phone from the intro, where the signal starts
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1, matrix=Matrix.Diagonal((0.06, 0.028, 0.003, 1)))
    phone = obj_from(bm, "Phone", M_PHONE, loc=PHONE, smooth=False)
    phone.rotation_euler = (0, 0, PHONE_A)
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1, matrix=Matrix.Diagonal((0.057, 0.025, 0.0004, 1)))
    screen = obj_from(bm, "PhoneScreen", M_SCREEN, loc=PHONE + Vector((0, 0, 0.0015)), smooth=False)
    screen.rotation_euler = (0, 0, PHONE_A)

    # amber signal: phone -> N-01 -> ... -> N-07 -> core
    bm = bmesh.new()
    sphere(bm, Vector(), 0.006, seg=16)
    sig = obj_from(bm, "Signal", M_AMBER)
    key(sig, 1, loc=PHONE + Vector((0, 0, 0.004)), scale=0)
    key(sig, 6, scale=1)
    for k in range(n):
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
print("objects:", len(bpy.data.objects), "tris:", sum(len(o.data.loop_triangles) or o.data.calc_loop_triangles() or len(o.data.loop_triangles) for o in bpy.data.objects))
