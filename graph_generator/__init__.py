bl_info = {
    "name": "Graph Generator",
    "author": "The French Monkey",
    "version": (1, 2, 2),
    "blender": (4, 4, 0),
    "location": "Graph Editor > Sidebar > Graph Generator",
    "description": "Generate graph between saved keyframes.",
    "category": "Animation",
    "license": "GPL-3.0-or-later",
}

import bpy
import random
import math
import re
import json
from bpy_extras import anim_utils

EPS = 1e-6

# --------------------------------
# Presets
# --------------------------------

EASING_PRESETS = {
    # --- Basic Easing ---
    "linear": [0.0, 1.0],
    "ease": [0.25, 0.1, 0.25, 1.0],
    "ease-in": [0.42, 0.0, 1.0, 1.0],
    "ease-out": [0.0, 0.0, 0.58, 1.0],
    "ease-in-out": [0.42, 0.0, 0.58, 1.0],

    # --- Physically Inspired ---
    "ease-out-bounce": [0.34, 1.56, 0.64, 1.0],
    "ease-out-elastic": [0.45, 1.6, 0.55, -0.6],
    "ease-out-back": [0.22, 1.55, 0.36, 1.0],
    "ease-in-back": [0.36, 0.0, 0.66, -0.56],
    "ease-in-out-back": [0.68, -0.6, 0.32, 1.6],
    "ease-anticipate": [0.5, -0.4, 0.2, 1.4],
    "ease-overshoot": [0.2, 1.3, 0.4, 1.0],

    # --- Cinematic Motion ---
    "ease-soft": [0.35, 0.0, 0.65, 1.0],
    "ease-snappy": [0.4, 0.0, 0.2, 1.0],
    "ease-firm": [0.7, 0.0, 0.3, 1.0],
    "ease-punch": [0.15, 1.4, 0.45, 1.0],
    "ease-springy": [0.2, 1.3, 0.6, -0.4],

    # --- Stylized Effects ---
    "ease-pop": [0.45, 1.7, 0.55, -0.5],
    "ease-snap": [0.65, -0.4, 0.35, 1.4],
    "ease-pulse": [0.4, 0.0, 0.6, 1.0],
    "ease-wobble": [0.25, 1.5, 0.75, -0.5],
    "ease-rubber": [0.4, 1.8, 0.6, -0.8],

    # --- Exaggerated Animation ---
    "ease-cartoon": [0.7, -0.4, 0.3, 1.4],
    "ease-pop-in": [0.2, 1.0, 0.4, 1.0],
    "ease-squash": [0.5, -0.5, 0.5, 1.5],
    "ease-wave": [0.3, 1.2, 0.7, -0.2],
    "ease-jelly": [0.3, 1.5, 0.6, -0.6],

    # --- Organic ---
    "ease-soft-bounce": [0.5, 1.3, 0.3, 1.0],
    "ease-organic": [0.25, 0.8, 0.55, 0.3],
    "ease-smooth-pop": [0.3, 1.4, 0.6, 0.8],
    "ease-damped": [0.6, -0.2, 0.3, 1.2],

    # --- Natural Motion ---
    "ease-slow-rise": [0.3, 0.6, 0.5, 1.0],
    "ease-falloff": [0.5, 1.2, 0.7, 1.0],
    "ease-weight": [0.5, 1.3, 0.8, 1.0],
    "ease-pop-bounce": [0.35, 1.7, 0.45, -0.4],
    "ease-pulse-smooth": [0.35, 0.0, 0.65, 1.0],

    # --- Experimental ---
    "ease-glitch": [0.1, 1.2, 0.9, -0.2],
    "ease-spike": [0.25, 1.8, 0.55, -0.7],
    "ease-breath": [0.4, 0.0, 0.6, 1.0],
    "ease-surge": [0.3, 1.0, 0.4, 1.0],
    "ease-microbounce": [0.2, 1.4, 0.6, -0.2],
}

# --------------------------------
# Utilities
# --------------------------------

def extract_bone_from_path(data_path):
    if not data_path or 'pose.bones[' not in data_path:
        return None
    try:
        start = data_path.index('pose.bones["') + 12
        end = data_path.index('"]', start)
        return data_path[start:end]
    except (ValueError, IndexError):
        return None

def is_ascii(s):
    return isinstance(s, str) and all(32 <= ord(c) <= 126 for c in s)

def clean_saved_dict(raw):
    if not isinstance(raw, dict):
        return {}

    clean = {}
    for gid, pts in raw.items():
        if not isinstance(gid, str) or not gid.isdigit():
            continue
        if not isinstance(pts, list) or len(pts) == 0:
            continue

        ok = True
        fixed_pts = []

        for p in pts:
            if not isinstance(p, list) or len(p) < 4:
                ok = False
                break

            dp = p[0]
            ai = p[1]
            bone = p[5] if len(p) >= 6 else None

            if not is_ascii(dp):
                ok = False
                break

            if not isinstance(ai, int):
                ok = False
                break

            if bone not in (None, "", "OBJECT"):
                if not is_ascii(bone):
                    ok = False
                    break

            fixed_pts.append(p)

        if ok:
            clean[gid] = fixed_pts

    return clean

def sanitize_graph_selector(s, context):
    items = get_dynamic_locations(s, context)
    valid = [i[0] for i in items]

    if not valid:
        s.graphgen_location_filter = "0"
        return

    if s.graphgen_location_filter not in valid:
        s.graphgen_location_filter = valid[0]

def redraw_graph_editor():
    for window in bpy.context.window_manager.windows:
        for area in window.screen.areas:
            if area.type == 'GRAPH_EDITOR':
                area.tag_redraw()

def load_saved_points_dict(s):
    try:
        raw = json.loads(s.saved_points_json)
    except Exception:
        s.saved_points_json = "{}"
        return {}

    cleaned = clean_saved_dict(raw)

    if cleaned != raw:
        s.saved_points_json = json.dumps(cleaned)

    return cleaned

def save_saved_points_dict(s, d):
    s.saved_points_json = json.dumps(d)

def _get_config_for_loc(settings, loc_id):
    for c in settings.graph_configs:
        if c.loc_id == loc_id:
            return c
    return None

def _ensure_config_for_loc(settings, loc_id):
    cfg = _get_config_for_loc(settings, loc_id)
    if cfg:
        return cfg
    cfg = settings.graph_configs.add()
    cfg.loc_id = loc_id
    return cfg

def clamp(v, a, b):
    return a if v < a else b if v > b else v

def clamp01(v):
    return clamp(v, 0.0, 1.0)

def parse_css_easing(css_input):
    if isinstance(css_input, list):
        return css_input
    if not isinstance(css_input, str):
        return None
    css = css_input.strip().lower()
    if css.startswith("cubic-bezier("):
        m = re.match(r"cubic-bezier\(([-+]?\d*\.?\d+),\s*([-+]?\d*\.?\d+),\s*([-+]?\d*\.?\d+),\s*([-+]?\d*\.?\d+)\)", css)
        if m:
            return [float(m.group(i)) for i in range(1, 5)]
    if css.startswith("linear("):
        nums = [float(n) for n in re.findall(r"[-+]?\d*\.?\d+", css)]
        return nums if len(nums) >= 2 else None
    return EASING_PRESETS.get(css, None)

def cubic_bezier_point(t, x1, y1, x2, y2):
    u = 1.0 - t
    return 3 * (u ** 2) * t * y1 + 3 * u * (t ** 2) * y2 + (t ** 3)

def get_armature_from_context(context):
    obj = context.active_object
    
    if obj and obj.type == 'ARMATURE':
        return obj
    
    if obj and obj.parent and obj.parent.type == 'ARMATURE':
        return obj.parent
    
    return None

def get_bone_enum_items(self, context):
    obj = context.active_object
    
    if not obj or not obj.animation_data or not obj.animation_data.action:
        return [('OBJECT', 'Object/Bones', 'Show all graphs (object transforms and all bones)')]
    
    arm = get_armature_from_context(context)
    
    if arm is None or not hasattr(arm, "pose") or not arm.pose.bones:
        return [('OBJECT', 'Object/Bones', 'Show all graphs (object transforms and all bones)')]
    
    items = [('OBJECT', 'Object/Bones', 'Show all graphs (object transforms and all bones)')]
    
    action = obj.animation_data.action
    animated_bones = set()
    
    for fc in action.fcurves:
        bone_name = extract_bone_from_path(fc.data_path)
        if bone_name and is_ascii(bone_name):
            animated_bones.add(bone_name)
    
    if action.is_action_layered and action.layers:
        for layer in action.layers:
            for strip in layer.strips:
                for slot in action.slots:
                    cbag = strip.channelbag(slot, ensure=False)
                    if not cbag:
                        continue
                    for fc in cbag.fcurves:
                        bone_name = extract_bone_from_path(fc.data_path)
                        if bone_name and is_ascii(bone_name):
                            animated_bones.add(bone_name)
    
    for bone_name in sorted(animated_bones):
        if bone_name in arm.pose.bones:
            items.append((bone_name, bone_name, f"Show only graphs for bone: {bone_name}"))
    
    return items

def get_animated_bone_count(context):
    obj = context.active_object
    if not obj or not obj.animation_data or not obj.animation_data.action:
        return 0

    arm = get_armature_from_context(context)
    if arm is None or not arm.pose.bones:
        return 0

    action = obj.animation_data.action
    bones = set()

    for fc in action.fcurves:
        bone = extract_bone_from_path(fc.data_path)
        if bone and is_ascii(bone):
            bones.add(bone)

    if action.is_action_layered and action.layers:
        for layer in action.layers:
            for strip in layer.strips:
                for slot in action.slots:
                    cbag = strip.channelbag(slot, ensure=False)
                    if not cbag:
                        continue
                    for fc in cbag.fcurves:
                        bone = extract_bone_from_path(fc.data_path)
                        if bone and is_ascii(bone):
                            bones.add(bone)

    return len(bones)

# --------------------------------
# Config storage
# --------------------------------

def _per_graph_auto_update(self, context): 
    s = context.scene.graphgen_settings
    if getattr(s, "graphgen_auto_update", False): 
        generate_graph(context)

class GraphGenConfig(bpy.types.PropertyGroup):
    loc_id: bpy.props.IntProperty(name="Graph ID", description="Internal identifier for this saved graph", default=-1)

    preset: bpy.props.EnumProperty(name="Graph Source", description="Select the generator algorithm used to create motion", 
        items=[
            ('Random','Random',"Random noisy motion"),
            ('Spring','Spring',"Spring-like oscillation"),
            ('Bounce','Bounce',"Bouncing motion"),
            ('Plateau','Plateau',"Flat plateau steps"),
            ('Pulse','Pulse',"Pulsing motion"),
            ('Peak','Peak',"Evenly spaced peaks"), 
            ('CustomCSS','Custom CSS',"CSS-style easing input"),
            ('Preset','Preset',"Studio easing preset")
        ],
        default='Random', update=_per_graph_auto_update)

    strength: bpy.props.FloatProperty(name="Strength", description="Overall amplitude of the generator", default=0.0, min=0, max=10.0, subtype='FACTOR', update=_per_graph_auto_update)
    resolution: bpy.props.IntProperty(name="Resolution", description="Number of keyframes inserted between anchors", default=20, min=2, max=256, subtype='FACTOR', update=_per_graph_auto_update)
    smooth_inout: bpy.props.BoolProperty(name="Smooth In/Out", description="Ease in/out at segment boundaries", default=False, update=_per_graph_auto_update)
    smooth_amount: bpy.props.FloatProperty(name="Smooth Amount", description="Intensity of in/out smoothing", default=0.1, min=0.0, max=1.0, subtype='FACTOR', update=_per_graph_auto_update)
    bounce_count: bpy.props.IntProperty(name="Bounces", description="Number of spring oscillations", default=3, min=1, max=50, subtype='FACTOR', update=_per_graph_auto_update)
    spring_invert_horiz: bpy.props.BoolProperty(name="Invert Horizontally", description="Flip the spring horizontally", default=False, update=_per_graph_auto_update)
    seed: bpy.props.IntProperty(name="Seed", description="Random seed for noise", default=0, min=0, max=1000, subtype='FACTOR', update=_per_graph_auto_update)
    bounce_amount: bpy.props.IntProperty(name="Bounce Amount", description="Amount of bouncing waves", default=5, min=1, max=50, subtype='FACTOR', update=_per_graph_auto_update)
    bounce_invert: bpy.props.BoolProperty(name="Invert Horizontally", description="Flip bounce motion horizontally", default=False, update=_per_graph_auto_update)
    plateau_amount: bpy.props.IntProperty(name="Plateau Amount", description="Number of plateau steps", default=6, min=1, max=50, subtype='FACTOR', update=_per_graph_auto_update)
    pulse_amount: bpy.props.IntProperty(name="Pulse Amount", description="Number of pulses across the segment", default=2, min=1, max=20, subtype='FACTOR', update=_per_graph_auto_update)
    css_string: bpy.props.StringProperty(name="Custom CSS", description='CSS easing like "linear(0,1)" or "cubic-bezier(...)"', default="linear(0, 1)", update=_per_graph_auto_update)
    css_invert_horiz: bpy.props.BoolProperty(name="Invert Horizontally", description="Flip CSS easing horizontally", default=False, update=_per_graph_auto_update)
    preset_name: bpy.props.EnumProperty(name="Preset", description="Easing preset", 
        items=[(k, k.replace("-", " ").title(), f"Easing preset: {k}") for k in EASING_PRESETS.keys()], 
        default='linear', update=_per_graph_auto_update)
    preset_repeat: bpy.props.IntProperty(name="Repeat", description="Repeat preset across the graph", default=1, min=1, max=50, subtype='FACTOR', update=_per_graph_auto_update)
    preset_continuous: bpy.props.BoolProperty(name="Continuous", description="Repeat preset without edge easing", default=False, update=_per_graph_auto_update)
    peaks_count: bpy.props.IntProperty(name="Peaks", description="Number of evenly spaced peaks", default=2, min=1, max=50, subtype='FACTOR', update=_per_graph_auto_update)
    peaks_randomizer: bpy.props.FloatProperty(name="Randomizer", description="Random variation on peak height (0 = none, 1 = fully random)", default=0.0, min=0.0, max=1.0, subtype='FACTOR', update=_per_graph_auto_update)


class GeneratedFramesItem(bpy.types.PropertyGroup):
    frame: bpy.props.FloatProperty(name="Frame", description="Generated frame number")
    loc_id: bpy.props.IntProperty(name="Graph ID", description="Identifier of related graph")

class GraphGenSettings(bpy.types.PropertyGroup):

    graphgen_auto_update: bpy.props.BoolProperty(name="Live Update", description="Regenerate automatically when settings change", default=True)
    graphgen_bone_filter: bpy.props.EnumProperty(name="Object", description="Choose which animated bone to work with", items=get_bone_enum_items)
    graphgen_location_filter: bpy.props.EnumProperty(name="Graph Selector", description="Select a saved graph to view or edit", items=lambda self, context: get_dynamic_locations(self, context), update=lambda self, context: None)
    saved_points_json: bpy.props.StringProperty(name="Saved Keyframes", description="Serialized saved keyframe anchors", default="{}")
    graph_configs: bpy.props.CollectionProperty(name="Graph Configs", description="Settings per saved graph", type=GraphGenConfig)
    generated_frames: bpy.props.CollectionProperty(name="Generated Frames", description="Internally generated keyframes", type=GeneratedFramesItem)
    save_highlighted_only: bpy.props.BoolProperty(name="Save Highlighted Graphs Only", description="Save only highlighted curves in the Graph Editor", default=False)

# --------------------------------
# Evaluators
# --------------------------------

def edge_envelope(t, sm):
    if sm <= 0.0:
        return 1.0
    e_in = clamp(t / sm, 0.0, 1.0)
    e_out = clamp((1.0 - t) / sm, 0.0, 1.0)
    return min(e_in, e_out)

def center_envelope(t):
    return 4.0 * t * (1.0 - t)

def eval_random_offset(cfg, t):
    random.seed(cfg.seed + int(t * 10000))
    rnd = (random.random() - 0.5) * 2.0
    return rnd

def eval_spring_offset(cfg, t):
    tt = 1.0 - t if cfg.spring_invert_horiz else t
    return math.sin(tt * cfg.bounce_count * math.pi) * math.exp(-2.5 * tt) * center_envelope(tt)

def eval_bounce_offset(cfg, t, y0=0.0, y1=1.0):
    going_up = (y1 > y0)
    tt = 1.0 - t if cfg.bounce_invert else t
    y = abs(math.sin(tt * cfg.bounce_amount * math.pi)) * ((1.0 - tt) ** 2)
    if not going_up:
        y = -y
    return y

def eval_plateau_offset(cfg, t):
    steps = max(1, cfg.plateau_amount)
    u = abs(2.0 * t - 1.0)
    k = min(int(u * steps + 1e-9), steps)
    plateau = 1.0 - (k / steps)
    return plateau

def eval_pulse_offset(cfg, t):
    pulses = max(1, cfg.pulse_amount)
    phase = (t * pulses) % 1.0

    def g(x, mu, sigma, amp):
        return amp * math.exp(-0.5 * ((x - mu) / sigma) ** 2)

    q = -g(phase, 0.085, 0.006, 0.4)
    r = g(phase, 0.100, 0.010, 1.2)
    s = -g(phase, 0.118, 0.008, 0.6)
    t_wave = g(phase, 0.200, 0.030, 0.25)

    return q + r + s + t_wave

def eval_custom_css_offset(cfg, t):
    vals = parse_css_easing(cfg.css_string)
    if not vals:
        return 0.0
    tt = 1.0 - t if cfg.css_invert_horiz else t
    if len(vals) == 4:
        y = clamp01(cubic_bezier_point(tt, *vals))
    elif len(vals) >= 2:
        i = int(math.floor(tt * (len(vals) - 1)))
        f = tt * (len(vals) - 1) - i
        y = clamp01((1 - f) * vals[i] + f * vals[min(i + 1, len(vals) - 1)])
    else:
        y = tt
    return (y - t) * center_envelope(t)

def eval_preset_offset(cfg, t):
    vals = EASING_PRESETS.get(cfg.preset_name)
    if not vals:
        return 0.0

    repeat = max(1, getattr(cfg, "preset_repeat", 1))
    continuous = getattr(cfg, "preset_continuous", False)

    tt = (t * repeat) % 1.0

    if len(vals) == 4:
        y = clamp01(cubic_bezier_point(tt, *vals))
    else:
        n = len(vals) - 1
        idx = tt * n
        i0 = int(math.floor(idx))
        i1 = min(i0 + 1, n)
        f = idx - i0
        y = clamp01((1 - f) * vals[i0] + f * vals[i1])

    if continuous:
        return y

    return (y - t)

def eval_peak_offset(cfg, t):
    peaks = max(1, cfg.peaks_count)
    peak_index = int(t * peaks)

    local_t = (t * peaks) - peak_index

    if cfg.peaks_randomizer > 0.0:
        min_factor = 1.0 - cfg.peaks_randomizer
        height = min_factor + cfg.peaks_randomizer * random.random()
    else:
        height = 1.0

    value = 1.0 - abs(local_t - 0.5) * 2.0

    return value * height

# --------------------------------
# Dynamic Graph Selector
# --------------------------------

def label_for_curve(dp, ai):
    dp_lower = dp.lower()
    if "location" in dp_lower:
        return f"Location {'XYZ'[ai]}"
    if "rotation" in dp_lower:
        return f"Rotation {'XYZW'[ai]}"
    if "scale" in dp_lower:
        return f"Scale {'XYZ'[ai]}"
    return f"{dp}[{ai}]"

def get_dynamic_locations(self, context):
    s = context.scene.graphgen_settings
    d = load_saved_points_dict(s)
    bone_filter = s.graphgen_bone_filter

    if not isinstance(d, dict) or not d:
        return [('0', 'No Saved Graphs', '')]

    items = []
    seen = set()
    
    debug_info = []

    for gid, pts in d.items():
        if not pts:
            debug_info.append(f"GID {gid}: empty points")
            continue

        if not isinstance(gid, str) or not gid.isdigit():
            debug_info.append(f"GID {gid}: invalid ID format")
            continue

        dp = pts[0][0]
        ai = pts[0][1]

        if not isinstance(dp, str) or not is_ascii(dp):
            debug_info.append(f"GID {gid}: non-ASCII data path")
            continue
        
        if not isinstance(ai, int):
            debug_info.append(f"GID {gid}: invalid array index")
            continue

        bone_name = extract_bone_from_path(dp)
        if bone_name is None:
            bone_name = "OBJECT"
        
        if not is_ascii(bone_name):
            debug_info.append(f"GID {gid}: non-ASCII bone name")
            bone_name = "OBJECT"

        if bone_filter != "OBJECT":
            if bone_name != bone_filter:
                debug_info.append(f"GID {gid}: bone {bone_name} != filter {bone_filter}")
                continue

        sig = (dp, ai)
        if sig in seen:
            debug_info.append(f"GID {gid}: duplicate signature")
            continue
        seen.add(sig)

        label = label_for_curve(dp, ai)
        if bone_name != "OBJECT":
            label = f"{bone_name} - {label}"
        
        if not is_ascii(label):
            debug_info.append(f"GID {gid}: non-ASCII label")
            continue
        
        if not is_ascii(gid):
            debug_info.append(f"GID {gid}: non-ASCII gid")
            continue

        debug_info.append(f"GID {gid}: ADDED - {label}")
        items.append((gid, label, ""))

    if debug_info:
        print("\n=== Graph Selector Debug ===")
        print(f"Bone filter: {bone_filter}")
        print(f"Total saved graphs: {len(d)}")
        print(f"Visible items: {len(items)}")
        for line in debug_info:
            print(line)
        print("===========================\n")

    if not items:
        if bone_filter != "OBJECT":
            return [('0', 'No Graphs for Selected Bone', 'Try selecting a different bone or save new keyframes')]
        else:
            return [('0', 'No Saved Graphs', 'Select keyframes and click Save Keyframes')]

    return items

# --------------------------------
# Graph Generation Core
# --------------------------------

def get_fcurve_for_graph(action, pts):
    if not pts:
        return None
    
    f = pts[0]
    if len(f) >= 6:
        dp, ai, x0, y0, slot_id, bone_name = f
    elif len(f) >= 5:
        dp, ai, x0, y0, slot_id = f
        bone_name = None
    else:
        dp, ai, x0, y0 = f
        slot_id = None
        bone_name = None
    
    if action.is_action_layered:
        if not action.layers or not action.slots:
            return None
        
        layer = action.layers[0]
        if not layer.strips:
            return None
        
        strip = layer.strips[0]
        
        slot = None
        if slot_id:
            for sl in action.slots:
                if sl.identifier == slot_id:
                    slot = sl
                    break
        
        if slot is None:
            if action.slots:
                slot = action.slots[0]
            else:
                return None
        
        cbag = strip.channelbag(slot, ensure=False)
        if not cbag:
            return None
        
        return cbag.fcurves.find(dp, index=ai)
    else:
        return action.fcurves.find(dp, index=ai)

def delete_generated_keyframes(action, pts, s, graph_id):
    if not pts:
        return

    fcurve = get_fcurve_for_graph(action, pts)
    if not fcurve:
        return

    pts_sorted = sorted(pts, key=lambda p: p[2])
    x0 = pts_sorted[0][2]
    x1 = pts_sorted[-1][2]

    to_delete = []

    for idx, kp in enumerate(fcurve.keyframe_points):
        frame = kp.co.x

        if abs(frame - x0) < 1e-6 or abs(frame - x1) < 1e-6:
            continue

        if x0 < frame < x1:
            to_delete.append(idx)

    for idx in reversed(to_delete):
        try:
            fcurve.keyframe_points.remove(fcurve.keyframe_points[idx])
        except:
            pass

    fcurve.update()

    for i in reversed(range(len(s.generated_frames))):
        if s.generated_frames[i].loc_id == graph_id:
            s.generated_frames.remove(i)

def generate_graph_core(action, obj, pts, cfg, graph_id, s):
    if len(pts) < 2:
        return

    dp, ai, _, _, slot_id, bone_name = pts[0]

    if action.is_action_layered:
        if not action.layers:
            layer = action.layers.new("Layer")
        else:
            layer = action.layers[0]

        if not layer.strips:
            strip = layer.strips.new(type='KEYFRAME')
        else:
            strip = layer.strips[0]

        slot = None
        if slot_id:
            for sl in action.slots:
                if sl.identifier == slot_id:
                    slot = sl
                    break
        if slot is None and action.slots:
            slot = action.slots[0]
        if not slot:
            return

        cbag = strip.channelbag(slot, ensure=True)
        fcurve = cbag.fcurves.find(dp, index=ai)
        if not fcurve:
            fcurve = cbag.fcurves.new(dp, index=ai)

    else:
        fcurve = action.fcurves.find(dp, index=ai)
        if not fcurve:
            fcurve = action.fcurves.new(dp, index=ai)

    if not fcurve:
        return

    existing_frames = {round(k.co.x) for k in fcurve.keyframe_points}

    for dp, ai, x, y, slot_id, bone_name in pts:
        if round(x) not in existing_frames:
            fcurve.keyframe_points.insert(frame=x, value=y)

    fcurve.update()

    delete_generated_keyframes(action, pts, s, graph_id)

    for i in reversed(range(len(s.generated_frames))):
        if s.generated_frames[i].loc_id == graph_id:
            s.generated_frames.remove(i)

    pts_sorted = sorted(pts, key=lambda p: p[2])
    updated_pts = []

    frame_to_kp = {round(k.co.x): k for k in fcurve.keyframe_points}

    for dp, ai, x, y, slot_id, bone_name in pts_sorted:
        k = frame_to_kp.get(round(x))
        if k:
            y = k.co.y 
        updated_pts.append([dp, ai, x, y, slot_id, bone_name])

    d = load_saved_points_dict(s)
    d[str(graph_id)] = updated_pts
    save_saved_points_dict(s, d)

    p_sorted = updated_pts
    funcs = {
        'Random': eval_random_offset,
        'Spring': eval_spring_offset,
        'Bounce': lambda c, t, y0, y1: eval_bounce_offset(c, t, y0, y1),
        'Plateau': eval_plateau_offset,
        'Pulse': eval_pulse_offset,
        'Peak': eval_peak_offset,
        'CustomCSS': eval_custom_css_offset,
        'Preset': eval_preset_offset,
    }
    get_offset = funcs.get(cfg.preset, lambda c, t, *_: 0.0)
    sm = cfg.smooth_amount if cfg.smooth_inout else 0.0

    for i in range(len(p_sorted) - 1):
        dp, ai, x0, y0, slot_id, bone_name = p_sorted[i]
        _, _, x1, y1, _, _ = p_sorted[i + 1]

        diff = y1 - y0
        flat = abs(diff) < EPS
        AMP = cfg.strength * (abs(diff) if not flat else 1.0)

        for r in range(1, cfg.resolution + 1):
            t = r / (cfg.resolution + 1)
            base_y = y0 + diff * t if not flat else y0

            if cfg.preset == "Bounce":
                offset = get_offset(cfg, t, y0, y1)
            else:
                offset = get_offset(cfg, t)

            edge = edge_envelope(t, sm)
            y = base_y + offset * AMP * edge
            x = x0 + (x1 - x0) * t

            kp = fcurve.keyframe_points.insert(frame=x, value=y)

            item = s.generated_frames.add()
            item.frame = int(round(kp.co.x))
            item.loc_id = graph_id

    fcurve.update()

def generate_graph(context):
    scene = context.scene
    obj = context.active_object
    s = scene.graphgen_settings

    if not obj or not obj.animation_data or not obj.animation_data.action:
        return False

    act = obj.animation_data.action

    if not str(s.graphgen_location_filter).isdigit():
        return False

    graph_id = int(s.graphgen_location_filter)
    d = load_saved_points_dict(s)

    if str(graph_id) not in d:
        return False

    pts_raw = d[str(graph_id)]
    if len(pts_raw) < 2:
        return False

    pts = []
    for p in pts_raw:
        if len(p) >= 6:
            dp, ai, x, y, slot_id, bone_name = p[:6]
        elif len(p) == 5:
            dp, ai, x, y, slot_id = p
            bone_name = None
        else:
            dp, ai, x, y = p
            slot_id = None
            bone_name = None
        pts.append((dp, ai, x, y, slot_id, bone_name))

    if s.graphgen_bone_filter != "OBJECT":
        extracted_bone = extract_bone_from_path(pts[0][0])
        if extracted_bone != s.graphgen_bone_filter:
            return False

    cfg = _ensure_config_for_loc(s, graph_id)

    generate_graph_core(act, obj, pts, cfg, graph_id, s)
    redraw_graph_editor()
    return True

# --------------------------------
# Operators
# --------------------------------

class GRAPHGENERATOR_OT_save_selected(bpy.types.Operator):
    bl_idname = "graph.save_selected_points"
    bl_label = "Save Keyframes"
    bl_description = "Save selected keyframes as graph anchors (bone & slot aware)"

    def execute(self, context):
        obj = context.active_object
        s = context.scene.graphgen_settings

        if not obj or not obj.animation_data or not obj.animation_data.action:
            self.report({'WARNING'}, "No animation data.")
            return {'CANCELLED'}
        
        act = obj.animation_data.action
        ###
        actor = anim_utils.action_get_channelbag_for_slot(obj.animation_data.action, obj.animation_data.action_slot)
        ###
        d = load_saved_points_dict(s)

        selected = set()
        highlighted_only = s.save_highlighted_only
        ###
        for fc in actor.fcurves:
        ###
            if highlighted_only:
                if not fc.select or fc.hide:
                    continue
            
            has_selected_kp = any(kp.select_control_point for kp in fc.keyframe_points)
            if has_selected_kp:
                selected.add((fc.data_path, fc.array_index, None))

        if act.is_action_layered and act.layers:
            layer = act.layers[0]
            if layer.strips:
                strip = layer.strips[0]

                for slot in act.slots:
                    safe_slot_id = slot.identifier

                    cbag = strip.channelbag(slot, ensure=False)
                    if not cbag:
                        continue

                    for fc in cbag.fcurves:
                        if highlighted_only:
                            if not fc.select or fc.hide:
                                continue

                        has_selected_kp = any(kp.select_control_point for kp in fc.keyframe_points)
                        if has_selected_kp:
                            selected.add((fc.data_path, fc.array_index, safe_slot_id))

        if not selected:
            if highlighted_only:
                self.report({'WARNING'}, "No keyframes selected on highlighted curves.")
            else:
                self.report({'WARNING'}, "No curves selected in Graph Editor.")
            return {'CANCELLED'}

        grouped = {}

        def collect(fc, slot_id):
            bone = extract_bone_from_path(fc.data_path)
            if bone is None or not is_ascii(bone):
                bone = "OBJECT"
            
            key = (fc.data_path, fc.array_index, slot_id, bone)
            selected_kps = []
            for kp in fc.keyframe_points:
                if kp.select_control_point:
                    selected_kps.append((kp.co.x, kp.co.y))
            
            if selected_kps:
                grouped.setdefault(key, []).extend(selected_kps)

        if act.is_action_layered and act.layers:
            layer = act.layers[0]
            if layer.strips:
                strip = layer.strips[0]

                for slot in act.slots:
                    safe_slot_id = slot.identifier
                    cbag = strip.channelbag(slot, ensure=False)
                    if not cbag:
                        continue

                    for fc in cbag.fcurves:
                        if (fc.data_path, fc.array_index, safe_slot_id) in selected:
                            collect(fc, safe_slot_id)
        else:
            for fc in act.fcurves:
                if (fc.data_path, fc.array_index, None) in selected:
                    collect(fc, None)

        if not grouped:
            self.report({'WARNING'}, "No keyframes selected on control points.")
            return {'CANCELLED'}

        existing_ids = [int(k) for k in d.keys()] if d else []
        saved = 0

        for (dp, ai, slot_id, bone), pts in grouped.items():
            if len(pts) < 2:
                self.report({'INFO'}, f"Skipped {bone} - need at least 2 keyframes, found {len(pts)}.")
                continue

            pts_sorted = sorted(pts, key=lambda x: x[0])
            anchors = [[dp, ai, x, y, slot_id, bone] for (x, y) in pts_sorted]

            new_id = max(existing_ids, default=0) + 1
            existing_ids.append(new_id)

            d[str(new_id)] = anchors
            _ensure_config_for_loc(s, new_id)

            saved += 1

        save_saved_points_dict(s, d)
        sanitize_graph_selector(s, context)

        self.report({'INFO'}, f"Saved {saved} graph(s).")
        return {'FINISHED'}

class GRAPHGENERATOR_OT_clear_saved(bpy.types.Operator):
    bl_idname = "graph.clear_saved_points"
    bl_label = "Clear Saved Keyframes"
    bl_description = "Delete the saved keyframes for the currently selected graph"

    def execute(self, context):
        s = context.scene.graphgen_settings
        d = load_saved_points_dict(s)
        graph_key = s.graphgen_location_filter

        if graph_key not in d:
            self.report({'INFO'}, "No saved graph selected.")
            return {'CANCELLED'}

        d.pop(graph_key, None)
        save_saved_points_dict(s, d)

        for i in reversed(range(len(s.graph_configs))):
            if s.graph_configs[i].loc_id == int(graph_key):
                s.graph_configs.remove(i)

        for i in reversed(range(len(s.generated_frames))):
            if s.generated_frames[i].loc_id == int(graph_key):
                s.generated_frames.remove(i)

        new_items = get_dynamic_locations(s, context)
        valid_keys = [item[0] for item in new_items]

        if not valid_keys:
            s.graphgen_location_filter = "0"
        elif s.graphgen_location_filter not in valid_keys:
            s.graphgen_location_filter = valid_keys[0]

        self.report({'INFO'}, "Removed the selected saved graph.")
        return {'FINISHED'}

class GRAPHGENERATOR_OT_generate(bpy.types.Operator):
    bl_idname = "graph.generate_curve"
    bl_label = "Generate Graph"
    bl_description = "Generate in-between keyframes using the selected graph settings"
    bl_options = {'UNDO'}

    def execute(self, context):
        if not generate_graph(context):
            self.report({'WARNING'}, "Ensure at least two saved keyframes exist for this graph.")
            return {'CANCELLED'}
        self.report({'INFO'}, "Graph generated.")
        return {'FINISHED'}

class GRAPHGENERATOR_OT_clear_generated(bpy.types.Operator):
    bl_idname = "graph.clear_generated_points"
    bl_label = "Reset Graph"
    bl_description = "Remove all generated keyframes for the selected graph"
    bl_options = {'UNDO'}

    def execute(self, context):
        scene = context.scene
        obj = context.active_object
        if not obj or not obj.animation_data or not obj.animation_data.action:
            return {'CANCELLED'}

        act = obj.animation_data.action
        s = scene.graphgen_settings

        if not str(s.graphgen_location_filter).isdigit():
            return {'CANCELLED'}

        graph_id = int(s.graphgen_location_filter)

        d = load_saved_points_dict(s)
        pts = d.get(str(graph_id), [])
        if not pts:
            self.report({'INFO'}, "No saved points for this graph.")
            return {'CANCELLED'}

        delete_generated_keyframes(act, pts, s, graph_id)

        for i in reversed(range(len(s.generated_frames))):
            if s.generated_frames[i].loc_id == graph_id:
                s.generated_frames.remove(i)

        redraw_graph_editor()
        self.report({'INFO'}, "Cleared generated keyframes.")
        return {'FINISHED'}

class GRAPHGENERATOR_OT_clear_all_saved(bpy.types.Operator):
    bl_idname = "graph.clear_all_saved_graphs"
    bl_label = "Clear ALL Saved Graphs"
    bl_description = "Delete all saved graphs (use if corruption persists)"
    bl_options = {'UNDO'}

    def execute(self, context):
        s = context.scene.graphgen_settings
        
        s.saved_points_json = "{}"
        s.graph_configs.clear()
        s.generated_frames.clear()
        s.graphgen_location_filter = "0"
        
        self.report({'WARNING'}, "All saved graphs have been cleared.")
        return {'FINISHED'}
    
    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self, event)

# --------------------------------
# UI
# --------------------------------

class GRAPHGENERATOR_PT_panel(bpy.types.Panel):
    bl_space_type = 'GRAPH_EDITOR'
    bl_region_type = 'UI'
    bl_category = 'Graph Generator'
    bl_label = "Graph Generator"

    def draw(self, context):
        layout = self.layout
        s = context.scene.graphgen_settings

        row_top = layout.row(align=True)
        row_top.operator("graph.generate_curve", icon="GRAPH")
        row_live = layout.row(align=True)
        row_live.prop(s, "graphgen_auto_update", text="Live Update", toggle=True)
        row_live.operator("graph.clear_generated_points", text="Reset Graph", icon="X")

        layout.separator()

        row_save = layout.row(align=True)
        row_save.operator("graph.save_selected_points", text="Save Keyframes", icon="KEY_HLT")
        row_save.operator("graph.clear_saved_points", text="Delete Saved", icon="TRASH")
        layout.prop(s, "save_highlighted_only", toggle=True)

        layout.separator()

        bone_count = get_animated_bone_count(context)
        if bone_count >= 2:
            layout.prop(s, "graphgen_bone_filter", text="Filter")
        
        layout.prop(s, "graphgen_location_filter", text="Graph")

        layout.separator()

        d = load_saved_points_dict(s)
        key = s.graphgen_location_filter

        if not d or not key.isdigit() or key == "0":
            layout.label(text="No saved graph selected.", icon="INFO")
            return

        graph_id = int(key)
        pts = d.get(str(graph_id), [])

        if not pts:
            layout.label(text="No data for this graph.", icon="ERROR")
            return

        cfg = _get_config_for_loc(s, graph_id)
        if not cfg:
            layout.label(text="Settings will appear after generating or saving.", icon="INFO")
            return

        layout.prop(cfg, "preset")

        if cfg.preset == 'Spring':
            layout.prop(cfg, "bounce_count")
        elif cfg.preset == 'Random':
            layout.prop(cfg, "seed")
        elif cfg.preset == 'Bounce':
            layout.prop(cfg, "bounce_amount")
        elif cfg.preset == 'Plateau':
            layout.prop(cfg, "plateau_amount")
        elif cfg.preset == 'Pulse':
            layout.prop(cfg, "pulse_amount")
        elif cfg.preset == 'Peak':
            layout.prop(cfg, "peaks_count")
            layout.prop(cfg, "peaks_randomizer")
        elif cfg.preset == 'CustomCSS':
            layout.prop(cfg, "css_string")
        elif cfg.preset == 'Preset':
            layout.prop(cfg, "preset_name")
            layout.prop(cfg, "preset_repeat")

        layout.prop(cfg, "strength")
        layout.prop(cfg, "resolution")

        if cfg.preset == 'Spring':
            layout.prop(cfg, "spring_invert_horiz", toggle=True)
        elif cfg.preset == 'Bounce':
            layout.prop(cfg, "bounce_invert", toggle=True)
        elif cfg.preset == 'CustomCSS':
            layout.prop(cfg, "css_invert_horiz", toggle=True)

        if cfg.preset == 'Preset':
            layout.prop(cfg, "preset_continuous", toggle=True)

        layout.prop(cfg, "smooth_inout", toggle=True)
        if cfg.smooth_inout:
            layout.prop(cfg, "smooth_amount")

        layout.separator()

        layout.operator("graph.clear_all_saved_graphs", text="Clear All Saved", icon="X")

# --------------------------------
# Registration
# --------------------------------

classes = (
    GraphGenConfig,
    GeneratedFramesItem,
    GraphGenSettings,
    GRAPHGENERATOR_OT_save_selected,
    GRAPHGENERATOR_OT_clear_saved,
    GRAPHGENERATOR_OT_generate,
    GRAPHGENERATOR_OT_clear_generated,
    GRAPHGENERATOR_OT_clear_all_saved,
    GRAPHGENERATOR_PT_panel,
)

def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.graphgen_settings = bpy.props.PointerProperty(type=GraphGenSettings)

def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
    del bpy.types.Scene.graphgen_settings

if __name__ == "__main__":
    register()