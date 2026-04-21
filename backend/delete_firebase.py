import firebase_admin
from firebase_admin import auth, credentials

def init_firebase(service_account_path: str) -> None:
    if not firebase_admin._apps:
        firebase_admin.initialize_app(credentials.Certificate(service_account_path))

def delete_user_by_email(email: str) -> str:
    user = auth.get_user_by_email(email)
    auth.delete_user(user.uid)
    return user.uid  # useful for logging

# usage:
# init_firebase(r"C:\path\to\serviceAccount.json")
# uid = delete_user_by_email("user@example.com")
# print("Deleted uid:", uid)