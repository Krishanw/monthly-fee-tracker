import gspread
from oauth2client.service_account import ServiceAccountCredentials
import pandas as pd

# Google Sheets Setup
def connect_sheets(sheet_name):
    scope = ["https://spreadsheets.google.com/feeds",
             "https://www.googleapis.com/auth/drive"]
    creds = ServiceAccountCredentials.from_json_keyfile_name("config.json", scope)
    client = gspread.authorize(creds)
    sheet = client.open(sheet_name)
    return sheet

def load_data(sheet, tab):
    worksheet = sheet.worksheet(tab)
    data = worksheet.get_all_records()
    return pd.DataFrame(data)

def append_data(sheet, tab, row_values):
    worksheet = sheet.worksheet(tab)
    worksheet.append_row(row_values)
