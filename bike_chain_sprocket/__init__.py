# SPDX-License-Identifier: GPL-3.0-or-later
"""Parametric bicycle-chain sprocket generator for Blender."""

bl_info = {
    "name": "Bike Chain Sprocket Generator",
    "author": "Eric Roehrich / Hermes Agent",
    "version": (1, 4, 0),
    "blender": (3, 6, 0),
    "location": "3D View > Add > Mesh > Bicycle Chain Sprocket",
    "description": "Generate chain-compatible sprockets with 5 or more teeth",
    "category": "Add Mesh",
}

import math

import bpy
from bpy_extras.object_utils import AddObjectHelper, object_data_add
from bpy.props import EnumProperty, FloatProperty, IntProperty
from bpy.types import Operator


MM_TO_M = 0.001

# Pitch, roller diameter and a conservative suggested sprocket thickness in mm.
# Thickness is intentionally below nominal chain inner width to leave side play.
CHAIN_PRESETS = {
    "BICYCLE_1_8": (12.700, 7.750, 2.80),
    "BICYCLE_3_32": (12.700, 7.750, 2.00),
    "BICYCLE_11_128": (12.700, 7.750, 1.80),
    "MOTORCYCLE_415": (12.700, 7.770, 4.30),
    "MOTORCYCLE_420": (12.700, 7.770, 5.80),
    "MOTORCYCLE_428": (12.700, 8.510, 7.30),
    "MOTORCYCLE_520": (15.875, 10.160, 5.80),
    "MOTORCYCLE_525": (15.875, 10.160, 7.30),
    "MOTORCYCLE_530": (15.875, 10.160, 8.80),
}


def _apply_chain_preset(self, context):
    values = CHAIN_PRESETS.get(self.chain_preset)
    if values is None:
        return
    self.chain_pitch_mm, self.roller_diameter_mm, self.thickness_mm = values


def _smootherstep(value):
    """C2 blend used to restrict directional pitch deformation to tooth tips."""
    value = max(0.0, min(1.0, value))
    return value * value * value * (value * (value * 6.0 - 15.0) + 10.0)


def calculate_profile(
    teeth,
    chain_pitch_mm,
    roller_diameter_mm,
    roller_clearance_mm,
    tooth_height_mm,
    tooth_tip_flat_mm,
    samples_per_tooth,
    rotation_radians=0.0,
):
    """Return the outer 2D sprocket profile and its design radii in millimetres.

    Roller seats are true circular arcs around roller centres on the pitch circle.
    C2-continuous quintic Hermite flanks connect those seats to rounded radial tooth tips.
    """
    pitch_angle = math.tau / teeth
    half_pitch_angle = pitch_angle * 0.5
    pitch_radius = chain_pitch_mm / (2.0 * math.sin(math.pi / teeth))
    roller_radius = roller_diameter_mm * 0.5 + roller_clearance_mm
    if roller_radius >= pitch_radius:
        raise ValueError("Roller radius/clearance is too large for this tooth count")

    root_radius = pitch_radius - roller_radius
    tip_radius = pitch_radius + tooth_height_mm

    # Keep the exact roller-seat arc slightly inside its tangency limit. For very
    # small tooth counts, this leaves enough angular space for a usable flank.
    tangency_angle = math.asin(roller_radius / pitch_radius)
    seat_half_angle = min(half_pitch_angle * 0.62, tangency_angle * 0.75)
    seat_radicand = (
        roller_radius * roller_radius
        - pitch_radius
        * pitch_radius
        * math.sin(seat_half_angle)
        * math.sin(seat_half_angle)
    )
    seat_root = math.sqrt(max(0.0, seat_radicand))
    seat_end_radius = pitch_radius * math.cos(seat_half_angle) - seat_root
    seat_end_slope = (
        -pitch_radius * math.sin(seat_half_angle)
        + pitch_radius
        * pitch_radius
        * math.sin(seat_half_angle)
        * math.cos(seat_half_angle)
        / seat_root
    )
    seat_u = (
        pitch_radius
        * pitch_radius
        * math.sin(seat_half_angle)
        * math.cos(seat_half_angle)
    )
    seat_u_slope = pitch_radius * pitch_radius * (
        math.cos(seat_half_angle) ** 2 - math.sin(seat_half_angle) ** 2
    )
    seat_end_curvature = (
        -pitch_radius * math.cos(seat_half_angle)
        + seat_u_slope / seat_root
        + seat_u * seat_u / (seat_root * seat_root * seat_root)
    )
    maximum_tip_flat = tip_radius - seat_end_radius - 0.05
    if tooth_tip_flat_mm < 0.0 or tooth_tip_flat_mm > maximum_tip_flat:
        raise ValueError(
            f"Tooth tip flattening must be between 0 and {maximum_tip_flat:.3f} mm"
        )
    flat_tip_radius = tip_radius - tooth_tip_flat_mm

    # Split each tooth into explicit flank and seat segments. This guarantees
    # vertices at both seat endpoints, the valley centre, and every tooth tip.
    effective_samples = samples_per_tooth + samples_per_tooth % 2
    seat_intervals = max(2, round(effective_samples * seat_half_angle / pitch_angle))
    flank_intervals = effective_samples // 2 - seat_intervals
    segments = (
        (-half_pitch_angle, -seat_half_angle, flank_intervals),
        (-seat_half_angle, 0.0, seat_intervals),
        (0.0, seat_half_angle, seat_intervals),
        (seat_half_angle, half_pitch_angle, flank_intervals),
    )

    points = []
    for tooth in range(teeth):
        valley_angle = rotation_radians + tooth * pitch_angle
        local_angles = []
        for start, end, interval_count in segments:
            local_angles.extend(
                start + (end - start) * sample / interval_count
                for sample in range(interval_count)
            )
        for local_angle in local_angles:
            absolute_local = abs(local_angle)
            if absolute_local <= seat_half_angle:
                # Near-side intersection of a radial ray and the roller circle.
                under_root = (
                    roller_radius * roller_radius
                    - pitch_radius
                    * pitch_radius
                    * math.sin(local_angle)
                    * math.sin(local_angle)
                )
                radius = (
                    pitch_radius * math.cos(local_angle)
                    - math.sqrt(max(0.0, under_root))
                )
            else:
                flank_angle = half_pitch_angle - seat_half_angle
                blend = (absolute_local - seat_half_angle) / flank_angle
                # Quintic Hermite interpolation matches position, slope and
                # curvature at the seat and ends flat at the tooth tip.
                coefficient_0 = seat_end_radius
                coefficient_1 = flank_angle * seat_end_slope
                coefficient_2 = (
                    flank_angle * flank_angle * seat_end_curvature * 0.5
                )
                delta_position = tip_radius - (
                    coefficient_0 + coefficient_1 + coefficient_2
                )
                delta_slope = -(coefficient_1 + 2.0 * coefficient_2)
                delta_curvature = -2.0 * coefficient_2
                coefficient_3 = (
                    10.0 * delta_position
                    - 4.0 * delta_slope
                    + 0.5 * delta_curvature
                )
                coefficient_4 = (
                    -15.0 * delta_position
                    + 7.0 * delta_slope
                    - delta_curvature
                )
                coefficient_5 = (
                    6.0 * delta_position
                    - 3.0 * delta_slope
                    + 0.5 * delta_curvature
                )
                radius = (
                    coefficient_0
                    + blend
                    * (
                        coefficient_1
                        + blend
                        * (
                            coefficient_2
                            + blend
                            * (
                                coefficient_3
                                + blend * (coefficient_4 + blend * coefficient_5)
                            )
                        )
                    )
                )
            if tooth_tip_flat_mm > 0.0:
                # Intersect the rounded profile with a line tangent to the
                # requested flat-tip radius. All clipped points lie on one
                # true straight cap instead of a constant-radius arc.
                tip_offset = half_pitch_angle - absolute_local
                flat_cap_radius = flat_tip_radius / math.cos(tip_offset)
                radius = min(radius, flat_cap_radius)
            angle = valley_angle + local_angle
            points.append((radius * math.cos(angle), radius * math.sin(angle)))

    outside_radius = max(math.hypot(x, y) for x, y in points)
    return points, {
        "pitch_radius_mm": pitch_radius,
        "root_radius_mm": root_radius,
        "tip_radius_mm": tip_radius,
        "flat_tip_radius_mm": flat_tip_radius,
        "outside_radius_mm": outside_radius,
        "roller_seat_radius_mm": roller_radius,
        "pitch_angle_radians": pitch_angle,
        "seat_half_angle_radians": seat_half_angle,
    }


def build_sprocket_mesh(
    name,
    teeth,
    chain_pitch_mm,
    roller_diameter_mm,
    roller_clearance_mm,
    tooth_height_mm,
    tooth_tip_flat_mm,
    thickness_mm,
    bore_diameter_mm,
    samples_per_tooth,
    rotation_radians=0.0,
    scene_scale_length=1.0,
    overall_scale=1.0,
    tooth_tip_pitch_radians=0.0,
):
    """Build a closed, manifold Blender mesh with an axial circular bore."""
    outline_mm, dimensions = calculate_profile(
        teeth,
        chain_pitch_mm,
        roller_diameter_mm,
        roller_clearance_mm,
        tooth_height_mm,
        tooth_tip_flat_mm,
        samples_per_tooth,
        rotation_radians,
    )
    bore_radius_mm = bore_diameter_mm * 0.5
    if bore_radius_mm >= dimensions["root_radius_mm"] - 0.25:
        raise ValueError(
            "Bore is too large: leave at least 0.25 mm material below the tooth roots"
        )

    count = len(outline_mm)
    mm_to_blender_units = (
        MM_TO_M * overall_scale / max(scene_scale_length, 1e-12)
    )
    half_thickness = thickness_mm * mm_to_blender_units * 0.5
    outer = [(x * mm_to_blender_units, y * mm_to_blender_units) for x, y in outline_mm]
    inner = []
    for x, y in outline_mm:
        angle = math.atan2(y, x)
        inner.append(
            (
                bore_radius_mm * mm_to_blender_units * math.cos(angle),
                bore_radius_mm * mm_to_blender_units * math.sin(angle),
            )
        )

    pitch_angle = dimensions["pitch_angle_radians"]
    half_pitch_angle = pitch_angle * 0.5
    seat_half_angle = dimensions["seat_half_angle_radians"]

    def pitched_outer_ring():
        ring = []
        for (x_mm, y_mm), (x, y) in zip(outline_mm, outer):
            angle = math.atan2(y_mm, x_mm)
            local_angle = (
                (angle - rotation_radians + half_pitch_angle) % pitch_angle
            ) - half_pitch_angle
            influence = _smootherstep(
                (abs(local_angle) - seat_half_angle)
                / (half_pitch_angle - seat_half_angle)
            )
            twist = tooth_tip_pitch_radians * influence
            cosine = math.cos(twist)
            sine = math.sin(twist)
            ring.append((x * cosine - y * sine, x * sine + y * cosine))
        return ring

    vertices = []
    pitched_outer = pitched_outer_ring()
    for z in (-half_thickness, half_thickness):
        vertices.extend((x, y, z) for x, y in pitched_outer)
        vertices.extend((x, y, z) for x, y in inner)

    bottom_outer = 0
    bottom_inner = count
    top_outer = count * 2
    top_inner = count * 3
    faces = []
    for index in range(count):
        next_index = (index + 1) % count
        bo_i, bo_j = bottom_outer + index, bottom_outer + next_index
        bi_i, bi_j = bottom_inner + index, bottom_inner + next_index
        to_i, to_j = top_outer + index, top_outer + next_index
        ti_i, ti_j = top_inner + index, top_inner + next_index

        faces.append((to_i, to_j, ti_j, ti_i))       # top annulus
        faces.append((bo_i, bi_i, bi_j, bo_j))       # bottom annulus
        faces.append((bo_i, bo_j, to_j, to_i))       # outer wall
        faces.append((bi_i, ti_i, ti_j, bi_j))       # bore wall

    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(vertices, [], faces)
    mesh.validate(verbose=False)
    mesh.update(calc_edges=True)
    return mesh, dimensions


class MESH_OT_add_bike_chain_sprocket(Operator, AddObjectHelper):
    """Create a bicycle-chain sprocket using roller-seat geometry"""

    bl_idname = "mesh.add_bike_chain_sprocket"
    bl_label = "Bicycle Chain Sprocket"
    bl_options = {"REGISTER", "UNDO", "PRESET"}

    chain_preset: EnumProperty(
        name="Chain Size Preset",
        description="Load pitch, roller diameter and suggested sprocket thickness",
        items=(
            ("CUSTOM", "Custom", "Keep manually entered dimensions"),
            ("BICYCLE_1_8", 'Bicycle 1/8" · Single-speed/BMX', "12.7 mm pitch, 7.75 mm roller, 2.80 mm sprocket"),
            ("BICYCLE_3_32", 'Bicycle 3/32" · Derailleur', "12.7 mm pitch, 7.75 mm roller, 2.00 mm sprocket"),
            ("BICYCLE_11_128", 'Bicycle 11/128" · Narrow 10–12 speed', "12.7 mm pitch, 7.75 mm roller, 1.80 mm sprocket"),
            ("MOTORCYCLE_415", "Motorcycle 415", "12.7 mm pitch, 7.77 mm roller, 4.30 mm sprocket"),
            ("MOTORCYCLE_420", "Motorcycle 420", "12.7 mm pitch, 7.77 mm roller, 5.80 mm sprocket"),
            ("MOTORCYCLE_428", "Motorcycle 428", "12.7 mm pitch, 8.51 mm roller, 7.30 mm sprocket"),
            ("MOTORCYCLE_520", "Motorcycle 520", "15.875 mm pitch, 10.16 mm roller, 5.80 mm sprocket"),
            ("MOTORCYCLE_525", "Motorcycle 525", "15.875 mm pitch, 10.16 mm roller, 7.30 mm sprocket"),
            ("MOTORCYCLE_530", "Motorcycle 530", "15.875 mm pitch, 10.16 mm roller, 8.80 mm sprocket"),
        ),
        default="BICYCLE_3_32",
        update=_apply_chain_preset,
    )
    teeth: IntProperty(
        name="Teeth",
        description="Number of teeth; five is the geometric minimum supported here",
        default=5,
        min=5,
        max=150,
    )
    chain_pitch_mm: FloatProperty(
        name="Chain Pitch (mm)",
        description="Pin-to-pin distance; bicycle chains normally use 12.7 mm (1/2 inch)",
        default=12.7,
        min=1.0,
        max=100.0,
        precision=3,
    )
    roller_diameter_mm: FloatProperty(
        name="Roller Diameter (mm)",
        description="Bicycle-chain roller diameter; typically about 7.75 mm",
        default=7.75,
        min=0.5,
        max=50.0,
        precision=3,
    )
    roller_clearance_mm: FloatProperty(
        name="Roller Clearance (mm)",
        description="Radial clearance added around each chain roller",
        default=0.15,
        min=0.0,
        max=2.0,
        precision=3,
    )
    tooth_height_mm: FloatProperty(
        name="Tooth Height above Pitch Circle (mm)",
        description="Radial distance from the pitch circle to each tooth tip",
        default=0.45,
        min=0.0,
        max=10.0,
        precision=3,
    )
    tooth_tip_pitch: FloatProperty(
        name="Tooth Tip Pitch",
        description=(
            "Shift the upper and lower tooth tip together in one tangential "
            "direction; roller seats remain unchanged"
        ),
        default=math.radians(1.5),
        min=math.radians(-15.0),
        max=math.radians(15.0),
        subtype="ANGLE",
        unit="ROTATION",
    )
    tooth_tip_flat_mm: FloatProperty(
        name="Tooth Tip Flattening (mm)",
        description="Cut each rounded tooth tip with a straight tangential cap",
        default=0.0,
        min=0.0,
        max=5.0,
        precision=3,
    )
    thickness_mm: FloatProperty(
        name="Thickness (mm)",
        description="Axial sprocket thickness; match this to the chain's inner width",
        default=2.0,
        min=0.1,
        max=30.0,
        precision=3,
    )
    bore_diameter_mm: FloatProperty(
        name="Bore Diameter (mm)",
        description="Diameter of the circular centre bore",
        default=5.0,
        min=0.1,
        max=200.0,
        precision=3,
    )
    overall_scale: FloatProperty(
        name="Scale",
        description="Uniformly scale pitch, teeth, bore, thickness and bevel",
        default=1.0,
        min=0.01,
        max=100.0,
        precision=3,
    )
    samples_per_tooth: IntProperty(
        name="Profile Resolution",
        description="Vertices per tooth; higher values produce smoother roller seats",
        default=32,
        min=12,
        max=128,
    )
    profile_rotation: FloatProperty(
        name="Profile Rotation",
        description="Rotate the generated tooth pattern around the Z axis",
        default=0.0,
        min=math.radians(-180.0),
        max=math.radians(180.0),
        subtype="ANGLE",
        unit="ROTATION",
    )
    bevel_width_mm: FloatProperty(
        name="Edge Bevel (mm)",
        description="Non-destructive bevel modifier width; zero disables it",
        default=0.10,
        min=0.0,
        max=2.0,
        precision=3,
    )
    bevel_segments: IntProperty(
        name="Bevel Segments",
        default=2,
        min=1,
        max=8,
    )

    @classmethod
    def poll(cls, context):
        return context.mode == "OBJECT"

    def draw(self, context):
        layout = self.layout
        chain = layout.box()
        chain.label(text="Chain and Teeth")
        chain.prop(self, "chain_preset")
        chain.prop(self, "teeth")
        chain.prop(self, "chain_pitch_mm")
        chain.prop(self, "roller_diameter_mm")
        chain.prop(self, "roller_clearance_mm")
        chain.prop(self, "tooth_height_mm")
        chain.prop(self, "tooth_tip_pitch")
        chain.prop(self, "tooth_tip_flat_mm")

        body = layout.box()
        body.label(text="Body")
        body.prop(self, "thickness_mm")
        body.prop(self, "bore_diameter_mm")
        body.prop(self, "overall_scale")
        body.prop(self, "profile_rotation")

        finish = layout.box()
        finish.label(text="Mesh Quality")
        finish.prop(self, "samples_per_tooth")
        finish.prop(self, "bevel_width_mm")
        if self.bevel_width_mm > 0.0:
            finish.prop(self, "bevel_segments")

        placement = layout.box()
        placement.label(text="Placement")
        placement.prop(self, "align")
        placement.prop(self, "location")
        placement.prop(self, "rotation")

    def execute(self, context):
        name = f"Bike_Sprocket_{self.teeth}T"
        try:
            mesh, dimensions = build_sprocket_mesh(
                name=name,
                teeth=self.teeth,
                chain_pitch_mm=self.chain_pitch_mm,
                roller_diameter_mm=self.roller_diameter_mm,
                roller_clearance_mm=self.roller_clearance_mm,
                tooth_height_mm=self.tooth_height_mm,
                tooth_tip_flat_mm=self.tooth_tip_flat_mm,
                thickness_mm=self.thickness_mm,
                bore_diameter_mm=self.bore_diameter_mm,
                samples_per_tooth=self.samples_per_tooth,
                rotation_radians=self.profile_rotation,
                scene_scale_length=context.scene.unit_settings.scale_length,
                overall_scale=self.overall_scale,
                tooth_tip_pitch_radians=self.tooth_tip_pitch,
            )
        except ValueError as error:
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}

        obj = object_data_add(context, mesh, operator=self, name=name)
        obj["teeth"] = self.teeth
        obj["chain_preset"] = self.chain_preset
        obj["overall_scale"] = self.overall_scale
        obj["chain_pitch_mm"] = self.chain_pitch_mm
        obj["roller_diameter_mm"] = self.roller_diameter_mm
        obj["tooth_tip_pitch_degrees"] = math.degrees(self.tooth_tip_pitch)
        obj["tooth_tip_flattening_mm"] = (
            self.tooth_tip_flat_mm * self.overall_scale
        )
        obj["pitch_diameter_mm"] = (
            dimensions["pitch_radius_mm"] * 2.0 * self.overall_scale
        )
        obj["outside_diameter_mm"] = (
            dimensions["outside_radius_mm"] * 2.0 * self.overall_scale
        )
        obj["profile_type"] = (
            "circular roller seats, C2 Hermite flanks, directional pitch and flat caps"
        )

        if self.bevel_width_mm > 0.0:
            bevel = obj.modifiers.new(name="Manufacturing Edge Bevel", type="BEVEL")
            bevel.width = (
                self.bevel_width_mm
                * MM_TO_M
                * self.overall_scale
                / max(context.scene.unit_settings.scale_length, 1e-12)
            )
            bevel.segments = self.bevel_segments
            bevel.limit_method = "ANGLE"
            bevel.angle_limit = math.radians(20.0)

        if self.teeth <= 8:
            self.report(
                {"WARNING"},
                "5T-8T is supported geometrically but causes extreme chain articulation",
            )

        return {"FINISHED"}


def menu_func(self, context):
    self.layout.operator(
        MESH_OT_add_bike_chain_sprocket.bl_idname,
        text="Bicycle Chain Sprocket",
        icon="MESH_CIRCLE",
    )


classes = (MESH_OT_add_bike_chain_sprocket,)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.VIEW3D_MT_mesh_add.append(menu_func)


def unregister():
    bpy.types.VIEW3D_MT_mesh_add.remove(menu_func)
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)


if __name__ == "__main__":
    register()
