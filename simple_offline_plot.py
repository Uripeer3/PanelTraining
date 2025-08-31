"""
simple_offline_plot.py

Interactive MapLinkPlot class that links a line plot and a tiled map:
- moving over the line highlights the corresponding map point,
- moving over the map highlights the nearest point and updates the line span,
- a PreText widget shows the selected latitude/longitude.

API:
    plot() -> returns bokeh layout (row)
    show() -> displays the layout in a browser (convenience)
    save(filepath: str) -> saves a standalone HTML file
"""

from typing import Tuple, Optional
from bokeh.models.tiles import WMTSTileSource
from bokeh.plotting import figure, show
from bokeh.models import ColumnDataSource, Span, CustomJS, PreText
from bokeh.layouts import row
from bokeh.io import output_file, save as bokeh_save
import numpy as np


def wgs84_to_web_mercator(lon: np.ndarray, lat: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    """Convert arrays of lon/lat (degrees) to Web-Mercator (meters)."""
    k = 6378137.0
    x = lon * (k * np.pi / 180.0)
    y = np.log(np.tan((90.0 + lat) * np.pi / 360.0)) * k
    return x, y


def create_data(n: int = 100):
    """Create example data (line x/y and corresponding lon/lat arrays)."""
    x = np.arange(n)
    y = np.sin(x / 10.0)
    lats = 37.0 + 0.0001 * np.sin(x / 15.0)
    lons = -122.0 + 0.0001 * np.cos(x / 15.0)
    return x, y, lons, lats


class MapLinkPlot:
    """Encapsulates creation of linked line + tiled map plot with interactive JS callbacks.

    Usage:
        mlp = MapLinkPlot(n=100)
        layout = mlp.plot(x, y, lons, lats)   # supply data or omit to use example
        mlp.show()
        mlp.save("out.html")
    """

    def __init__(self, n: int = 100) -> None:
        # Do not build layout here; allow the user to supply data to plot()
        self.n = n
        self._layout = None
        # placeholders for data sources and widgets
        self.line_source = None
        self.marker_source = None
        self.future_text = None

    def line_plot(self) -> "tuple[bokeh.plotting.figure, Span]":
        """Create and return the line plot and its vertical Span.

        Expects self.line_source to be set.
        """
        p1 = figure(width=400, height=300, tools="crosshair", title="Line Plot")
        p1.line("x", "y", source=self.line_source)
        hover_line = Span(location=None, dimension="height", line_color="red", line_dash="dashed")
        p1.add_layout(hover_line)
        return p1, hover_line

    def scatter_plot(self, mx: np.ndarray, my: np.ndarray) -> "bokeh.plotting.figure":
        """Create and return the mercator tiled map figure with points.

        Expects self.marker_source to be set; draws the full point set from mx/my
        and the movable marker using the marker_source.
        """
        tile_provider = WMTSTileSource(
            url="https://tile.openstreetmap.org/{Z}/{X}/{Y}.png",
            max_zoom=22,
            attribution="&copy; OpenStreetMap contributors"
        )
        p2 = figure(
            width=400, height=300, x_axis_type="mercator", y_axis_type="mercator",
            title="Map with Marker",
        )
        p2.add_tile(tile_provider)
        p2.circle(x=mx, y=my, size=6, color="blue", alpha=0.5)
        p2.circle("mx", "my", size=12, color="red", alpha=0.8, source=self.marker_source)
        return p2

    def _build(self, x: np.ndarray, y: np.ndarray, lons: np.ndarray, lats: np.ndarray) -> None:
        """Internal: build layout from provided arrays (x, y, lon, lat)."""
        # convert to mercator
        mx, my = wgs84_to_web_mercator(lons, lats)

        # store arrays for JS args
        self._x_arr = list(x)
        self._mx_arr = list(mx)
        self._my_arr = list(my)
        self._lon_arr = list(lons)
        self._lat_arr = list(lats)

        # Data sources
        self.line_source = ColumnDataSource(data=dict(x=x, y=y))
        self.marker_source = ColumnDataSource(data=dict(mx=[], my=[]))

        # PreText widget
        self.future_text = PreText(text="lat: -, lon: -", width=300)

        # --- Line plot and hover span (created via helper) ---
        p1, hover_line = self.line_plot()

        # --- Map plot with tile provider and points (created via helper) ---
        p2 = self.scatter_plot(mx, my)

        # --- Callbacks (JS) ---
        move_callback = CustomJS(
            args=dict(
                line_src=self.line_source,
                marker_src=self.marker_source,
                hover_line=hover_line,
                scatter_x=self._mx_arr,
                scatter_y=self._my_arr,
                scatter_lon=self._lon_arr,
                scatter_lat=self._lat_arr,
                future_text=self.future_text,
            ),
            code="""
            const evt = cb_obj;
            if (!evt) return;
            const x_evt = evt.x;
            if (x_evt == null) return;

            const xs = line_src.data.x;
            let best = 0;
            let bestDist = Math.abs(xs[0] - x_evt);
            for (let i = 1; i < xs.length; i++) {
                const d = Math.abs(xs[i] - x_evt);
                if (d < bestDist) { bestDist = d; best = i; }
            }
            const ind = best;

            hover_line.location = xs[ind];
            marker_src.data.mx = [scatter_x[ind]];
            marker_src.data.my = [scatter_y[ind]];
            future_text.text = "lat: " + scatter_lat[ind].toFixed(6) + ", lon: " + scatter_lon[ind].toFixed(6);
            marker_src.change.emit();
            """,
        )

        leave_callback = CustomJS(
            args=dict(marker_src=self.marker_source, hover_line=hover_line, future_text=self.future_text),
            code="""
            hover_line.location = null;
            marker_src.data.mx = [];
            marker_src.data.my = [];
            future_text.text = "lat: -, lon: -";
            marker_src.change.emit();
            """,
        )

        map_move_callback = CustomJS(
            args=dict(
                line_src=self.line_source,
                marker_src=self.marker_source,
                hover_line=hover_line,
                scatter_x=self._mx_arr,
                scatter_y=self._my_arr,
                scatter_lon=self._lon_arr,
                scatter_lat=self._lat_arr,
                xs=self._x_arr,
                future_text=self.future_text,
            ),
            code="""
            const evt = cb_obj;
            if (!evt) return;
            const mx_evt = evt.x;
            const my_evt = evt.y;
            if (mx_evt == null || my_evt == null) return;

            const sx = scatter_x;
            const sy = scatter_y;
            let best = 0;
            let dx0 = sx[0] - mx_evt;
            let dy0 = sy[0] - my_evt;
            let bestDist = dx0*dx0 + dy0*dy0;
            for (let i = 1; i < sx.length; i++) {
                const dx = sx[i] - mx_evt;
                const dy = sy[i] - my_evt;
                const d2 = dx*dx + dy*dy;
                if (d2 < bestDist) { bestDist = d2; best = i; }
            }
            const ind = best;

            hover_line.location = xs[ind];
            marker_src.data.mx = [scatter_x[ind]];
            marker_src.data.my = [scatter_y[ind]];
            future_text.text = "lat: " + scatter_lat[ind].toFixed(6) + ", lon: " + scatter_lon[ind].toFixed(6);
            marker_src.change.emit();
            """,
        )

        # Attach events
        p1.js_on_event("mousemove", move_callback)
        p1.js_on_event("mouseleave", leave_callback)
        p2.js_on_event("mousemove", map_move_callback)
        p2.js_on_event("mouseleave", leave_callback)

        # store layout
        self._layout = row(p1, p2, self.future_text)

    def plot(
        self, x: np.ndarray = None, y: np.ndarray = None,
        lons: np.ndarray = None, lats: np.ndarray = None,
    ):
        """Build and return the Bokeh layout. If any data is missing, use example data.

        Parameters:
            x, y: arrays for the line plot
            lons, lats: arrays of longitudes and latitudes (degrees) for the map points
        """
        if x is None or y is None or lons is None or lats is None:
            x, y, lons, lats = create_data(self.n)
        # ensure numpy arrays
        x = np.asarray(x)
        y = np.asarray(y)
        lons = np.asarray(lons)
        lats = np.asarray(lats)

        # build the layout from the provided data
        self._build(x, y, lons, lats)
        return self._layout

    def show(self) -> None:
        """Show the plot in a browser (convenience wrapper)."""
        show(self._layout)

    def save(self, filepath: str, title: Optional[str] = "MapLinkPlot") -> None:
        """Save the current plot to an HTML file (standalone)."""
        output_file(filepath, title=title)
        bokeh_save(self._layout)


# Example usage (kept guarded)
if __name__ == "__main__":
    # create example data and pass it explicitly into plot()
    x, y, lons, lats = create_data(n=100)
    mlp = MapLinkPlot(n=100)
    mlp.plot(x=x, y=y, lons=lons, lats=lats)  # build layout with provided data
    mlp.show()
