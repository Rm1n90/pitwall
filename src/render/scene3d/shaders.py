"""GLSL for the 3D circuit view.

Kept in one place so the renderer reads as setup and drawing rather than as
a wall of shader source.
"""

# The circuit surface. Lit by a single low sun, with the white track edges
# and the pit-lane style hatching drawn from the vertex attributes rather
# than from a texture, so nothing has to be loaded or filtered.
TRACK_VERTEX = """
#version 330
uniform mat4 view_projection;

in vec3 in_position;
in vec3 in_normal;
in vec3 in_surface;   // distance around the lap, which edge, and kerb

out vec3 v_normal;
out vec3 v_world;
out float v_along;
out float v_side;
out float v_kerb;

void main() {
    v_normal = in_normal;
    v_world = in_position;
    v_along = in_surface.x;
    v_side = in_surface.y;
    v_kerb = in_surface.z;
    gl_Position = view_projection * vec4(in_position, 1.0);
}
"""

TRACK_FRAGMENT = """
#version 330
uniform vec3 camera_position;
uniform vec3 sun_direction;
uniform vec3 surface_colour;
uniform vec3 edge_colour;
uniform vec3 fog_colour;
uniform float fog_distance;
uniform float edge_width;
uniform float highlight;   // 0 normally, 1 when this stretch is flagged
uniform vec3 highlight_colour;
uniform float kerb_enabled;
uniform float start_line;  // where the lap begins, in metres around it

in vec3 v_normal;
in vec3 v_world;
in float v_along;
in float v_side;
in float v_kerb;

out vec4 f_colour;

void main() {
    vec3 normal = normalize(v_normal);
    float diffuse = max(dot(normal, normalize(sun_direction)), 0.0);

    // Asphalt is not flat grey: a slow variation along the lap keeps a long
    // straight from reading as a single dead block of colour.
    float grain = 0.5 + 0.5 * sin(v_along * 0.35);
    vec3 base = surface_colour * (0.94 + 0.06 * grain);

    // Across the ribbon from the middle outwards: racing surface, the white
    // line, then either a kerb or the run-off beyond it. Real kerbs sit
    // outside the line rather than inside it.
    float across = abs(v_side);
    if (edge_width > 0.0) {
        float line_inner = 1.0 - edge_width * 2.4;
        float line_outer = 1.0 - edge_width * 1.7;

        if (across > line_outer) {
            if (v_kerb > 0.5 && kerb_enabled > 0.5) {
                float band = step(0.5, fract(v_along * 0.22));
                base = mix(vec3(0.74, 0.12, 0.14),
                           vec3(0.88, 0.88, 0.90), band);
            } else {
                base = surface_colour * 0.55;
            }
        } else if (across > line_inner) {
            base = edge_colour;
        }
    }

    // The start line: a chequered band across the full width.
    if (start_line >= 0.0 && abs(v_along - start_line) < 2.4) {
        float check = step(0.5, fract(v_side * 3.0));
        base = mix(vec3(0.09), vec3(0.93), check);
    }

    base = mix(base, highlight_colour, highlight * 0.35);

    vec3 lit = base * (0.58 + 0.62 * diffuse);

    // Fade into the horizon so distance reads as distance.
    float depth = length(v_world - camera_position);
    float fog = clamp(depth / fog_distance, 0.0, 1.0);
    fog = fog * fog * 0.55;

    f_colour = vec4(mix(lit, fog_colour, fog), 1.0);
}
"""

# Cars. One small mesh drawn once per driver, with the position, heading and
# colour supplied per instance so the whole field is a single draw call.
CAR_VERTEX = """
#version 330
uniform mat4 view_projection;

in vec3 in_position;
in vec3 in_normal;

in vec3 in_offset;      // where the car is, in world space
in float in_heading;    // which way it points, in radians
in vec3 in_colour;
in float in_scale;

out vec3 v_normal;
out vec3 v_colour;
out vec3 v_world;

void main() {
    float s = sin(in_heading);
    float c = cos(in_heading);
    mat3 turn = mat3(c, 0.0, -s,
                     0.0, 1.0, 0.0,
                     s, 0.0, c);

    vec3 local = turn * (in_position * in_scale);
    vec3 world = local + in_offset;

    v_normal = turn * in_normal;
    v_colour = in_colour;
    v_world = world;
    gl_Position = view_projection * vec4(world, 1.0);
}
"""

CAR_FRAGMENT = """
#version 330
uniform vec3 sun_direction;
uniform vec3 camera_position;
uniform vec3 fog_colour;
uniform float fog_distance;

in vec3 v_normal;
in vec3 v_colour;
in vec3 v_world;

out vec4 f_colour;

void main() {
    vec3 normal = normalize(v_normal);
    vec3 sun = normalize(sun_direction);
    float diffuse = max(dot(normal, sun), 0.0);

    // A rim light picks the cars out against dark asphalt.
    vec3 view = normalize(camera_position - v_world);
    float rim = pow(1.0 - max(dot(normal, view), 0.0), 2.5);

    vec3 lit = v_colour * (0.62 + 0.62 * diffuse) + vec3(rim * 0.30);

    float depth = length(v_world - camera_position);
    float fog = clamp(depth / fog_distance, 0.0, 1.0);
    fog = fog * fog * 0.35;

    f_colour = vec4(mix(lit, fog_colour, fog), 1.0);
}
"""

# The ground the circuit sits on, and the shadow each car casts on it.
GROUND_VERTEX = """
#version 330
uniform mat4 view_projection;
in vec3 in_position;
out vec3 v_world;
void main() {
    v_world = in_position;
    gl_Position = view_projection * vec4(in_position, 1.0);
}
"""

GROUND_FRAGMENT = """
#version 330
uniform vec3 camera_position;
uniform vec3 ground_colour;
uniform vec3 fog_colour;
uniform float fog_distance;
in vec3 v_world;
out vec4 f_colour;
void main() {
    float depth = length(v_world - camera_position);
    float fog = clamp(depth / fog_distance, 0.0, 1.0);
    f_colour = vec4(mix(ground_colour, fog_colour, fog * fog), 1.0);
}
"""
