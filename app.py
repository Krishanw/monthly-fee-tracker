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
# Page Config MUST be first
# ==============================
st.set_page_config(page_title="සුහද එකමුතු මොළගොඩ වත්ත ග්‍රාම සංවර්ධන සමිතිය", layout="wide")

# ==============================
# Language Dictionary
# ==============================
LANGUAGES = {
    "English": {
        "title": "සුහද එකමුතු මොළගොඩ වත්ත ග්‍රාම සංවර්ධන සමිතිය",
        "login": "🔐 Admin Login",
        "username": "Username",
        "password": "Password",
        "login_button": "Login",
        "logout": "Logout",
        "welcome_admin": "Welcome, Admin",
        "dashboard": "📊 Admin Dashboard",
        "members": "👥 All Members",
        "fees": "💰 All Fee Records",
        "user_mgmt": "👤 Add / Edit Members",
        "qr_generator": "📦 Bulk QR Code Generator",
        "refresh": "🔄 Refresh Data",
        "payments": "💳 My Monthly Payments",
        "total_expected": "💰 Total Expected",
        "total_received": "✅ Total Received",
        "total_due": "⚠️ Total Outstanding",
        "payment_history": "📊 Payment History",
        "no_payments": "No payment records found yet.",
        "not_found": "❌ Member not found.",
        "download_qr": "⬇️ Download All QR Codes",
        "add_payment": "➕ Add Payment",
        "add_member": "➕ Add New Member",
        "edit_member": "✏️ Edit Member",
        "save": "Save"
    },
    "සිංහල": {
        "title": "🏋 සාමාජික ගාස්තු හා පැමිණීම කළමනාකරණය",
        "login": "🔐 පරිපාලක පිවිසුම",
        "username": "පරිශීලක නාමය",
        "password": "මුරපදය",
        "login_button": "පිවිසෙන්න",
        "logout": "ඉවත් වන්න",
        "welcome_admin": "සාදරයෙන් පිළිගනිමු, පරිපාලක",
        "dashboard": "📊 පරිපාලන පුවරුව",
        "members": "👥 සියලුම සාමාජිකයින්",
        "fees": "💰 සියලු ගාස්තු",
        "user_mgmt": "👤 සාමාජිකයින් එකතු/වෙනස් කිරීම",
        "qr_generator": "📦 QR කේත ජනකය",
        "refresh": "🔄 දත්ත යාවත්කාලීන කරන්න",
        "payments": "💳 මාසික ගෙවීම්",
        "total_expected": "💰 මුළු අපේක්ෂිත මුදල",
        "total_received": "✅ මුළු ලැබූ ගෙවීම්",
        "total_due": "⚠️ ඉතිරි ගෙවීම්",
        "payment_history": "📊 ගෙවීම් ඉතිහාසය",
        "no_payments": "ගෙවීම් තොරතුරු නොමැත.",
        "not_found": "❌ සාමාජිකයා හමු නොවීය.",
        "download_qr": "⬇️ සියලු QR කේතයන් බාගන්න",
        "add_payment": "➕ ගෙවීමක් එක් කරන්න",
        "add_member": "➕ නව සාමාජිකයෙක් එක් කරන්න",
        "edit_member": "✏️ සාමාජිකයෙක් වෙනස් කරන්න",
        "save": "සුරකින්න"
    }
}

# Language selector
lang = st.sidebar.radio("🌐 Language", ["English", "සිංහල"])
t = LANGUAGES[lang]

# Dynamic title
st.title(t["title"])

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
        "Fees": ["Member ID", "Month", "Paid Amount", "Remaining Due", "Paid On"]
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
SHEET_ID = "1aiDyNeK_T3eovJ3_g3D0iXHjh3lLpHJLktGmrzjnp5E"
APP_URL = "https://monthly-fee-tracker-expjkaupcdyn9ahcyicht3.streamlit.app/"

sheet = get_sheet(SHEET_ID)
ensure_sheets_and_headers(sheet)

@st.cache_data(ttl=300)
def cached_load(_sheet, tab):
    return load_data(_sheet, tab)

if st.sidebar.button(t["refresh"]):
    st.cache_data.clear()
    st.success(t["refresh"])

# -------------------------
# QR Mode (Read-Only)
# -------------------------
query_params = st.query_params
if "id" in query_params:
    scanned_id = str(query_params["id"]).strip().lower()
    members = cached_load(sheet, "Members")
    fees = cached_load(sheet, "Fees")

    members["Member ID"] = members["Member ID"].astype(str).str.strip().str.lower()
    fees["Member ID"] = fees["Member ID"].astype(str).str.strip().str.lower()

    member_info = members[members["Member ID"] == scanned_id]

    if not member_info.empty:
        member_name = member_info.iloc[0]["Name"]
        st.success(f"{t['payments']} - {member_name}")
        member_fee = safe_int(member_info.iloc[0]["Monthly Fee"], 0)
        my_fees = fees[fees["Member ID"] == scanned_id]
        if not my_fees.empty:
            my_fees["Monthly Fee"] = member_fee
            my_fees["Remaining Due"] = my_fees["Remaining Due"].apply(safe_int)
            st.write(f"### {t['payment_history']}")
            st.dataframe(my_fees[["Month", "Monthly Fee", "Paid Amount", "Remaining Due"]])
            st.plotly_chart(
                px.bar(my_fees, x="Month", y=["Paid Amount", "Remaining Due"],
                       barmode="group", title=t["payments"]),
                use_container_width=True
            )
        else:
            st.info(t["no_payments"])
    else:
        st.error(t["not_found"])
    st.stop()

# -------------------------
# Admin Login
# -------------------------
if "logged_in" not in st.session_state:
    st.session_state.logged_in = False
    st.session_state.role = None
    st.session_state.username = None

if not st.session_state.logged_in:
    st.subheader(t["login"])
    username = st.text_input(t["username"])
    password = st.text_input(t["password"], type="password")
    members = cached_load(sheet, "Members")

    if st.button(t["login_button"]):
        user = members[(members["Username"] == username) &
                       (members["Password"] == password) &
                       (members["Role"] == "admin") &
                       (members["Status"] == "Active")]
        if not user.empty:
            st.session_state.logged_in = True
            st.session_state.role = "admin"
            st.session_state.username = username
            st.success(t["welcome_admin"])
            st.rerun()
        else:
            st.error("Invalid admin credentials or inactive account.")

else:
    st.sidebar.success(f"{t['welcome_admin']} ({st.session_state.username})")
    if st.sidebar.button(t["logout"]):
        st.session_state.logged_in = False
        st.rerun()

    menu = st.sidebar.selectbox("Navigation", 
        [t["dashboard"], t["members"], t["fees"], t["user_mgmt"], t["qr_generator"]])

    # Dashboard
    if menu == t["dashboard"]:
        st.subheader(t["dashboard"])
        members = cached_load(sheet, "Members")
        fees = cached_load(sheet, "Fees")
        if not fees.empty and not members.empty:
            merged = fees.merge(members[["Member ID", "Name", "Monthly Fee"]],
                                on="Member ID", how="left")
            merged["Monthly Fee"] = merged["Monthly Fee"].apply(safe_int)
            merged["Paid Amount"] = merged["Paid Amount"].apply(safe_int)
            merged["Remaining Due"] = merged["Remaining Due"].apply(safe_int)

            monthly_summary = merged.groupby("Month").agg(
                Total_Fees=("Monthly Fee", "sum"),
                Total_Received=("Paid Amount", "sum"),
                Total_Due=("Remaining Due", "sum")
            ).reset_index()

            st.dataframe(monthly_summary, use_container_width=True)
            col1, col2, col3 = st.columns(3)
            col1.metric(t["total_expected"], monthly_summary["Total_Fees"].sum())
            col2.metric(t["total_received"], monthly_summary["Total_Received"].sum())
            col3.metric(t["total_due"], monthly_summary["Total_Due"].sum())

            st.plotly_chart(
                px.bar(monthly_summary, x="Month", y=["Total_Fees", "Total_Received", "Total_Due"],
                       barmode="group", title=t["dashboard"]),
                use_container_width=True
            )

    # Members
    elif menu == t["members"]:
        st.subheader(t["members"])
        st.dataframe(cached_load(sheet, "Members"), use_container_width=True)

    # Fees
    elif menu == t["fees"]:
        st.subheader(t["fees"])
        fees = cached_load(sheet, "Fees")
        st.dataframe(fees, use_container_width=True)
        with st.form("add_payment"):
            members = cached_load(sheet, "Members")
            member_id = st.selectbox("Select Member", members["Member ID"])
            month = st.text_input("Payment Month", value=date.today().strftime("%b-%y"))
            paid_amount = st.number_input("Paid Amount", min_value=0)
            submit = st.form_submit_button(t["save"])
            if submit:
                add_or_update_fee(sheet, member_id, month, paid_amount)
                st.success("Payment saved!")

    # User Management
    elif menu == t["user_mgmt"]:
        st.subheader(t["user_mgmt"])
        members = cached_load(sheet, "Members")
        st.dataframe(members, use_container_width=True)

        with st.expander(t["add_member"]):
            with st.form("add_member"):
                member_id = st.text_input("Member ID")
                name = st.text_input("Name")
                contact = st.text_input("Contact")
                status = st.selectbox("Status", ["Active", "Inactive"])
                absence_fee = st.number_input("Absence Fee", min_value=0, value=0)
                monthly_fee = st.number_input("Monthly Fee", min_value=0, value=2000)
                username = st.text_input(t["username"])
                password = st.text_input(t["password"])
                role = st.selectbox("Role", ["user", "admin"])
                submitted = st.form_submit_button(t["save"])
                if submitted:
                    append_data(sheet, "Members", [
                        str(member_id).strip(), name, contact, status,
                        absence_fee, monthly_fee, username, password, role
                    ])
                    st.success(f"{name} added!")
                    st.rerun()

        with st.expander(t["edit_member"]):
            if not members.empty:
                edit_id = st.selectbox("Select Member ID to Edit", members["Member ID"])
                member_row = members[members["Member ID"] == edit_id].iloc[0]
                with st.form("edit_member"):
                    name = st.text_input("Name", member_row["Name"])
                    contact = st.text_input("Contact", member_row["Contact"])
                    status = st.selectbox("Status", ["Active", "Inactive"], 
                                          index=["Active","Inactive"].index(member_row["Status"]))
                    absence_fee = st.number_input("Absence Fee", min_value=0,
                                                  value=safe_int(member_row["Absence Fee"], 0))
                    monthly_fee = st.number_input("Monthly Fee", min_value=0,
                                                  value=safe_int(member_row["Monthly Fee"], 2000))
                    username = st.text_input(t["username"], member_row["Username"])
                    password = st.text_input(t["password"], member_row["Password"])
                    role = st.selectbox("Role", ["user", "admin"], 
                                        index=["user","admin"].index(member_row["Role"]))
                    save_changes = st.form_submit_button(t["save"])
                    if save_changes:
                        ws = sheet.worksheet("Members")
                        for idx, row in members.iterrows():
                            if str(row["Member ID"]) == str(edit_id):
                                ws.update(f"A{idx+2}:I{idx+2}", [[
                                    edit_id, name, contact, status,
                                    absence_fee, monthly_fee, username, password, role
                                ]])
                                st.cache_data.clear()
                                st.success(f"{name} updated!")
                                st.rerun()

    # QR Generator
    elif menu == t["qr_generator"]:
        st.subheader(t["qr_generator"])
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
            st.download_button(t["download_qr"], data=zip_buf,
                               file_name="All_QR_Codes.zip", mime="application/zip")

