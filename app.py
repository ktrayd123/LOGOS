import dash
from dash import dcc, html, Input, Output, State, callback
import dash_ag_grid as dag
import pandas as pd
import os
import re
import base64
import io
import json
import gspread
from google.oauth2.service_account import Credentials

# ======================= НАСТРОЙКИ GOOGLE SHEETS =======================
# Замените на ID вашей таблицы (из URL)
SHEET_ID = "1sB7h5QPO1XV2liqZAF8weMPhdHJApxUJBHVde_wzU4o"   # <-- ВСТАВЬТЕ СВОЙ ID

# Переменная окружения на Render (содержит JSON-ключ)
CRED_JSON = os.environ.get("GOOGLE_CREDENTIALS_JSON")

def get_worksheet():
    """Подключается к Google Sheets и возвращает первый лист."""
    if not CRED_JSON:
        raise Exception("Переменная окружения GOOGLE_CREDENTIALS_JSON не задана")
    cred_dict = json.loads(CRED_JSON)
    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
    creds = Credentials.from_service_account_info(cred_dict, scopes=scopes)
    client = gspread.authorize(creds)
    sheet = client.open_by_key(SHEET_ID)
    return sheet.get_worksheet(0)

def load_data_from_gsheet():
    """Загружает данные из Google Sheets в DataFrame."""
    try:
        ws = get_worksheet()
        records = ws.get_all_records()
        if not records:
            return None
        df = pd.DataFrame(records)
        # Все данные из Sheets приходят как строки, оставляем как есть
        df = df.astype(str)
        # Добавляем недостающие колонки (если их нет)
        for col in ["type_ts", "color", "votes", "id"]:
            if col not in df.columns:
                if col == "id":
                    df[col] = range(len(df))
                else:
                    df[col] = 0 if col == "votes" else ("white" if col == "color" else "")
        if "id" not in df.columns:
            df["id"] = range(len(df))
        # Преобразуем голоса в числа
        df["votes"] = pd.to_numeric(df["votes"], errors="coerce").fillna(0).astype(int)
        return df
    except Exception as e:
        print(f"Ошибка загрузки из Google Sheets: {e}")
        return None

def save_data_to_gsheet(df):
    """Сохраняет DataFrame в Google Sheets (полная замена данных)."""
    try:
        ws = get_worksheet()
        ws.clear()
        if df.empty:
            return
        # Заменяем NaN на пустые строки
        df = df.fillna("")
        # Подготавливаем данные: сначала заголовки, потом строки
        data = [df.columns.tolist()] + df.values.tolist()
        ws.update(data, value_input_option="USER_ENTERED")
        print(f"Сохранено {len(df)} записей в Google Sheets")
    except Exception as e:
        print(f"Ошибка сохранения в Google Sheets: {e}")

# ======================= ОСТАЛЬНОЙ КОД (БЕЗ ИЗМЕНЕНИЙ) =======================
DATA_DIR = "data"
CLEAN_FILE = os.path.join(DATA_DIR, "carriers_clean.csv")
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
    print("Колонки в загруженном файле:", list(df.columns))
    clean = pd.DataFrame({
        "from_location": df["Откуда"].astype(str).apply(clean_location),
        "to_location": df["Куда"].astype(str).apply(clean_location),
        "phone": df["Контакты"].astype(str).apply(clean_phone),
        "carrier_name": df["Наименование"].astype(str).apply(clean_location)
    })
    clean["type_ts"] = ""
    clean["color"] = "white"
    clean["votes"] = 0
    clean["id"] = range(len(clean))
    clean = clean[(clean["from_location"] != "") & (clean["to_location"] != "") & (clean["phone"] != "")].reset_index(drop=True)
    clean["id"] = range(len(clean))
    return clean

# -------------------------------
# Загрузка глобальных данных (теперь из Google Sheets)
# -------------------------------
global_df = load_data_from_gsheet()

# Если в Google Sheets нет данных, пробуем загрузить из файла по умолчанию и сохранить в Sheets
if global_df is None or global_df.empty:
    default_file = os.path.join(DATA_DIR, "carriers_data.csv")
    if not os.path.exists(default_file):
        default_file = os.path.join(DATA_DIR, "carriers_data.xlsx")
    print(f"=== Проверка файла по умолчанию: {default_file} ===")
    if os.path.exists(default_file):
        print(f"Файл найден, размер: {os.path.getsize(default_file)} байт")
        try:
            if default_file.endswith('.csv'):
                raw = pd.read_csv(default_file, dtype=str)
            else:
                raw = pd.read_excel(default_file, engine='openpyxl', dtype=str)
            print(f"Файл прочитан, строк: {len(raw)}")
            clean = preprocess(raw)
            if not clean.empty:
                global_df = clean
                save_data_to_gsheet(global_df)
                print(f"✅ Загружено {len(clean)} записей из файла и сохранено в Google Sheets")
            else:
                print("❌ После очистки нет записей")
        except Exception as e:
            print(f"❌ Ошибка загрузки файла по умолчанию: {e}")
    else:
        print(f"Файл {default_file} не найден, создаём пустой DataFrame")
        global_df = pd.DataFrame(columns=["from_location","to_location","phone","carrier_name","type_ts","color","votes","id"])

# ======================= DASH APP (БЕЗ ИЗМЕНЕНИЙ) =======================
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
        save_data_to_gsheet(global_df)
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
    save_data_to_gsheet(global_df)
    return html.Div("✅ Изменения сохранены в Google Sheets!", style={"color": "green"})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8050))
    app.run(debug=False, host="0.0.0.0", port=port)
