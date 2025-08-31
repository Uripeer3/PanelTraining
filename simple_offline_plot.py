from bokeh.plotting import figure, show
from bokeh.models import ColumnDataSource, Span, WMTSTileSource, CustomJS
from bokeh.layouts import row
import numpy as np

# --- Example data ---
n = 100
x = np.arange(n)  # line plot x
y = np.sin(x / 10)  # line plot y
lats = 37 + 0.1 * np.sin(x / 15)  # latitude
lons = -122 + 0.1 * np.cos(x / 15)  # longitude


# Convert lat/lon to Web Mercator (needed for Bokeh tiles)
def wgs84_to_web_mercator(lon, lat):
    k = 6378137
    x = lon * (k * np.pi / 180.0)
    y = np.log(np.tan((90 + lat) * np.pi / 360.0)) * k
    return x, y


mx, my = wgs84_to_web_mercator(lons, lats)

# Data sources
line_source = ColumnDataSource(data=dict(x=x, y=y))
marker_source = ColumnDataSource(data=dict(mx=[], my=[]))  # start empty

# --- Line plot ---
p1 = figure(width=400, height=300, tools="crosshair",
            title="Line Plot")
p1.line("x", "y", source=line_source)

# Make this a vertical span (dimension='height') so it appears as a vertical red line at an x value
hover_line = Span(location=None, dimension="height",
                  line_color="red", line_dash="dashed")
p1.add_layout(hover_line)

# --- Map plot ---
tile_provider = WMTSTileSource(url="https://tile.openstreetmap.org/{Z}/{X}/{Y}.png")

p2 = figure(width=400, height=300,
            x_axis_type="mercator", y_axis_type="mercator",
            title="Map with Marker")
p2.add_tile(tile_provider)

p2.scatter(mx, my, size=6, color="blue", alpha=0.5)  # all points
p2.scatter("mx", "my", size=12, color="red", alpha=0.8, source=marker_source)  # marker

# --- Callback for mousemove ---
move_callback = CustomJS(
    args=dict(
        line_src=line_source,
        marker_src=marker_source,
        hover_line=hover_line,
        scatter_x=list(mx),
        scatter_y=list(my),
        yvals=list(y),
    ),
    code="""
    // cb_obj is the event for js_on_event; use its x coordinate (data-space)
    const evt = cb_obj;
    if (!evt) return;
    const x = evt.x;
    if (x == null) return;

    const xs = line_src.data.x;
    // find nearest index by x-value (works even when x is not integer)
    let best = 0;
    let bestDist = Math.abs(xs[0] - x);
    for (let i = 1; i < xs.length; i++) {
        const d = Math.abs(xs[i] - x);
        if (d < bestDist) { bestDist = d; best = i; }
    }
    const ind = best;

        // Place vertical span at the exact x value and move marker to corresponding mercator point
        hover_line.location = xs[ind];
        marker_src.data.mx = [scatter_x[ind]];
        marker_src.data.my = [scatter_y[ind]];
        marker_src.change.emit();
    """,
)

# --- Callback for mouse leave (clear marker + line) ---
leave_callback = CustomJS(args=dict(marker_src=marker_source, hover_line=hover_line),
                          code="""
    hover_line.location = null;
    marker_src.data.mx = [];
    marker_src.data.my = [];
    marker_src.change.emit();
""")

# --- Callback for mousemove on the MAP: find nearest mercator point and update marker/line ---
map_move_callback = CustomJS(
    args=dict(
        line_src=line_source,
        marker_src=marker_source,
        hover_line=hover_line,
        scatter_x=list(mx),
        scatter_y=list(my),
        xs=list(x),
    ),
    code="""
    const evt = cb_obj;
    if (!evt) return;
    const mx_evt = evt.x; // mercator x
    const my_evt = evt.y; // mercator y
    if (mx_evt == null || my_evt == null) return;

    // Find nearest mercator index using 2D distance
    const sx = scatter_x;
    const sy = scatter_y;
    let best = 0;
    let bestDist = (sx[0] - mx_evt) * (sx[0] - mx_evt) + (sy[0] - my_evt) * (sy[0] - my_evt);
    for (let i = 1; i < sx.length; i++) {
        const dx = sx[i] - mx_evt;
        const dy = sy[i] - my_evt;
        const d2 = dx*dx + dy*dy;
        if (d2 < bestDist) { bestDist = d2; best = i; }
    }
    const ind = best;

    // Use the same index to update line vertical position and marker
    const xs_vals = xs;
    hover_line.location = xs_vals[ind];
        marker_src.data.mx = [scatter_x[ind]];
        marker_src.data.my = [scatter_y[ind]];
        marker_src.change.emit();
    """,
)

# Attach to plots: only attach mousemove to the line plot (p1) so x-values map correctly
p1.js_on_event("mousemove", move_callback)
p1.js_on_event("mouseleave", leave_callback)
# For the map only clear on leave
p2.js_on_event("mouseleave", leave_callback)
# Attach map callback so moving over the map also updates marker
p2.js_on_event("mousemove", map_move_callback)

show(row(p1, p2))
