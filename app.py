import streamlit as st
import pandas as pd
from datetime import date
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import plotly.express as px
from io import BytesIO
import qrcode
import zipfile
import json

# ==============================
# Google Sheets Setup (via Streamlit Secrets)
# ==============================
@st.cache_resource
def get_client():
    scope = ["https://spreadsheets.google.com/feeds",
             "https://www.googleapis.com/auth/drive"]
    creds_dict = json.loads(st.secrets["GOOGLE_SERVICE_ACCOUNT"])
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    return gspread.authorize(creds)

@st.cache_resource
def get_sheet(sheet_id):
    client = get_client()
    return client.open_by_key(sheet_id)

def ensure_sheets_and_headers(sheet):
    required_sheets = {
        "Members": ["Member ID", "Name", "Contact", "Status", "Absence Fee", "Monthly Fee",
                    "Username", "Password", "Role"],
        "Fees": ["Member ID", "Month", "Paid Amount", "Remaining Due", "Paid On"],
        "Attendance": ["Date", "Member ID", "Status"]
    }
    for tab, headers in required_sheets.items():
        try:
            ws = sheet.worksheet(tab)
            if ws.row_values(1) != headers:
                ws.clear()
                ws.append_row(headers)
        except gspread.exceptions.WorksheetNotFound:
            ws = sheet.add_worksheet(title=tab, rows="100", cols=len(headers))
            ws.append_row(headers)

def load_data(sheet, tab):
    ws = sheet.worksheet(tab)
    data = ws.get_all_records()
    return pd.DataFrame(data)

def append_data(sheet, tab, row_values):
    sheet.worksheet(tab).append_row(row_values)
    st.cache_data.clear()

def safe_int(value, default=0):
    try:
        return int(value)
    except (ValueError, TypeError):
        return default

def add_or_update_fee(sheet, member_id, month, paid_amount):
    members = cached_load(sheet, "Members")
    fees = cached_load(sheet, "Fees")
    today = date.today().isoformat()
    member_fee = safe_int(members[members["Member ID"] == member_id]["Monthly Fee"].values[0])

    ws = sheet.worksheet("Fees")
    found = False
    for i, row in fees.iterrows():
        if row["Member ID"] == member_id and row["Month"] == month:
            new_paid = safe_int(row["Paid Amount"]) + paid_amount
            remaining_due = max(member_fee - new_paid, 0)
            ws.update_cell(i+2, fees.columns.get_loc("Paid Amount")+1, new_paid)
            ws.update_cell(i+2, fees.columns.get_loc("Remaining Due")+1, remaining_due)
            ws.update_cell(i+2, fees.columns.get_loc("Paid On")+1, today)
            found = True
            break
    if not found:
        remaining_due = max(member_fee - paid_amount, 0)
        append_data(sheet, "Fees", [member_id, month, paid_amount, remaining_due, today])
    st.cache_data.clear()
    return True

# ==============================
# Streamlit Setup
# ==============================
st.set_page_config(page_title="Member Fee Tracker", layout="wide")
st.title("🏋 Member Fee & Attendance Tracker")

SHEET_ID = "1aiDyNeK_T3eovJ3_g3D0iXHjh3lLpHJLktGmrzjnp5E"
APP_URL = "https://your-app-url.streamlit.app"  # Replace with your Streamlit Cloud URL

sheet = get_sheet(SHEET_ID)
ensure_sheets_and_headers(sheet)

@st.cache_data(ttl=300)
def cached_load(_sheet, tab):
    return load_data(_sheet, tab)

if st.sidebar.button("🔄 Refresh Data"):
    st.cache_data.clear()
    st.success("Data refreshed!")

# -------------------------
# Direct QR Link Mode
# -------------------------
query_params = st.query_params
if "id" in query_params:
    scanned_id = query_params["id"]
    members = cached_load(sheet, "Members")
    fees = cached_load(sheet, "Fees")
    member_info = members[members["Member ID"] == scanned_id]

    if not member_info.empty:
        member_name = member_info.iloc[0]["Name"]
        st.success(f"Payment details for {member_name} ({scanned_id})")

        member_fee = safe_int(member_info.iloc[0]["Monthly Fee"])
        my_fees = fees[fees["Member ID"] == scanned_id]
        if not my_fees.empty:
            my_fees["Monthly Fee"] = member_fee
            my_fees["Remaining Due"] = my_fees["Remaining Due"].astype(int)

            st.write("### 📊 Payment History")
            styled_df = my_fees[["Month", "Monthly Fee", "Paid Amount", "Remaining Due"]].style.apply(
                lambda row: ['background-color: lightcoral' if row["Remaining Due"] > 0 
                             else 'background-color: lightgreen'] * len(row),
                axis=1
            )
            st.dataframe(styled_df, use_container_width=True)

            st.plotly_chart(
                px.bar(my_fees, x="Month", y=["Paid Amount", "Remaining Due"], 
                       barmode="group", title="Monthly Payments"),
                use_container_width=True
            )
        else:
            st.info("No payment records found.")
    else:
        st.error("❌ Member not found.")
    st.stop()

# -------------------------
# Admin / User Login System
# -------------------------
if "logged_in" not in st.session_state:
    st.session_state.logged_in = False
    st.session_state.role = None
    st.session_state.username = None
    st.session_state.member_id = None

if not st.session_state.logged_in:
    st.subheader("🔐 Admin/User Login")
    username = st.text_input("Username")
    password = st.text_input("Password", type="password")
    members = cached_load(sheet, "Members")

    if st.button("Login"):
        user = members[(members["Username"] == username) &
                       (members["Password"] == password) &
                       (members["Status"] == "Active")]
        if not user.empty:
            st.session_state.logged_in = True
            st.session_state.role = user.iloc[0]["Role"]
            st.session_state.username = username
            st.session_state.member_id = user.iloc[0]["Member ID"]
            st.success(f"Welcome, {user.iloc[0]['Name']} ({st.session_state.role})")
            st.rerun()
        else:
            st.error("Invalid credentials or inactive account.")

else:
    st.sidebar.success(f"Logged in as {st.session_state.username} ({st.session_state.role})")
    if st.sidebar.button("Logout"):
        st.session_state.logged_in = False
        st.rerun()

    if st.session_state.role == "admin":
        menu = st.sidebar.selectbox("Navigation", 
            ["Dashboard", "Members", "Fees", "User Management", "QR Generator"])
    else:
        menu = "My Payments"

    # -------------------------
    # Admin Dashboard
    # -------------------------
    if menu == "Dashboard":
        st.subheader("📊 Admin Dashboard")
        members = cached_load(sheet, "Members")
        fees = cached_load(sheet, "Fees")

        if fees.empty or members.empty:
            st.info("No data available to display.")
        else:
            merged = fees.merge(members[["Member ID", "Name", "Monthly Fee"]], on="Member ID", how="left")
            merged["Monthly Fee"] = merged["Monthly Fee"].fillna(0).astype(int)
            merged["Paid Amount"] = merged["Paid Amount"].fillna(0).astype(int)
            merged["Remaining Due"] = merged["Remaining Due"].fillna(0).astype(int)

            # Month-wise Summary
            monthly_summary = merged.groupby("Month").agg(
                Total_Fees=("Monthly Fee", "sum"),
                Total_Received=("Paid Amount", "sum"),
                Total_Due=("Remaining Due", "sum")
            ).reset_index()

            st.write("### 📅 Month-wise Summary")
            styled_summary = monthly_summary.style.apply(
                lambda row: ['background-color: lightcoral' if row["Total_Due"] > 0 
                             else 'background-color: lightgreen'] * len(row),
                axis=1
            )
            st.dataframe(styled_summary, use_container_width=True)

            col1, col2, col3 = st.columns(3)
            col1.metric("Total Fees Expected", monthly_summary["Total_Fees"].sum())
            col2.metric("Total Payments Received", monthly_summary["Total_Received"].sum())
            col3.metric("Total Outstanding Dues", monthly_summary["Total_Due"].sum())

            st.plotly_chart(
                px.bar(monthly_summary, x="Month", y=["Total_Fees", "Total_Received", "Total_Due"],
                       barmode="group", title="Fees vs Payments vs Dues"),
                use_container_width=True
            )

            st.plotly_chart(
                px.line(monthly_summary, x="Month", y="Total_Due", markers=True,
                        title="Outstanding Dues Over Time"),
                use_container_width=True
            )

            # Member-wise Summary
            st.write("### 👤 Member-wise Outstanding Dues")
            member_summary = merged.groupby(["Member ID", "Name"]).agg(
                Total_Fees=("Monthly Fee", "sum"),
                Total_Received=("Paid Amount", "sum"),
                Total_Due=("Remaining Due", "sum")
            ).reset_index()

            styled_member_summary = member_summary.style.apply(
                lambda row: ['background-color: lightcoral' if row["Total_Due"] > 0 
                             else 'background-color: lightgreen'] * len(row),
                axis=1
            )
            st.dataframe(styled_member_summary, use_container_width=True)

            st.plotly_chart(
                px.bar(member_summary, x="Name", y="Total_Due",
                       color="Total_Due", title="Outstanding Dues per Member"),
                use_container_width=True
            )

            # Export to Excel
            st.write("### 📂 Export Reports")
            excel_buffer = BytesIO()
            with pd.ExcelWriter(excel_buffer, engine="xlsxwriter") as writer:
                monthly_summary.to_excel(writer, index=False, sheet_name="Month Summary")
                member_summary.to_excel(writer, index=False, sheet_name="Member Summary")

                workbook = writer.book
                money_fmt = workbook.add_format({'num_format': '#,##0'})
                for sheetname in ["Month Summary", "Member Summary"]:
                    worksheet = writer.sheets[sheetname]
                    worksheet.set_column("B:D", 18, money_fmt)

            excel_buffer.seek(0)
            st.download_button(
                label="⬇️ Download Dashboard Report (Excel)",
                data=excel_buffer,
                file_name="Dashboard_Report.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )

    # -------------------------
    # User View
    # -------------------------
    elif menu == "My Payments":
        st.subheader("💳 My Monthly Payments")
        fees = cached_load(sheet, "Fees")
        members = cached_load(sheet, "Members")
        my_fees = fees[fees["Member ID"] == st.session_state.member_id]

        if my_fees.empty:
            st.info("No payment records found.")
        else:
            member_fee = safe_int(members[members["Member ID"] == st.session_state.member_id]["Monthly Fee"].values[0])
            my_fees["Monthly Fee"] = member_fee
            my_fees["Remaining Due"] = my_fees["Remaining Due"].astype(int)

            st.write("### 📊 My Payment History")
            styled_df = my_fees[["Month", "Monthly Fee", "Paid Amount", "Remaining Due"]].style.apply(
                lambda row: ['background-color: lightcoral' if row["Remaining Due"] > 0 
                             else 'background-color: lightgreen'] * len(row),
                axis=1
            )
            st.dataframe(styled_df, use_container_width=True)

            st.plotly_chart(
                px.bar(my_fees, x="Month", y=["Paid Amount", "Remaining Due"], 
                       barmode="group", title="My Monthly Payments"),
                use_container_width=True
            )

        st.subheader("🎟 My QR Code")
        qr_link = f"{APP_URL}?id={st.session_state.member_id}"
        qr_img = qrcode.make(qr_link)
        buf = BytesIO()
        qr_img.save(buf, format="PNG")
        qr_data = buf.getvalue()
        st.image(qr_data, caption=f"QR for {st.session_state.username}", width=200)
        st.download_button("⬇️ Download My QR Code", data=qr_data,
                           file_name=f"{st.session_state.username}_QR.png", mime="image/png")
