import dash
from dash import dcc, html
from dash.dependencies import Input, Output, State
import pandas as pd
import datetime
import plotly.graph_objects as go

# ------------------------
# Load log file
# ------------------------
LOG_FILE = "atak_logs/data.log"

data = []
with open(LOG_FILE, "r") as f:
    current_time = None
    for line in f:
        line = line.strip()
        if line.startswith("--- Snapshot"):
            ts_str = line.split(" at ")[1].split(" UTC")[0]
            current_time = datetime.datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S")
        elif line.startswith("[") and current_time:
            ts_end = line.index("]")
            entry_time = datetime.datetime.strptime(line[1:ts_end], "%Y-%m-%d %H:%M:%S")
            rest = line[ts_end+2:]
            if ":" in rest:
                user, loc = rest.split(":")
                user = user.strip()
                loc = loc.strip()
                coords = [float(x) for x in loc.split(",")[:2]]  # lon, lat
                tag = "".join([c for c in user if c.isalpha()][:3]).upper()
                data.append({
                    "time": entry_time,
                    "user": user,
                    "lon": coords[0],
                    "lat": coords[1],
                    "tag": tag
                })

df = pd.DataFrame(data)
df.sort_values("time", inplace=True)
unique_times = sorted(df['time'].unique())
unique_tags = df['tag'].unique()

# Tag colors
tag_colors = {}
for tag in unique_tags:
    if tag.startswith("BDR"):
        tag_colors[tag] = "red"
    elif tag.startswith("ETG"):
        tag_colors[tag] = "blue"
    else:
        tag_colors[tag] = f"#{hash(tag) % 0xFFFFFF:06x}"

# ------------------------
# Dash App
# ------------------------
app = dash.Dash(__name__)
app.layout = html.Div([
    html.H1("ATAK Replay Viewer", style={"textAlign": "center"}),

    # Buttons + status
    html.Div([
        html.Div([
            html.Button("Play", id="play-btn", n_clicks=0),
            html.Button("Pause", id="pause-btn", n_clicks=0),
            html.Button("Fast-forward", id="fast-btn", n_clicks=0),
        ], style={"display": "flex", "justifyContent": "center", "gap": "10px", "margin-bottom": "5px"}),

        html.Div(id="play-status", style={"textAlign": "center", "fontWeight": "bold", "fontSize": "18px"})
    ]),

    # Slider
    dcc.Slider(
        id='time-slider',
        min=0,
        max=len(unique_times)-1,
        value=0,
        step=1,
        marks={i: unique_times[i].strftime("%H:%M") 
           for i in range(0, len(unique_times), max(1, len(unique_times)//10))},
        tooltip={"placement": "bottom", "always_visible": True}
    ),

    # Map
    dcc.Graph(id="map-graph", style={"height": "85vh", "width": "100%"}),

    # Interval for playback
    dcc.Interval(
        id="interval-component",
        interval=1000,
        n_intervals=0,
        disabled=True
    ),

    # Store zoom/center
    dcc.Store(id="map-state", data={"center": None, "zoom": 12})
])

# ------------------------
# Map creation
# ------------------------
def create_figure(current_time, center=None, zoom=12):
    # Filter all data up to current_time
    current_df = df[df['time'] <= current_time]

    # Keep only the latest position for each user
    current_df = current_df.sort_values("time").groupby("user").tail(1)

    fig = go.Figure()
    for tag in current_df['tag'].unique():
        tag_df = current_df[current_df['tag'] == tag]
        fig.add_trace(go.Scattermapbox(
            lon=tag_df['lon'],
            lat=tag_df['lat'],
            mode='markers+text',
            marker=dict(size=10, color=tag_colors[tag]),
            text=tag_df['user'],
            textposition="top right",
            name=tag
        ))

    # Center map
    if center is None:
        if not current_df.empty:
            center_lat = current_df['lat'].mean()
            center_lon = current_df['lon'].mean()
        else:
            center_lat, center_lon = -41.289, 174.762
    else:
        center_lat, center_lon = center

    fig.update_layout(
        mapbox_style="open-street-map",
        mapbox=dict(center=dict(lat=center_lat, lon=center_lon), zoom=zoom),
        margin={"l":0,"r":0,"t":0,"b":0},
        legend=dict(title=""),
        dragmode="pan"
    )
    return fig


# ------------------------
# Callbacks
# ------------------------

# Map update when slider moves
@app.callback(
    Output("map-graph", "figure"),
    Input("time-slider", "value"),
    State("map-state", "data")
)
def update_map(slider_value, map_state):
    center = map_state.get("center")
    zoom = map_state.get("zoom", 12)
    current_time = unique_times[slider_value]
    return create_figure(current_time, center=center, zoom=zoom)

# Update zoom/center on map interaction
@app.callback(
    Output("map-state", "data"),
    Input("map-graph", "relayoutData"),
    State("map-state", "data"),
    prevent_initial_call=True
)
def update_map_state(relayout, current_state):
    if relayout is None:
        return current_state
    center = current_state["center"]
    zoom = current_state["zoom"]
    if "mapbox.center" in relayout:
        center = (relayout["mapbox.center"]["lat"], relayout["mapbox.center"]["lon"])
    if "mapbox.zoom" in relayout:
        zoom = relayout["mapbox.zoom"]
    return {"center": center, "zoom": zoom}

# Play/Pause/Fast-forward control
@app.callback(
    Output("interval-component", "disabled"),
    Output("interval-component", "interval"),
    Output("play-status", "children"),
    Input("play-btn", "n_clicks"),
    Input("pause-btn", "n_clicks"),
    Input("fast-btn", "n_clicks")
)
def control_interval(play, pause, fast):
    ctx = dash.callback_context
    if not ctx.triggered:
        return True, 1000, "Paused ⏸️"
    button_id = ctx.triggered[0]["prop_id"].split(".")[0]
    if button_id == "play-btn":
        return False, 1000, "Playing ▶️"
    elif button_id == "fast-btn":
        return False, 100, "Fast-forward ⏩"
    else:
        return True, 1000, "Paused ⏸️"

# Advance slider for playback
@app.callback(
    Output("time-slider", "value"),
    Input("interval-component", "n_intervals"),
    State("time-slider", "value")
)
def advance_slider(n, current_value):
    if current_value < len(unique_times)-1:
        return current_value + 1
    return current_value

# ------------------------
# Run app
# ------------------------
if __name__ == "__main__":
    app.run(debug=True)
