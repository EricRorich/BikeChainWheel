#!/usr/bin/env python3
"""Create a Blender demo file containing default 5T through 11T sprockets."""
from pathlib import Path
import importlib
import math
import sys

import bpy

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
addon = importlib.import_module("bike_chain_sprocket")
addon.register()

bpy.ops.object.select_all(action="SELECT")
bpy.ops.object.delete(use_global=False)

x = 0.0
for teeth in range(5, 12):
    bpy.ops.mesh.add_bike_chain_sprocket(
        teeth=teeth,
        bevel_width_mm=0.10,
        bevel_segments=2,
    )
    obj = bpy.context.active_object
    obj.location.x = x
    obj.name = f"Bike_Sprocket_{teeth}T"
    pitch_radius = 12.7 / (2.0 * math.sin(math.pi / teeth))
    x += (2.0 * (pitch_radius + 0.45) + 8.0) * 0.001

bpy.ops.wm.save_as_mainfile(filepath=str(ROOT / "BikeChainWheel_5T-11T_Demo.blend"))
print(ROOT / "BikeChainWheel_5T-11T_Demo.blend")
addon.unregister()
