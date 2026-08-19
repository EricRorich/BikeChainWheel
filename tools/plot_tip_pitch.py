#!/usr/bin/env python3
"""Create a visual QA sheet for the directional tooth-tip pitch control."""
from pathlib import Path
import importlib
import math
import sys

import matplotlib.pyplot as plt
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
addon = importlib.import_module("bike_chain_sprocket")

parameters = dict(
    name="TipPitchPreview",
    teeth=11,
    chain_pitch_mm=12.7,
    roller_diameter_mm=7.75,
    roller_clearance_mm=0.15,
    tooth_height_mm=0.45,
    tooth_tip_flat_mm=0.0,
    thickness_mm=2.0,
    bore_diameter_mm=5.0,
    samples_per_tooth=48,
)
baseline_mesh, _ = addon.build_sprocket_mesh(
    **parameters,
    tooth_tip_pitch_radians=0.0,
)
pitched_mesh, _ = addon.build_sprocket_mesh(
    **parameters,
    tooth_tip_pitch_radians=math.radians(6.0),
)
count = 11 * 48
baseline = np.array([baseline_mesh.vertices[index].co[:] for index in range(count)]) * 1000.0
bottom = np.array([pitched_mesh.vertices[index].co[:] for index in range(count)]) * 1000.0
top = np.array([pitched_mesh.vertices[count * 2 + index].co[:] for index in range(count)]) * 1000.0
baseline = np.vstack((baseline, baseline[0]))
bottom = np.vstack((bottom, bottom[0]))
top = np.vstack((top, top[0]))

fig = plt.figure(figsize=(12, 6))
axis = fig.add_subplot(1, 2, 1)
axis.plot(baseline[:, 0], baseline[:, 1], color="#777d86", label="Pitch 0°")
axis.plot(bottom[:, 0], bottom[:, 1], color="#d45252", label="Pitch +6°")
axis.set_aspect("equal")
axis.set_title("11T · Tooth Tip Pitch · Draufsicht")
axis.legend()
axis.grid(True, alpha=0.2)
axis.set_xlabel("X [mm]")
axis.set_ylabel("Y [mm]")

axis3d = fig.add_subplot(1, 2, 2, projection="3d")
for index in range(0, count, 4):
    axis3d.plot(
        [bottom[index, 0], top[index, 0]],
        [bottom[index, 1], top[index, 1]],
        [bottom[index, 2], top[index, 2]],
        color="#555b66",
        linewidth=0.6,
    )
axis3d.plot(bottom[:, 0], bottom[:, 1], bottom[:, 2], color="#3676c5")
axis3d.plot(top[:, 0], top[:, 1], top[:, 2], color="#d45252")
axis3d.set_title("Oben und unten gleichgerichtet")
axis3d.set_xlabel("X [mm]")
axis3d.set_ylabel("Y [mm]")
axis3d.set_zlabel("Z [mm]")
axis3d.view_init(elev=34, azim=-58)
fig.tight_layout()
out = ROOT / "BikeChainWheel_TipPitch_Preview.png"
fig.savefig(out, dpi=180, bbox_inches="tight", facecolor="white")
print(out)
