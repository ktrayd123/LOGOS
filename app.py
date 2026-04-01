import dash
from dash import dcc, html, Input, Output, State, callback
import dash_ag_grid as dag
import pandas as pd
import os
import re
import base64
import io

DATA_DIR = "data"
CLEAN_FILE = os.path.join(DATA_DIR, "carriers_clean.xlsx")
os.makedirs(DATA_DIR, exist_ok=True)

def clean_phone(phone):
    if pd.isna(phone):
        return ""
    s = str(phone)
    digits = re.sub(r'[^\d+]', '', s)
    if digits.startswith('8') and len(digits) == 11:
        digits = '+7' + digits[1:]
    elif digits.startswith('7') and len(digits) == 11:
        digits = '+' + digits
    elif digits.startswith('9') and len(digits) == 10:
        digits = '+7' + digits
    return digits

def clean_location(loc):
    if pd.isna(loc):
        return ""
    s = str(loc).strip()
    s = re.sub(r'^[\"\']+|[\"\']+$', '', s)
    return re.sub(r'\s+', ' ', s)

def preprocess(df):
    # Если в вашем файле колонки называются иначе, измените здесь
    clean = pd.DataFrame({
        "from_location": df["а"].astype(str).apply(clean_location),
        "to_location": df["Куда"].astype(str).apply(clean_location),
        "phone": df["Контакты"].astype(str).apply(clean_phone),
        "er_name": df["Наименование"].astype(str).apply(clean_location)
    })
    clean["type_ts"] = ""
    clean["color"] = "white"
    clean["votes"] = 0
    clean["id"] = range(len(clean))
    clean = clean[(clean["from_location"] != "") & (clean["to_location"] != "") & (clean["phone"] != "")].reset_index(drop=True)
    clean["id"] = range(len(clean))
    return clean

def load_data():
    if os.path.exists(CLEAN_FILE):
        df = pd.read_excel(CLEAN_FILE, engine='openpyxl')
        for col in ["type_ts", "color", "votes", "id"]:
            if col not in df.columns:
                if col == "id":
                    df[col] = range(len(df))
                else:
                    df[col] = 0 if col == "votes" else ("white" if col == "color" else "")
        return df
    return None

def save_data(df):
    df.to_excel(CLEAN_FILE, index=False, engine='openpyxl')

# Автоматическая загрузка из файла в репозитории, если нет сохранённых данных
global_df = load_data()
if global_df is None:
    default_file = os.path.join("data", "carriers_data-_3_.xls")
    if os.path.exists(default_file):
        try:
            raw = pd.read_excel(default_file, engine='openpyxl', dtype=str)
            clean = preprocess(raw)
            if not clean.empty:
                global_df = clean
                save_data(global_df)
        except Exception as e:
            print(f"Ошибка загрузки файла по умолчанию: {e}")

app = dash.Dash(__name__, suppress_callback_exceptions=True)
server = app.server

app.layout = html.Div([
    html.H1("📦 Поиск перевозчика по маршруту", style={"textAlign": "center"}),
    dcc.Upload(
        id="upload-data",
        children=html.Div(["📂 Перетащите файл или ", html.A("выберите файл")]),
        style={
            "width": "100%", "height": "60px", "lineHeight": "60px",
            "borderWidth": "1px", "borderStyle": "dashed", "borderRadius": "5px",
            "textAlign": "center", "margin": "10px"
        },
        multiple=False
    ),
    html.Div(id="upload-output"),
    html.Div([
        html.Div([
            html.Label("Откуда"),
            dcc.Input(id="from-input", type="text", debounce=True, style={"width": "100%"}),
        ], style={"width": "48%", "display": "inline-block"}),
        html.Div([
            html.Label("Куда"),
            dcc.Input(id="to-input", type="text", debounce=True, style={"width": "100%"}),
        ], style={"width": "48%", "float": "right", "display": "inline-block"}),
    ], style={"margin": "20px 0"}),
    html.Div(id="table-container"),
    html.Button("💾 Сохранить изменения", id="save-button", n_clicks=0, style={"margin": "20px"}),
    html.Div(id="save-message")
])

def update_table_data(global_df, from_val, to_val):
    if global_df is None or global_df.empty:
        return None
    df = global_df.copy()
    mask = pd.Series([True] * len(df))
    if from_val:
        mask &= df["from_location"].str.contains(from_val, case=False, na=False)
    if to_val:
        mask &= df["to_location"].str.contains(to_val, case=False, na=False)
    filtered = df[mask].sort_values("votes", ascending=False).reset_index(drop=True)
    return filtered

@callback(
    Output("upload-output", "children"),
    Input("upload-data", "contents"),
    State("upload-data", "filename")
)
def handle_upload(contents, filename):
    global global_df
    if contents is None:
        return dash.no_update
    content_type, content_string = contents.split(",")
    decoded = base64.b64decode(content_string)
    try:
        if filename.endswith(".csv"):
            raw = pd.read_csv(io.StringIO(decoded.decode("utf-8")), dtype=str)
        else:
            raw = pd.read_excel(io.BytesIO(decoded), engine="openpyxl", dtype=str)
        clean = preprocess(raw)
        if clean.empty:
            return html.Div("Ошибка: не удалось извлечь данные. Проверьте колонки.")
        global_df = clean
        save_data(global_df)
        return html.Div(f"✅ Загружено {len(clean)} записей")
    except Exception as e:
        return html.Div(f"❌ Ошибка: {e}")

@callback(
    Output("table-container", "children"),
    Input("from-input", "value"),
    Input("to-input", "value")
)
def display_table(from_val, to_val):
    global global_df
    filtered = update_table_data(global_df, from_val, to_val)
    if filtered is None or filtered.empty:
        return html.Div("Нет данных")
    filtered = filtered.fillna("")
    column_defs = [
        {"field": "from_location", "headerName": "Откуда", "editable": False},
        {"field": "to_location", "headerName": "Куда", "editable": False},
        {"field": "phone", "headerName": "Телефон", "editable": True},
        {"field": "carrier_name", "headerName": "Перевозчик", "editable": True},
        {"field": "type_ts", "headerName": "Тип ТС", "editable": True},
        {
            "field": "color",
            "headerName": "Цвет",
            "editable": True,
            "cellEditor": "agSelectCellEditor",
            "cellEditorParams": {"values": ["green", "yellow", "white", "red"]}
        },
        {"field": "votes", "headerName": "Голоса", "editable": True, "type": "numericColumn"},
        {"field": "id", "headerName": "ID", "hide": True}
    ]
    row_style = {
        "styleConditions": [
            {"condition": "params.data.color == 'green'", "style": {"backgroundColor": "#ccffcc"}},
            {"condition": "params.data.color == 'yellow'", "style": {"backgroundColor": "#ffffcc"}},
            {"condition": "params.data.color == 'red'", "style": {"backgroundColor": "#ffcccc"}},
            {"condition": "params.data.color == 'white'", "style": {"backgroundColor": "#ffffff"}}
        ]
    }
    return dag.AgGrid(
        id="carrier-grid",
        rowData=filtered.to_dict("records"),
        columnDefs=column_defs,
        defaultColDef={"resizable": True, "sortable": True, "filter": True},
        getRowStyle=row_style,
        dashGridOptions={"rowSelection": "single", "animateRows": False},
        style={"height": 600, "width": "100%"}
    )

@callback(
    Output("save-message", "children"),
    Input("save-button", "n_clicks"),
    State("carrier-grid", "rowData"),
)
def save_changes(n_clicks, row_data):
    global global_df
    if n_clicks == 0 or row_data is None:
        return ""
    edited_df = pd.DataFrame(row_data)
    for _, row in edited_df.iterrows():
        row_id = row["id"]
        orig_idx = global_df[global_df["id"] == row_id].index
        if not orig_idx.empty:
            for col in ["phone", "carrier_name", "type_ts", "color", "votes"]:
                if col in row:
                    global_df.loc[orig_idx[0], col] = row[col]
    save_data(global_df)
    return html.Div("✅ Изменения сохранены!", style={"color": "green"})

if __name__ == "__main__":
    import os
    port = int(os.environ.get("PORT", 8050))
    app.run(debug=False, host="0.0.0.0", port=port)
