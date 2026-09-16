from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

class SheetsClient:
    def __init__(self, service_account_info, spreadsheet_id):
        creds = Credentials.from_service_account_info(service_account_info, scopes=SCOPES)
        self.api = build("sheets", "v4", credentials=creds, cache_discovery=False)
        self.spreadsheet_id = spreadsheet_id

    def get(self, range_name):
        return self.api.spreadsheets().values().get(spreadsheetId=self.spreadsheet_id, range=range_name).execute().get("values", [])

    def batch_get(self, ranges):
        res = self.api.spreadsheets().values().batchGet(spreadsheetId=self.spreadsheet_id, ranges=ranges).execute()
        return {r: v.get("values", []) for r, v in zip(ranges, res.get("valueRanges", []))}

    def replace_rows(self, sheet_name, rows, start_row=4):
        self.api.spreadsheets().values().clear(spreadsheetId=self.spreadsheet_id, range=f"'{sheet_name}'!A{start_row}:ZZ", body={}).execute()
        if not rows: return
        self.api.spreadsheets().values().update(spreadsheetId=self.spreadsheet_id, range=f"'{sheet_name}'!A{start_row}", valueInputOption="RAW", body={"values": rows}).execute()

    def append(self, sheet_name, rows):
        if not rows: return
        self.api.spreadsheets().values().append(spreadsheetId=self.spreadsheet_id, range=f"'{sheet_name}'!A:A", valueInputOption="RAW", insertDataOption="INSERT_ROWS", body={"values": rows}).execute()

    def set_value(self, range_name, value):
        self.api.spreadsheets().values().update(spreadsheetId=self.spreadsheet_id, range=range_name, valueInputOption="RAW", body={"values":[[value]]}).execute()
