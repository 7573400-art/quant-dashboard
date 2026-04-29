import re

with open('dashboard.py', 'r') as f:
    content = f.read()

pattern = r"""JSON_FILE = 'service_account\.json'\s*@st\.cache_resource\s*def get_gspread_client\(\):\s*scope = \["https://spreadsheets\.google\.com/feeds", "https://www\.googleapis\.com/auth/drive"\]\s*creds = ServiceAccountCredentials\.from_json_keyfile_name\(JSON_FILE, scope\)\s*return gspread\.authorize\(creds\)"""

replacement = """JSON_FILE = 'service_account.json'

@st.cache_resource
def get_gspread_client():
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    if "gcp_service_account" in st.secrets:
        # Streamlit Cloud 환경
        creds_dict = dict(st.secrets["gcp_service_account"])
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    else:
        # 로컬 환경
        creds = ServiceAccountCredentials.from_json_keyfile_name(JSON_FILE, scope)
    return gspread.authorize(creds)"""

new_content = re.sub(pattern, replacement, content)

with open('dashboard.py', 'w') as f:
    f.write(new_content)
