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
# Google Sheets Setup
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
    member_fee = safe_int(
        members[members["Member ID"] == member_id]["Monthly Fee"].values[0], 0
    )

    ws = sheet.worksheet("Fees")
    found = False
    for i, row in fees.iterrows():
        if str(row["Member ID"]) == str(member_id) and row["Month"] == month:
            new_paid = safe_int(row["Paid Amount"], 0) + paid_amount
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
APP_URL = "https://monthly-fee-tracker-expjkaupcdyn9ahcyicht3.streamlit.app/"  # Replace with your deployed URL

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
    scanned_id = str(query_params["id"]).strip().lower()
    members = cached_load(sheet, "Members")
    fees = cached_load(sheet, "Fees")

    # Normalize IDs
    members["Member ID"] = members["Member ID"].astype(str).str.strip().str.lower()
    fees["Member ID"] = fees["Member ID"].astype(str).str.strip().str.lower()

    st.write("🔎 Debug Info")  # remove later
    st.write("Scanned ID:", scanned_id)
    st.write("Available IDs:", members["Member ID"].tolist())

    member_info = members[members["Member ID"] == scanned_id]

    if not member_info.empty:
        member_name = member_info.iloc[0]["Name"]
        st.success(f"💳 Payment details for {member_name} ({scanned_id})")

        member_fee = safe_int(member_info.iloc[0]["Monthly Fee"], 0)
        my_fees = fees[fees["Member ID"] == scanned_id]

        if not my_fees.empty:
            my_fees["Monthly Fee"] = member_fee
            my_fees["Remaining Due"] = my_fees["Remaining Due"].apply(lambda x: safe_int(x, 0))
            st.write("### 📊 Payment History")
            st.dataframe(my_fees[["Month", "Monthly Fee", "Paid Amount", "Remaining Due"]])
        else:
            st.info("No payment records found yet.")

        st.write("### ➕ Add New Payment")
        with st.form("qr_payment_form"):
            month = st.text_input("Payment Month", value=date.today().strftime("%b-%y"))
            paid_amount = st.number_input("Paid Amount", min_value=0)
            submit = st.form_submit_button("Save Payment")
            if submit:
                add_or_update_fee(sheet, scanned_id, month, paid_amount)
                st.success(f"✅ Payment of {paid_amount} recorded for {member_name} ({month})")
                st.rerun()
    else:
        st.error(f"❌ Member with ID {scanned_id} not found.")
    st.stop()

# -------------------------
# Login System
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
            st.session_state.member_id = str(user.iloc[0]["Member ID"]).strip().lower()
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
    # Dashboard
    # -------------------------
    if menu == "Dashboard":
        st.subheader("📊 Admin Dashboard")
        members = cached_load(sheet, "Members")
        fees = cached_load(sheet, "Fees")
        if fees.empty or members.empty:
            st.info("No data available to display.")
        else:
            merged = fees.merge(members[["Member ID", "Name", "Monthly Fee"]], on="Member ID", how="left")
            merged["Monthly Fee"] = merged["Monthly Fee"].apply(lambda x: safe_int(x, 0))
            merged["Paid Amount"] = merged["Paid Amount"].apply(lambda x: safe_int(x, 0))
            merged["Remaining Due"] = merged["Remaining Due"].apply(lambda x: safe_int(x, 0))

            monthly_summary = merged.groupby("Month").agg(
                Total_Fees=("Monthly Fee", "sum"),
                Total_Received=("Paid Amount", "sum"),
                Total_Due=("Remaining Due", "sum")
            ).reset_index()

            st.dataframe(monthly_summary, use_container_width=True)

            total_expected = monthly_summary["Total_Fees"].sum()
            total_received = monthly_summary["Total_Received"].sum()
            total_due = monthly_summary["Total_Due"].sum()

            col1, col2, col3 = st.columns(3)
            col1.metric("💰 Total Expected", total_expected)
            col2.metric("✅ Total Received", total_received)
            col3.metric("⚠️ Total Outstanding", total_due)

            st.plotly_chart(
                px.bar(monthly_summary, x="Month", y=["Total_Fees", "Total_Received", "Total_Due"],
                       barmode="group", title="Fees vs Payments vs Dues"),
                use_container_width=True
            )

            st.plotly_chart(
                px.pie(values=[total_received, total_due],
                       names=["Received", "Due"],
                       title="Overall Payment Status"),
                use_container_width=True
            )

            st.plotly_chart(
                px.line(monthly_summary, x="Month", y="Total_Received", markers=True, 
                        title="Payment Trend Over Time"),
                use_container_width=True
            )

    # -------------------------
    # Members Page
    # -------------------------
    elif menu == "Members":
        st.subheader("👥 All Members")
        st.dataframe(cached_load(sheet, "Members"), use_container_width=True)

    # -------------------------
    # Fees Page
    # -------------------------
    elif menu == "Fees":
        st.subheader("💰 All Fee Records")
        fees = cached_load(sheet, "Fees")
        st.dataframe(fees, use_container_width=True)
        with st.form("add_payment"):
            members = cached_load(sheet, "Members")
            member_id = st.selectbox("Select Member", members["Member ID"])
            month = st.text_input("Payment Month", value=date.today().strftime("%b-%y"))
            paid_amount = st.number_input("Paid Amount", min_value=0)
            submit = st.form_submit_button("Save Payment")
            if submit:
                add_or_update_fee(sheet, member_id, month, paid_amount)
                st.success(f"Payment updated for {member_id} ({month})")

    # -------------------------
    # User Management Page
    # -------------------------
    elif menu == "User Management":
        st.subheader("👤 Add / Edit Members")
        members = cached_load(sheet, "Members")
        st.dataframe(members, use_container_width=True)

        # Add New Member
        with st.expander("➕ Add New Member"):
            with st.form("add_member"):
                member_id = st.text_input("Member ID")
                name = st.text_input("Name")
                contact = st.text_input("Contact")
                status = st.selectbox("Status", ["Active", "Inactive"])
                absence_fee = st.number_input("Absence Fee", min_value=0, value=0)
                monthly_fee = st.number_input("Monthly Fee", min_value=0, value=2000)
                username = st.text_input("Username")
                password = st.text_input("Password")
                role = st.selectbox("Role", ["user", "admin"])
                submitted = st.form_submit_button("Add Member")
                if submitted:
                    append_data(sheet, "Members", [
                        str(member_id).strip(), name, contact, status,
                        absence_fee, monthly_fee, username, password, role
                    ])
                    st.success(f"✅ Member {name} added successfully!")
                    st.rerun()

        # Edit Existing Member
        with st.expander("✏️ Edit Existing Member"):
            if not members.empty:
                edit_id = st.selectbox("Select Member ID to Edit", members["Member ID"])
                member_row = members[members["Member ID"] == edit_id].iloc[0]
                with st.form("edit_member"):
                    name = st.text_input("Name", member_row["Name"])
                    contact = st.text_input("Contact", member_row["Contact"])
                    status = st.selectbox("Status", ["Active", "Inactive"], 
                                          index=["Active","Inactive"].index(member_row["Status"]))
                    absence_fee = st.number_input("Absence Fee", min_value=0, value=safe_int(member_row["Absence Fee"], 0))
                    monthly_fee = st.number_input("Monthly Fee", min_value=0, value=safe_int(member_row["Monthly Fee"], 2000))
                    username = st.text_input("Username", member_row["Username"])
                    password = st.text_input("Password", member_row["Password"])
                    role = st.selectbox("Role", ["user", "admin"], 
                                        index=["user","admin"].index(member_row["Role"]))
                    save_changes = st.form_submit_button("Update Member")
                    if save_changes:
                        ws = sheet.worksheet("Members")
                        for idx, row in members.iterrows():
                            if str(row["Member ID"]) == str(edit_id):
                                ws.update(f"A{idx+2}:I{idx+2}", [[
                                    edit_id, name, contact, status, absence_fee, monthly_fee,
                                    username, password, role
                                ]])
                                st.cache_data.clear()
                                st.success(f"✅ Member {name} updated successfully!")
                                st.rerun()

    # -------------------------
    # QR Generator
    # -------------------------
    elif menu == "QR Generator":
        st.subheader("📦 Bulk QR Code Generator")
        members = cached_load(sheet, "Members")
        if st.button("Generate QR Codes"):
            zip_buf = BytesIO()
            with zipfile.ZipFile(zip_buf, "w") as zipf:
                for _, row in members.iterrows():
                    qr_link = f"{APP_URL}?id={str(row['Member ID']).strip().lower()}"
                    qr_img = qrcode.make(qr_link)
                    qr_buf = BytesIO()
                    qr_img.save(qr_buf, format="PNG")
                    zipf.writestr(f"{row['Name']}_{row['Member ID']}.png", qr_buf.getvalue())
            zip_buf.seek(0)
            st.download_button("⬇️ Download All QR Codes", data=zip_buf,
                               file_name="All_QR_Codes.zip", mime="application/zip")

    # -------------------------
    # My Payments
    # -------------------------
    elif menu == "My Payments":
        st.subheader("💳 My Monthly Payments")
        fees = cached_load(sheet, "Fees")
        my_fees = fees[fees["Member ID"] == st.session_state.member_id]
        if not my_fees.empty:
            my_fees["Remaining Due"] = my_fees["Remaining Due"].apply(lambda x: safe_int(x, 0))
            st.dataframe(my_fees, use_container_width=True)
